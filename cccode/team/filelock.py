"""File-level lock using O_CREAT|O_EXCL, with stale-lock recovery."""

from __future__ import annotations

import asyncio
import contextlib
import os
import random
import time
from pathlib import Path

_LOCK_MAX_RETRIES = 10
_LOCK_STALE_AFTER = 10.0  # seconds
_LOCK_BACKOFF_MIN = 0.005
_LOCK_BACKOFF_MAX = 0.1


@contextlib.asynccontextmanager
async def acquire_lock(lock_path: str):
    """Acquire an exclusive file lock.

    Uses ``os.open(O_CREAT|O_EXCL|O_WRONLY)`` for atomicity across processes.
    If a stale lock file exists (older than ``LOCK_STALE_AFTER`` seconds),
    deletes it and retries once.  Otherwise sleeps a random backoff between
    ``LOCK_BACKOFF_MIN`` and ``LOCK_BACKOFF_MAX`` seconds and tries again.

    On exit (normal or exceptional), the lock file is removed.
    """

    acquired = False
    try:
        for attempt in range(_LOCK_MAX_RETRIES):
            try:
                fd = os.open(
                    lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
                os.close(fd)
                acquired = True
                yield
                return
            except FileExistsError:
                # Another actor holds this lock.  Check stale.
                try:
                    st = Path(lock_path).stat()
                    if time.time() - st.st_mtime > _LOCK_STALE_AFTER:
                        # stale — remove and retry immediately
                        try:
                            os.unlink(lock_path)
                        except OSError:
                            pass
                        continue
                except FileNotFoundError:
                    # disappeared — try again immediately
                    continue

                # alive lock — back off and retry
                await asyncio.sleep(
                    random.uniform(_LOCK_BACKOFF_MIN, _LOCK_BACKOFF_MAX)
                )
        # exhausted retries
        raise OSError(
            f"Failed to acquire lock '{lock_path}' after "
            f"{_LOCK_MAX_RETRIES} attempts"
        )
    finally:
        if acquired:
            try:
                os.unlink(lock_path)
            except OSError:
                pass