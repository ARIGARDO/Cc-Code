"""Allow running via ``python -m mewcode``."""
import asyncio

from mewcode.app import main


def _entry() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    _entry()