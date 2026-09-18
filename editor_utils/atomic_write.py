"""Small same-directory atomic file replacement helper."""

from __future__ import annotations

import os
import tempfile


def atomic_write_bytes(path: str, data: bytes) -> None:
    """Write bytes to a temporary file and atomically replace the target."""
    target = os.path.abspath(path)
    directory = os.path.dirname(target) or os.getcwd()
    fd, temp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(target)}.",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
