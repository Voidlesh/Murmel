import pytest

from engine.accounts import AccountStore, AuthError


@pytest.fixture
def accounts(tmp_path):
    return AccountStore(tmp_path)


def test_register_and_login_by_email_or_name(accounts):
    acc = accounts.register("Void", "Void@Example.com", "geheim123")
    assert acc.email == "void@example.com"
    assert accounts.login("void@example.com", "geheim123").id == acc.id
    assert accounts.login("VOID", "geheim123").id == acc.id


def test_wrong_password_and_unknown_user_rejected(accounts):
    accounts.register("Void", "void@example.com", "geheim123")
    with pytest.raises(AuthError):
        accounts.login("void@example.com", "falsch!!")
    with pytest.raises(AuthError):
        accounts.login("nobody@example.com", "geheim123")


def test_password_is_not_stored_in_plaintext(accounts, tmp_path):
    accounts.register("Void", "void@example.com", "geheim123")
    assert "geheim123" not in (tmp_path / "accounts.json").read_text()


@pytest.mark.parametrize("name,email,pw", [("", "a@b.de", "123456"), ("A", "kaputt", "123456"), ("A", "a@b.de", "123")])
def test_register_validation(accounts, name, email, pw):
    with pytest.raises(AuthError):
        accounts.register(name, email, pw)


def test_duplicates_rejected(accounts):
    accounts.register("Void", "void@example.com", "geheim123")
    with pytest.raises(AuthError):
        accounts.register("Other", "VOID@example.com", "geheim123")
    with pytest.raises(AuthError):
        accounts.register("void", "x@example.com", "geheim123")


def test_remember_survives_reload(accounts, tmp_path):
    acc = accounts.register("Void", "void@example.com", "geheim123")
    accounts.set_active(acc.id)
    assert AccountStore(tmp_path).remembered().id == acc.id
    accounts.set_active(None)
    assert AccountStore(tmp_path).remembered() is None


def test_first_account_adopts_legacy_data(tmp_path):
    (tmp_path / "murmel.db").write_text("legacy")
    store = AccountStore(tmp_path)
    acc = store.register("Void", "void@example.com", "geheim123")
    assert (store.account_dir(acc.id) / "murmel.db").read_text() == "legacy"
    assert not (tmp_path / "murmel.db").exists()
    second = store.register("Zweit", "z@example.com", "geheim123")
    assert not (store.account_dir(second.id) / "murmel.db").exists()


def test_change_password_and_delete(accounts):
    acc = accounts.register("Void", "void@example.com", "geheim123")
    with pytest.raises(AuthError):
        accounts.change_password(acc.id, "falsch", "neues-pw")
    accounts.change_password(acc.id, "geheim123", "neues-pw")
    assert accounts.login("Void", "neues-pw").id == acc.id
    accounts.delete(acc.id, "neues-pw")
    assert accounts.list_public() == []
    assert not accounts.account_dir(acc.id).exists()


def test_update_profile(accounts):
    a = accounts.register("Void", "void@example.com", "geheim123")
    accounts.register("Tim", "tim@example.com", "geheim123")
    with pytest.raises(AuthError):
        accounts.update_profile(a.id, "Tim", "void@example.com")
    assert accounts.update_profile(a.id, "Void Lesh", "v@example.com").name == "Void Lesh"
