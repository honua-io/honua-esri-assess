"""Shared output-file helpers: overwrite refusal and atomic writes.

These back the ``--force`` contract: by default the CLI refuses to clobber an
existing artifact, and when it does write it does so atomically (write to a
temp file in the destination directory, then ``os.replace``) so a mid-write
failure can never leave a truncated file in place of a prior valid one.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


class OutputExistsError(Exception):
    """Raised when an output path already exists and ``--force`` was not set."""

    def __init__(self, path: Path) -> None:
        super().__init__(str(path))
        self.path = path


def ensure_overwrite_allowed(path: Path, *, force: bool) -> None:
    """Refuse to overwrite an existing regular file unless ``force`` is set.

    Directories are not handled here; the caller's write will raise the usual
    ``OSError`` for those, preserving existing typed-diagnostic behavior.
    """

    if force:
        return
    if path.exists() and not path.is_dir():
        raise OutputExistsError(path)


def atomic_write_text(path: Path, data: str, *, encoding: str = "utf-8") -> None:
    """Write ``data`` to ``path`` atomically.

    The content is streamed to a temporary file in the same directory and then
    moved into place with ``os.replace`` (atomic on POSIX and Windows for paths
    on the same filesystem). On any failure the temp file is cleaned up and the
    destination is left untouched.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
