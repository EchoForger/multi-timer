#!/bin/zsh

set -euo pipefail
readonly MULTITIMER_ROOT="${0:A:h:h}"
readonly MULTITIMER_VERSION="0.9.0"
readonly MULTITIMER_STAGE="$(/usr/bin/mktemp -d /private/tmp/multitimer-dmg.XXXXXX)"
trap '/bin/rm -rf "$MULTITIMER_STAGE"' EXIT

"$MULTITIMER_ROOT/scripts/build.sh" release
if [[ -n "${MULTITIMER_NOTARY_PROFILE:-}" ]]; then
    readonly MULTITIMER_NOTARY_ZIP="$MULTITIMER_STAGE/MultiTimer-notary.zip"
    /usr/bin/ditto -c -k --keepParent "$MULTITIMER_ROOT/build/MultiTimer.app" "$MULTITIMER_NOTARY_ZIP"
    /usr/bin/xcrun notarytool submit "$MULTITIMER_NOTARY_ZIP" \
        --keychain-profile "$MULTITIMER_NOTARY_PROFILE" --wait
    /usr/bin/xcrun stapler staple "$MULTITIMER_ROOT/build/MultiTimer.app"
    /bin/rm -f "$MULTITIMER_NOTARY_ZIP"
fi
/usr/bin/ditto "$MULTITIMER_ROOT/build/MultiTimer.app" "$MULTITIMER_STAGE/MultiTimer.app"
/bin/ln -s /Applications "$MULTITIMER_STAGE/Applications"
mkdir -p "$MULTITIMER_ROOT/dist"
/usr/bin/hdiutil create \
    -volname MultiTimer \
    -srcfolder "$MULTITIMER_STAGE" \
    -ov -format UDZO \
    "$MULTITIMER_ROOT/dist/MultiTimer-$MULTITIMER_VERSION.dmg"
if [[ -n "${MULTITIMER_CODE_SIGN_IDENTITY:-}" && "$MULTITIMER_CODE_SIGN_IDENTITY" != "-" ]]; then
    /usr/bin/codesign --force --sign "$MULTITIMER_CODE_SIGN_IDENTITY" \
        "$MULTITIMER_ROOT/dist/MultiTimer-$MULTITIMER_VERSION.dmg"
fi
cd "$MULTITIMER_ROOT/dist"
/usr/bin/shasum -a 256 "MultiTimer-$MULTITIMER_VERSION.dmg" > "MultiTimer-$MULTITIMER_VERSION.dmg.sha256"
print "Packaged: $MULTITIMER_ROOT/dist/MultiTimer-$MULTITIMER_VERSION.dmg"
