#!/bin/zsh

set -euo pipefail
readonly MULTITIMER_ROOT="${0:A:h:h}"
"$MULTITIMER_ROOT/scripts/build.sh" "${1:-debug}"
/usr/bin/open -n -g "$MULTITIMER_ROOT/build/MultiTimer.app"
