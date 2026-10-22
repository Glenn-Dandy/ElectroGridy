"""Waiting for timers in tests without depending on the speed of the machine."""

from PyQt6.QtTest import QTest


def wait_until(condition, timeout_ms: int = 5000) -> bool:
    """Let events run until ``condition()`` holds or the time is up."""
    for _ in range(timeout_ms // 20):
        if condition():
            return True
        QTest.qWait(20)
    return condition()
