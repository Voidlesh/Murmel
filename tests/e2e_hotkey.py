"""Drive the real global hotkey (F13 test key) and watch engine states over WebSocket.

Usage: python tests/e2e_hotkey.py <screenshot-dir>
Requires a running engine configured with hotkey "f13".
"""
import asyncio
import json
import sys
import time

import keyboard
import websockets

sys.path.insert(0, ".")
from engine import output  # noqa: E402

URL = "ws://127.0.0.1:47821"


def grab_overlay(path: str) -> None:
    """Screenshot the bottom-center strip where the overlay pill lives."""
    import ctypes

    from PIL import ImageGrab  # optional dependency, only for this diagnostic

    w, h = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
    ImageGrab.grab(bbox=(w // 2 - 210, h - 200, w // 2 + 210, h)).save(path)


async def collect(ws, seconds: float) -> list[str]:
    states: list[str] = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=end - time.monotonic()))
        except asyncio.TimeoutError:
            break
        if msg.get("type") == "state":
            states.append(f"{msg['state']}{'+hf' if msg['hands_free'] else ''}:{msg['detail']}")
    return states


async def main(shot_dir: str) -> None:
    async with websockets.connect(URL) as ws:
        await collect(ws, 0.5)

        # 1) hold-to-talk: press, hold 1.2 s, release
        keyboard.press("f13")
        await asyncio.sleep(0.6)
        try:
            grab_overlay(f"{shot_dir}/overlay-recording.png")
        except ImportError:
            pass
        await asyncio.sleep(0.6)
        keyboard.release("f13")
        hold = await collect(ws, 6)
        print("hold :", hold)
        assert hold and hold[0].startswith("recording"), hold
        assert hold[-1].startswith("idle"), hold

        # 2) tap -> hands-free, tap again -> stop
        keyboard.send("f13")
        await asyncio.sleep(0.8)
        keyboard.send("f13")
        tap = await collect(ws, 6)
        print("tap  :", tap)
        assert any("+hf" in s for s in tap), tap
        assert tap[-1].startswith("idle"), tap

        # 3) Esc cancels
        keyboard.send("f13")
        await asyncio.sleep(0.5)
        keyboard.send("esc")
        esc = await collect(ws, 2)
        print("esc  :", esc)
        assert esc[-1] == "idle:Abgebrochen", esc

    # 4) clipboard roundtrip (restores whatever the user had)
    before = output.get_clipboard_text()
    output.set_clipboard_text("Murmel Ümläut-Test ✓")
    assert output.get_clipboard_text() == "Murmel Ümläut-Test ✓"
    if before is not None:
        output.set_clipboard_text(before)
    print("clipboard roundtrip OK")
    print("app category:", output.categorize("discord.exe", "", {"personal": ["discord.exe"]}),
          output.categorize("chrome.exe", "Posteingang - Gmail", {"email": ["Gmail"]}))
    print("HOTKEY E2E OK")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
