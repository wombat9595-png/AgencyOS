#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
exec bash "Launch AgencyOS.command" --recover-login
