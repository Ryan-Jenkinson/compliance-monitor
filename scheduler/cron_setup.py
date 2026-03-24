#!/usr/bin/env python3
"""Install or remove crontab entries for the compliance newsletter.

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

_SENTINEL = "# compliance-monitor"
_SENTINEL_REMINDER = "# compliance-monitor-reminder"

# 6 AM Mon–Fri: main pipeline (no subscriber emails — owner notification only)
_MAIN_CRON = (
    f"0 6 * * 1-5 cd {_PROJECT_ROOT} && {_PYTHON} {_RUN_PY} --no-email "
    f">> {_LOG_PATH} 2>&1 {_SENTINEL}"
)

# 9 AM Friday: reminder email to verify end-of-week run
_REMINDER_CRON = (
    f"0 9 * * 5 cd {_PROJECT_ROOT} && {_PYTHON} {_RUN_PY} --send-reminder "
    f">> {_LOG_PATH} 2>&1 {_SENTINEL_REMINDER}"
)


def _current_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def _write_crontab(contents: str) -> None:
    proc = subprocess.run(["crontab", "-"], input=contents, text=True, capture_output=True)
    if proc.returncode != 0:
        print(f"ERROR: crontab write failed: {proc.stderr}", file=sys.stderr)
        sys.exit(1)


def install() -> None:
    current = _current_crontab()
    lines_to_add = []

    if _SENTINEL not in current:
        lines_to_add.append(_MAIN_CRON)
        print(f"Adding main cron (6 AM Mon–Fri):\n  {_MAIN_CRON}")
    else:
        print("Main cron entry already installed.")

    if _SENTINEL_REMINDER not in current:
        lines_to_add.append(_REMINDER_CRON)
        print(f"Adding reminder cron (9 AM Fridays):\n  {_REMINDER_CRON}")
    else:
        print("Friday reminder cron already installed.")

    if lines_to_add:
        new_crontab = current.rstrip("\n") + "\n" + "\n".join(lines_to_add) + "\n"
        _write_crontab(new_crontab)
        print("\nIMPORTANT: Set System Settings > Battery > Schedule to wake at 5:55 AM.")


def remove() -> None:
    current = _current_crontab()
    lines = [
        l for l in current.splitlines()
        if _SENTINEL not in l and _SENTINEL_REMINDER not in l
    ]
    _write_crontab("\n".join(lines) + "\n")
    print("Removed all compliance monitor cron entries.")


def status() -> None:
    current = _current_crontab()
    found = False
    for line in current.splitlines():
        if _SENTINEL in line or _SENTINEL_REMINDER in line:
            tag = "MAIN" if _SENTINEL_REMINDER not in line else "REMINDER"
            print(f"[{tag}] {line}")
            found = True
    if not found:
        print("No compliance monitor cron entries installed.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Manage compliance monitor cron schedule")
    parser.add_argument("action", choices=["install", "remove", "status"])
    args = parser.parse_args()
    {"install": install, "remove": remove, "status": status}[args.action]()
