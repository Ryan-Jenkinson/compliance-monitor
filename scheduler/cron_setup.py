#!/usr/bin/env python3
"""Install or remove the 6 AM crontab entry for the compliance newsletter.

Usage:
    python scheduler/cron_setup.py install
    python scheduler/cron_setup.py remove
    python scheduler/cron_setup.py status
"""
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
_RUN_PY = _PROJECT_ROOT / "run.py"
_LOG_PATH = _PROJECT_ROOT / "logs" / "cron.log"
_PYTHON = sys.executable

# Cron comment used as a sentinel to find/remove our entry
_CRON_COMMENT = "# andersen-compliance-monitor"
_CRON_LINE = f"0 6 * * * cd {_PROJECT_ROOT} && {_PYTHON} {_RUN_PY} >> {_LOG_PATH} 2>&1 {_CRON_COMMENT}"


def _current_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout
    return ""  # No crontab yet


def _write_crontab(contents: str) -> None:
    proc = subprocess.run(["crontab", "-"], input=contents, text=True, capture_output=True)
    if proc.returncode != 0:
        print(f"ERROR: crontab write failed: {proc.stderr}", file=sys.stderr)
        sys.exit(1)


def install() -> None:
    current = _current_crontab()
    if _CRON_COMMENT in current:
        print("Cron entry already installed.")
        return
    new_crontab = current.rstrip("\n") + "\n" + _CRON_LINE + "\n"
    _write_crontab(new_crontab)
    print(f"Installed cron entry:\n  {_CRON_LINE}")
    print("\nIMPORTANT: Also set System Settings > Battery > Schedule to wake at 5:55 AM.")


def remove() -> None:
    current = _current_crontab()
    if _CRON_COMMENT not in current:
        print("No compliance monitor cron entry found.")
        return
    lines = [l for l in current.splitlines() if _CRON_COMMENT not in l]
    _write_crontab("\n".join(lines) + "\n")
    print("Removed compliance monitor cron entry.")


def status() -> None:
    current = _current_crontab()
    if _CRON_COMMENT in current:
        for line in current.splitlines():
            if _CRON_COMMENT in line:
                print(f"INSTALLED: {line}")
    else:
        print("NOT installed.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Manage compliance monitor cron schedule")
    parser.add_argument("action", choices=["install", "remove", "status"])
    args = parser.parse_args()

    {"install": install, "remove": remove, "status": status}[args.action]()
