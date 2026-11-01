"""Screenshot the island in every state (requires running engine + app, test hotkey F13).

Usage: python tests/shoot_island.py <out-dir>
"""
import asyncio
import ctypes
import sys
import time

import keyboard
from PIL import ImageGrab

user32 = ctypes.windll.user32


def grab(name: str, out: str) -> None:
    w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    # 140x40 strip around the pill, upscaled for inspection
    img = ImageGrab.grab(bbox=(w // 2 - 120, h - 120, w // 2 + 120, h - 30))
    img.resize((img.width * 3, img.height * 3)).save(f"{out}/island-{name}.png")


async def main(out: str) -> None:
    w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    grab("resting", out)

    point = ctypes.wintypes.POINT() if hasattr(ctypes, "wintypes") else None
    import ctypes.wintypes as wt

    point = wt.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    work = wt.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)  # SPI_GETWORKAREA
    user32.SetCursorPos(w // 2, work.bottom - 2 - 14 - 4)
    time.sleep(0.6)
    grab("ready", out)
    user32.SetCursorPos(point.x, point.y)
    time.sleep(0.4)

    keyboard.press("f13")
    time.sleep(0.8)
    grab("ptt", out)
    keyboard.release("f13")
    time.sleep(0.15)
    grab("processing-or-idle", out)
    time.sleep(2)

    keyboard.send("f13")
    time.sleep(0.8)
    grab("handsfree", out)
    keyboard.send("esc")
    time.sleep(0.5)
    grab("after-cancel", out)
    print("done")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
