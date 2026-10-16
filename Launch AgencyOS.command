#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if command -v python3.13 >/dev/null 2>&1; then
  agencyos_python="$(command -v python3.13)"
else
  agencyos_python="$(command -v python3 || true)"
fi
if [ -z "$agencyos_python" ] || ! "$agencyos_python" -c 'import sys; assert sys.version_info >= (3,13)' 2>/dev/null; then
  echo 'Install the free Python 3.13 macOS installer from python.org, then reopen this launcher.'
  read -r -p 'Press Enter to close.'
  exit 1
fi
if [ ! -x .venv-first-sale/bin/python ]; then
  "$agencyos_python" -m venv .venv-first-sale
fi
agencyos_requirements="$(cksum < requirements-local.lock)"
if [ ! -f .venv-first-sale/.requirements-ready ] || [ "$(cat .venv-first-sale/.requirements-ready)" != "$agencyos_requirements" ]; then
  .venv-first-sale/bin/python -m pip install -r requirements-local.lock
  printf '%s\n' "$agencyos_requirements" > .venv-first-sale/.requirements-ready
fi
exec .venv-first-sale/bin/python local_run.py
