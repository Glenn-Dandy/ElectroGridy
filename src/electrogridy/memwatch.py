"""Memory watch: finds out where the program is when it suddenly takes huge amounts of
memory. Pure Python, Linux only (reads /proc), does nothing elsewhere.

A background thread checks the resident memory every second. From ``first_gb`` on it
writes the Python stacks of all threads to the crash log (again after every further
``step_gb``). At ``limit`` it writes a last report and ends the program, before the
system starts swapping and the kernel kills it anyway (the desktop stays usable; the
automatic backup is offered on the next start).

It also watches for hangs: the user interface calls ``heartbeat()`` every second; when
that stops for ``HANG_SECONDS`` the stacks go to the crash log once (shows where the
program is stuck when the desktop reports it as not responding).
"""

import faulthandler
import os
import threading
import time
from typing import TextIO

GB = 1024**3
HANG_SECONDS = 10.0

_last_beat: float | None = None


def heartbeat() -> None:
    """Called regularly from the event loop of the user interface."""
    global _last_beat
    _last_beat = time.monotonic()


def rss_bytes() -> int | None:
    try:
        with open("/proc/self/statm", encoding="ascii") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None


def total_memory() -> int | None:
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def default_limit() -> int:
    """Half the RAM, at least 4 GB."""
    total = total_memory() or 8 * GB
    return max(4 * GB, total // 2)


def report(log: TextIO, used: int, note: str) -> None:
    log.write(f"--- Speicher {used / GB:.1f} GB: {note}\n")
    log.flush()
    faulthandler.dump_traceback(log, all_threads=True)
    log.flush()


def start(
    log: TextIO,
    first_gb: float = 2.0,
    step_gb: float = 2.0,
    limit: int | None = None,
    hang_seconds: float = HANG_SECONDS,
):
    """Start the watch thread; returns it (None where /proc is missing)."""
    if rss_bytes() is None:
        return None
    hard = limit if limit is not None else default_limit()

    def run() -> None:
        next_report = first_gb * GB
        hang_reported = False
        while True:
            time.sleep(1.0)
            beat = _last_beat
            if beat is not None:
                quiet = time.monotonic() - beat
                if quiet >= hang_seconds and not hang_reported:
                    log.write(f"--- Keine Reaktion seit {quiet:.0f} s\n")
                    log.flush()
                    faulthandler.dump_traceback(log, all_threads=True)
                    log.flush()
                    hang_reported = True
                elif quiet < hang_seconds:
                    hang_reported = False
            used = rss_bytes()
            if used is None:
                continue
            if used >= hard:
                report(log, used, "Grenze erreicht, Programm wird beendet")
                os._exit(70)
            if used >= next_report:
                report(log, used, "ungewöhnlich hoch")
                next_report = used + step_gb * GB

    thread = threading.Thread(target=run, name="memwatch", daemon=True)
    thread.start()
    return thread
