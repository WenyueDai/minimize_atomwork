"""Executor factory: prefer ProcessPoolExecutor, fall back to ThreadPoolExecutor on PermissionError.

On some platforms (e.g. containers without fork/spawn rights, or macOS in certain
test environments) creating a ProcessPoolExecutor raises PermissionError before any
work is done. The context manager here tries the process pool first; if the OS
rejects it, it transparently degrades to threads for the same workload.

Start-method safety
-------------------
On Linux the default multiprocessing start method is 'fork'.  When a worker
imports PyTorch (e.g. via ANARCI/abnumber for antibody numbering) and PyTorch
was already initialised in the parent, CUDA raises::

    RuntimeError: Cannot re-initialize CUDA in forked subprocess.

Using 'forkserver' avoids this: the forkserver process is started once before
any GPU initialisation happens, and it forks clean copies of itself for each
worker.  On macOS/Windows the default ('spawn') is already safe.

Usage::

    with process_or_thread_pool(max_workers=4) as executor:
        futures = [executor.submit(fn, x) for x in items]
        ...

    with process_or_thread_pool(max_workers=1, initializer=init_fn, initargs=(arg,)) as executor:
        ...
"""

from __future__ import annotations

import concurrent.futures
import multiprocessing
import sys
from contextlib import contextmanager
from typing import Any


def _safe_mp_context() -> multiprocessing.context.BaseContext | None:
    """Return a CUDA-safe multiprocessing context, or None to use the platform default.

    'forkserver' is used on Linux because the default 'fork' causes
    'Cannot re-initialize CUDA in forked subprocess' when workers import PyTorch.
    On other platforms the default start method (spawn) is already safe.
    """
    if sys.platform.startswith("linux"):
        return multiprocessing.get_context("forkserver")
    return None


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
    mp_context = _safe_mp_context()
    if mp_context is not None:
        kwargs["mp_context"] = mp_context
    try:
        with concurrent.futures.ProcessPoolExecutor(**kwargs) as executor:
            yield executor
            return
    except PermissionError:
        pass
    # Drop mp_context — ThreadPoolExecutor does not accept it.
    thread_kwargs = {k: v for k, v in kwargs.items() if k != "mp_context"}
    with concurrent.futures.ThreadPoolExecutor(**thread_kwargs) as executor:
        yield executor
