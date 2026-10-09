"""Windows source launcher; uses only the Python standard library."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def requirements_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_chrome():
    for variable in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        folder = os.environ.get(variable)
        if folder:
            candidate = Path(folder) / 'Google/Chrome/Application/chrome.exe'
            if candidate.is_file():
                return candidate
    return None


def execute(args, stage):
    print('[Launcher] ' + stage, flush=True)
    result = subprocess.run([str(arg) for arg in args], cwd=ROOT, check=False)
    if result.returncode:
        raise RuntimeError(stage + ' failed (exit ' + str(result.returncode) + ').')


def prepare_environment():
    requirements = ROOT / 'requirements.txt'
    if not requirements.is_file() or not (ROOT / 'app.py').is_file():
        raise RuntimeError('Extract the entire ZIP before running start.bat.')
    python = ROOT / '.venv/Scripts/python.exe'
    if not python.is_file():
        execute([sys.executable, '-m', 'venv', ROOT / '.venv'], 'Creating local Python environment')
    probe = subprocess.run(
        [str(python), '-c', 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)'],
        cwd=ROOT, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode:
        raise RuntimeError('The .venv is unusable. Rename .venv and restart with Python 3.12.')
    marker = ROOT / '.venv/requirements.sha256'
    digest = requirements_digest(requirements)
    installed = subprocess.run(
        [str(python), '-c', 'import tkinter, playwright.sync_api, openpyxl'],
        cwd=ROOT, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not marker.is_file() or marker.read_text().strip() != digest or installed.returncode:
        execute([python, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', requirements],
                'Installing dependencies (Internet required on first launch)')
        execute([python, '-c', 'import tkinter, playwright.sync_api, openpyxl'], 'Checking installed dependencies')
        marker.write_text(digest + '\n')
    if not find_chrome():
        raise RuntimeError('Google Chrome is missing. Install Chrome in its standard location and restart.')
    return python


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Prepare environment without opening the GUI.')
    args = parser.parse_args()
    try:
        if os.name != 'nt':
            raise RuntimeError('start.bat supports Windows only.')
        if not (3, 10) <= sys.version_info[:2] < (3, 14):
            raise RuntimeError('Install Python 3.12 with Tcl/Tk and the Python launcher enabled.')
        python = prepare_environment()
        if args.check:
            print('[Launcher] Environment ready.', flush=True)
        else:
            execute([python, ROOT / 'app.py'], 'Opening TPS Windows Client')
        return 0
    except (RuntimeError, OSError, UnicodeError) as exc:
        # Messages here describe local setup only; never echo environment variables.
        if isinstance(exc, RuntimeError):
            print('[Launcher ERROR] ' + str(exc), file=sys.stderr, flush=True)
        else:
            print('[Launcher ERROR] Local setup failed: ' + type(exc).__name__, file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
