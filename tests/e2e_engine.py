"""End-to-end check against a running engine: python tests/e2e_engine.py <wav>"""
import asyncio
import itertools
import json
import sys

import websockets

URL = "ws://127.0.0.1:47821"
_ids = itertools.count(1)


async def call(ws, method, **params):
    req_id = next(_ids)
    await ws.send(json.dumps({"id": req_id, "method": method, "params": params}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == req_id:
            if "error" in msg:
                raise RuntimeError(f"{method}: {msg['error']}")
            return msg["result"]


TEST_ACCOUNT = {"name": "E2E Test", "email": "e2e@murmel.test", "password": "e2e-test-pw"}


async def ensure_login(ws) -> None:
    """Log into the throwaway test account (created on first run, temp data dir only)."""
    try:
        await call(ws, "auth_login", login=TEST_ACCOUNT["email"], password=TEST_ACCOUNT["password"])
    except RuntimeError:
        await call(ws, "auth_register", **TEST_ACCOUNT)
    await call(ws, "set_settings", patch={"hotkey": "f13"})


async def main(wav: str) -> None:
    async with websockets.connect(URL) as ws:
        for _ in range(240):
            state = await call(ws, "status")
            if state["state"] != "loading":
                break
            await asyncio.sleep(0.5)
        print("state:", state["state"], state["detail"])
        assert state["state"] == "idle", state

        await ensure_login(ws)
        status = await call(ws, "auth_status")
        print("account:", status["account"]["name"], "| accounts:", len(status["accounts"]))

        await call(ws, "dictionary_save", word="Tim", replacement=None)
        await call(ws, "dictionary_save", word="neue Projekt", replacement="Projekt Murmel")
        await call(ws, "snippet_save", trigger="das Team", expansion="das Team (team@example.com)")

        item = await call(ws, "transcribe_wav", path=wav)
        print("raw :", item["raw_text"])
        print("text:", item["text"], f"({item['process_ms']} ms, {item['words']} Wörter)")
        assert "Projekt Murmel" in item["text"], item["text"]

        edited = item["text"].replace("Tim", "Timo")
        res = await call(ws, "edit_transcript", id=item["id"], text=edited)
        print("learned:", res["learned"])
        assert {"wrong": "Tim", "right": "Timo"} in res["learned"]

        stats = await call(ws, "stats", days=7)
        print("stats:", {k: stats[k] for k in ("words", "wpm", "sessions", "streak", "time_saved_min")})
        assert stats["sessions"] >= 1

        preview = await call(ws, "preview", text="äh ich bin gleich da.", category="personal")
        print("preview personal:", repr(preview))
        assert preview == "Ich bin gleich da"

        usage = await call(ws, "usage")
        print("usage:", {b["key"]: b["pct"] for b in usage["buckets"]})
        voice = await call(ws, "voice_profile")
        print("voice:", {k: voice.get(k) for k in ("unlocked", "words_total", "remaining", "most_used_word", "catch_phrase")})
        activity = await call(ws, "activity", days=28)
        assert len(activity) == 28
        stats2 = await call(ws, "stats", days=None)
        print("fixes:", stats2["fixes_words"], "words,", stats2["fixes_dict"], "dict")

        await call(ws, "auth_logout")
        try:
            await call(ws, "history")
            raise AssertionError("history must require login")
        except RuntimeError as exc:
            print("logged out ->", exc)
        await ensure_login(ws)

        print("mics:", [m["name"] for m in await call(ws, "microphones")][:3])
        print("llm:", await call(ws, "llm_check"))
        print("E2E OK")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
