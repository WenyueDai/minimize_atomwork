"""Executor factory: prefer ProcessPoolExecutor, fall back to ThreadPoolExecutor on PermissionError.

On some platforms (e.g. containers without fork/spawn rights, or macOS in certain
test environments) creating a ProcessPoolExecutor raises PermissionError before any
work is done. The context manager here tries the process pool first; if the OS
rejects it, it transparently degrades to threads for the same workload.

Usage::

    with process_or_thread_pool(max_workers=4) as executor:
        futures = [executor.submit(fn, x) for x in items]
        ...

    with process_or_thread_pool(max_workers=1, initializer=init_fn, initargs=(arg,)) as executor:
        ...
"""

from __future__ import annotations

import concurrent.futures
from contextlib import contextmanager
from typing import Any


@contextmanager
def process_or_thread_pool(
    *,
    max_workers: int,
    initializer=None,
    initargs: tuple[Any, ...] = (),
):
    """Yield a ProcessPoolExecutor, falling back to ThreadPoolExecutor on PermissionError."""
    kwargs: dict[str, Any] = {"max_workers": max_workers}
    if initializer is not None:
        kwargs["initializer"] = initializer
        kwargs["initargs"] = initargs
    try:
        with concurrent.futures.ProcessPoolExecutor(**kwargs) as executor:
            yield executor
            return
    except PermissionError:
        pass
    with concurrent.futures.ThreadPoolExecutor(**kwargs) as executor:
        yield executor
