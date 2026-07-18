"""Small cross-platform advisory file-lock adapter."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import IO, Iterator


@contextmanager
def file_lock(handle: IO[str], *, blocking: bool = True) -> Iterator[bool]:
    """Lock one byte of a file on Windows and the whole file on POSIX."""

    acquired = False
    if os.name == "nt":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write("\0")
            handle.flush()
        handle.seek(0)
        # msvcrt.LK_LOCK retries only once per second, which is far coarser
        # than the ~50ms polling used by callers contending for this lock.
        # Poll LK_NBLCK ourselves at a much finer interval instead.
        deadline = time.monotonic() + 10 if blocking else None
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
                break
            except OSError:
                if not blocking or time.monotonic() >= deadline:
                    if blocking:
                        raise
                    break
                time.sleep(0.01)
    else:
        import fcntl

        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(handle, flags)
            acquired = True
        except BlockingIOError:
            if blocking:
                raise
    try:
        yield acquired
    finally:
        if acquired and os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        elif acquired:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_UN)
