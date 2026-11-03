"""Check this machine is ready before running anything else.

Run it first on any new machine:  python -m scripts.check_env
It exits with code 1 if something needs fixing, so CI or a script can rely on it.
"""

import os
import platform
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
MIN_PYTHON = (3, 11)
MIN_KEY_LENGTH = 32


def read_pins(requirements_file):
    """Return {package: version} for every 'package==version' line in the file."""
    pins = {}
    for line in requirements_file.read_text().splitlines():
        line = line.split("#")[0].strip()
        if "==" in line:
            package, pinned = line.split("==")
            pins[package.strip()] = pinned.strip()
    return pins


def installed_version(package):
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def check_python():
    ok = sys.version_info >= MIN_PYTHON
    status = "ok" if ok else "TOO OLD (need 3.11+)"
    print(f"{'python':<14}{platform.python_version():<10}{status}")
    return ok


def check_packages():
    all_ok = True
    for requirements_file in ("requirements.txt", "requirements-dev.txt"):
        for package, pinned in read_pins(REPO_ROOT / requirements_file).items():
            found = installed_version(package)
            ok = found == pinned
            all_ok = all_ok and ok
            status = "ok" if ok else f"MISMATCH (pinned {pinned})"
            print(f"{package:<14}{found or 'not installed':<10}{status}")
    return all_ok


def check_pii_key():
    # Only report whether the key exists and how long it is. Never print it.
    load_dotenv(REPO_ROOT / ".env")
    key = os.environ.get("NOVA_PII_KEY", "")
    if not key:
        print("NOVA_PII_KEY  MISSING: copy .env.example to .env and set a key")
        return False
    if len(key) < MIN_KEY_LENGTH:
        print(f"NOVA_PII_KEY  TOO SHORT: {len(key)} characters, need {MIN_KEY_LENGTH}+")
        return False
    print(f"NOVA_PII_KEY  set ({len(key)} characters)  ok")
    return True


def report_disk():
    # 2**30 bytes per GB matches what Windows Explorer and `df -h` show.
    free_gb = shutil.disk_usage(REPO_ROOT).free / 2**30
    print(f"{'disk free':<14}{free_gb:.0f} GB on the drive holding {REPO_ROOT}")


def main():
    # platform.version() gives the real build number; platform.release() says
    # "10" on Windows 11 under Python 3.11, which would be misleading.
    print(f"{'os':<14}{platform.system()} {platform.version()} ({platform.machine()})")
    results = [check_python(), check_packages(), check_pii_key()]
    report_disk()
    if all(results):
        print("READY")
        return 0
    print("NOT READY: fix the lines marked above")
    return 1


if __name__ == "__main__":
    sys.exit(main())
