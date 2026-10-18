#!/bin/bash
# Wakes this Mac at 1:55 am every night (when plugged in) so the AgencyOS night shift can run.
# Asks for your Mac password once. Undo with "Stop Mac Waking.command".
set -euo pipefail
echo "This makes your Mac wake at 1:55 am every night. It will ask for your Mac password."
sudo pmset repeat wakeorpoweron MTWRFSU 01:55:00
pmset -g sched
echo "Done. Keep the Mac plugged in and AgencyOS open, and the night shift runs after 2 am."
