"""Allow running via ``python -m mewcode``."""
import asyncio
from mewcode.app import main

asyncio.run(main())
