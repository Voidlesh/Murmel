"""Entry point: python -m engine"""
import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from . import config


def main() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    handlers: list[logging.Handler] = [
        RotatingFileHandler(config.DATA_DIR / "engine.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    ]
    if sys.stderr:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)

    from .server import Engine

    try:
        asyncio.run(Engine().run())
    except OSError as exc:
        logging.error("Engine-Start fehlgeschlagen (läuft sie schon?): %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
