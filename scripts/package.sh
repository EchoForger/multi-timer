#!/bin/zsh

set -euo pipefail
readonly MULTITIMER_ROOT="${0:A:h:h}"
readonly MULTITIMER_VERSION="0.7.0"
readonly MULTITIMER_STAGE="$(/usr/bin/mktemp -d /private/tmp/multitimer-dmg.XXXXXX)"
trap '/bin/rm -rf "$MULTITIMER_STAGE"' EXIT

"$MULTITIMER_ROOT/scripts/build.sh" release
/usr/bin/ditto "$MULTITIMER_ROOT/build/MultiTimer.app" "$MULTITIMER_STAGE/MultiTimer.app"
/bin/ln -s /Applications "$MULTITIMER_STAGE/Applications"
mkdir -p "$MULTITIMER_ROOT/dist"
/usr/bin/hdiutil create \
    -volname MultiTimer \
    -srcfolder "$MULTITIMER_STAGE" \
    -ov -format UDZO \
    "$MULTITIMER_ROOT/dist/MultiTimer-$MULTITIMER_VERSION.dmg"
cd "$MULTITIMER_ROOT/dist"
/usr/bin/shasum -a 256 "MultiTimer-$MULTITIMER_VERSION.dmg" > "MultiTimer-$MULTITIMER_VERSION.dmg.sha256"
print "Packaged: $MULTITIMER_ROOT/dist/MultiTimer-$MULTITIMER_VERSION.dmg"
