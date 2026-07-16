"""Tool context cwd helpers — pass working directory through ContextVar."""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from pathlib import Path

_ctx_cwd: contextvars.ContextVar[str | None] = contextvars.ContextVar("cwd", default=None)


@contextmanager
def with_cwd(directory: str):
    """Context manager that sets the cwd ContextVar for the duration of the block."""
    if not directory:
        yield
        return
    token = _ctx_cwd.set(directory)
    try:
        yield
    finally:
        _ctx_cwd.reset(token)


def cwd_from_ctx() -> str | None:
    """Return the current ctx cwd, or None if not set."""
    return _ctx_cwd.get()


def resolve_path(p: str) -> str:
    """Resolve *p* to an absolute path, using ctx cwd (if set) or process cwd."""
    base = _ctx_cwd.get() or str(Path.cwd())
    if not p:
        return base
    pp = Path(p)
    if pp.is_absolute():
        return str(pp)
    return str(Path(base) / pp)