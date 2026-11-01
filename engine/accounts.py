"""Local user accounts. Each account owns its own folder (settings, database, audio).

Passwords are hashed with scrypt; nothing leaves this machine.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
MIN_PASSWORD = 6
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LEGACY_FILES = ("settings.json", "murmel.db", "audio")


class AuthError(ValueError):
    """Raised for user-facing authentication problems."""


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    email: str
    created_at: float
    salt: str
    pw_hash: str

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "email": self.email, "created_at": self.created_at}


def _hash(password: str, salt: str) -> str:
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **SCRYPT).hex()


class AccountStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.index_path = root / "accounts.json"
        root.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    # --- persistence -------------------------------------------------------
    def _load(self) -> dict:
        if not self.index_path.exists():
            return {"accounts": [], "active": None}
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        return {"accounts": data.get("accounts", []), "active": data.get("active")}

    def _save(self) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.index_path)

    def _accounts(self) -> list[Account]:
        return [Account(**a) for a in self._data["accounts"]]

    def account_dir(self, account_id: str) -> Path:
        return self.root / "accounts" / account_id

    # --- queries -------------------------------------------------------------
    def list_public(self) -> list[dict]:
        return [a.public() for a in self._accounts()]

    def get(self, account_id: str) -> Account:
        for a in self._accounts():
            if a.id == account_id:
                return a
        raise AuthError("Account nicht gefunden")

    def remembered(self) -> Account | None:
        active = self._data.get("active")
        try:
            return self.get(active) if active else None
        except AuthError:
            return None

    def _find(self, login: str) -> Account | None:
        login = login.strip().lower()
        return next((a for a in self._accounts() if login in (a.email.lower(), a.name.lower())), None)

    # --- mutations -----------------------------------------------------------
    def register(self, name: str, email: str, password: str) -> Account:
        name, email = name.strip(), email.strip().lower()
        if not name:
            raise AuthError("Bitte gib einen Namen ein")
        if not EMAIL_RE.match(email):
            raise AuthError("Bitte gib eine gültige E-Mail-Adresse ein")
        if len(password) < MIN_PASSWORD:
            raise AuthError(f"Das Passwort braucht mindestens {MIN_PASSWORD} Zeichen")
        if self._find(email) or self._find(name):
            raise AuthError("Es gibt schon einen Account mit diesem Namen oder dieser E-Mail")
        salt = secrets.token_hex(16)
        account = Account(uuid.uuid4().hex[:12], name, email, time.time(), salt, _hash(password, salt))
        is_first = not self._data["accounts"]
        self.account_dir(account.id).mkdir(parents=True, exist_ok=True)
        if is_first:
            self._adopt_legacy_data(account.id)
        self._data["accounts"].append(asdict(account))
        self._save()
        return account

    def login(self, login: str, password: str) -> Account:
        account = self._find(login)
        # compare against a dummy hash when unknown so timing does not reveal accounts
        expected = account.pw_hash if account else _hash("x", "00" * 16)
        given = _hash(password, account.salt if account else "00" * 16)
        if not account or not hmac.compare_digest(expected, given):
            raise AuthError("E-Mail/Name oder Passwort ist falsch")
        return account

    def set_active(self, account_id: str | None) -> None:
        self._data["active"] = account_id
        self._save()

    def update_profile(self, account_id: str, name: str, email: str) -> Account:
        name, email = name.strip(), email.strip().lower()
        if not name or not EMAIL_RE.match(email):
            raise AuthError("Name und gültige E-Mail sind Pflicht")
        for other in self._accounts():
            if other.id != account_id and (other.email == email or other.name.lower() == name.lower()):
                raise AuthError("Name oder E-Mail wird schon verwendet")
        return self._replace(account_id, name=name, email=email)

    def change_password(self, account_id: str, old: str, new: str) -> None:
        account = self.get(account_id)
        if not hmac.compare_digest(account.pw_hash, _hash(old, account.salt)):
            raise AuthError("Aktuelles Passwort ist falsch")
        if len(new) < MIN_PASSWORD:
            raise AuthError(f"Das neue Passwort braucht mindestens {MIN_PASSWORD} Zeichen")
        salt = secrets.token_hex(16)
        self._replace(account_id, salt=salt, pw_hash=_hash(new, salt))

    def delete(self, account_id: str, password: str) -> None:
        account = self.get(account_id)
        if not hmac.compare_digest(account.pw_hash, _hash(password, account.salt)):
            raise AuthError("Passwort ist falsch")
        self._data["accounts"] = [a for a in self._data["accounts"] if a["id"] != account_id]
        if self._data.get("active") == account_id:
            self._data["active"] = None
        self._save()
        shutil.rmtree(self.account_dir(account_id), ignore_errors=True)

    def _replace(self, account_id: str, **changes: str) -> Account:
        updated = None
        accounts = []
        for raw in self._data["accounts"]:
            if raw["id"] == account_id:
                raw = {**raw, **changes}
                updated = Account(**raw)
            accounts.append(raw)
        if updated is None:
            raise AuthError("Account nicht gefunden")
        self._data["accounts"] = accounts
        self._save()
        return updated

    def _adopt_legacy_data(self, account_id: str) -> None:
        """Data from before accounts existed belongs to the first account."""
        target = self.account_dir(account_id)
        for name in LEGACY_FILES:
            src = self.root / name
            if src.exists():
                shutil.move(str(src), str(target / name))
