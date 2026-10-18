#!/bin/bash
# Removes the nightly wake-up. Note: this clears every repeating wake or sleep schedule on the Mac.
set -euo pipefail
sudo pmset repeat cancel
pmset -g sched
echo "Done. The Mac no longer wakes itself at night."
