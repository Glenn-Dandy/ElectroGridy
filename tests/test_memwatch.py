import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from electrogridy import memwatch

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")


@linux_only
def test_reads_own_memory():
    used = memwatch.rss_bytes()
    assert used is not None and used > 10 * 1024**2
    assert memwatch.default_limit() >= 4 * memwatch.GB


def test_report_writes_stacks():
    with tempfile.TemporaryFile("w+") as f:
        memwatch.report(f, 3 * memwatch.GB, "ungewöhnlich hoch")
        f.seek(0)
        text = f.read()
    assert "Speicher 3.0 GB" in text and "test_report_writes_stacks" in text


@linux_only
def test_limit_ends_the_program_with_a_report(tmp_path: Path):
    log = tmp_path / "crash.log"
    code = (
        "import time\n"
        "from electrogridy import memwatch\n"
        f"log = open({str(log)!r}, 'w')\n"
        "memwatch.start(log, first_gb=0.0, limit=1)\n"
        "def busy():\n"
        "    time.sleep(10)\n"
        "busy()\n"
    )
    result = subprocess.run([sys.executable, "-c", code], timeout=30)
    assert result.returncode == 70
    text = log.read_text()
    assert "Grenze erreicht" in text and "busy" in text


@linux_only
def test_a_hang_is_reported(tmp_path: Path):
    log = tmp_path / "crash.log"
    code = (
        "import time\n"
        "from electrogridy import memwatch\n"
        f"log = open({str(log)!r}, 'w')\n"
        "memwatch.start(log, hang_seconds=1.5)\n"
        "memwatch.heartbeat()\n"
        "def stuck():\n"
        "    time.sleep(4)\n"
        "stuck()\n"
    )
    subprocess.run([sys.executable, "-c", code], timeout=30, check=True)
    text = log.read_text()
    assert "Keine Reaktion seit" in text and "stuck" in text
    assert text.count("Keine Reaktion") == 1
