"""Log the running engine out or back into the E2E test account: python tests/auth_toggle.py out|in"""
import asyncio
import sys

import websockets

sys.path.insert(0, "tests")
from e2e_engine import TEST_ACCOUNT, call  # noqa: E402


async def main(action: str) -> None:
    async with websockets.connect("ws://127.0.0.1:47821") as ws:
        if action == "out":
            await call(ws, "auth_logout")
        else:
            await call(ws, "auth_login", login=TEST_ACCOUNT["email"], password=TEST_ACCOUNT["password"])
    print(action, "ok")


asyncio.run(main(sys.argv[1]))
