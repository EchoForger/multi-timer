#!/bin/zsh

set -euo pipefail
setopt NULL_GLOB

readonly MULTITIMER_ROOT="${0:A:h:h}"
readonly MULTITIMER_CONFIGURATION="${1:-release}"
readonly MULTITIMER_BUILD_DIR="$MULTITIMER_ROOT/.build"
readonly MULTITIMER_OUTPUT_DIR="$MULTITIMER_ROOT/build"
readonly MULTITIMER_APP="$MULTITIMER_OUTPUT_DIR/MultiTimer.app"
readonly MULTITIMER_CLT_DIR="/Library/Developer/CommandLineTools"

if [[ "$MULTITIMER_CONFIGURATION" != "debug" && "$MULTITIMER_CONFIGURATION" != "release" ]]; then
    print -u2 "Usage: $0 [debug|release]"
    exit 2
fi

if [[ ! -x /usr/bin/swift ]]; then
    print -u2 "Swift Command Line Tools are required. Install them with: xcode-select --install"
    exit 1
fi

mkdir -p \
    "$MULTITIMER_BUILD_DIR/cache" \
    "$MULTITIMER_BUILD_DIR/config" \
    "$MULTITIMER_BUILD_DIR/security" \
    "$MULTITIMER_BUILD_DIR/module-cache" \
    "$MULTITIMER_OUTPUT_DIR"

MULTITIMER_SWIFT_ARGS=(
    --cache-path "$MULTITIMER_BUILD_DIR/cache"
    --config-path "$MULTITIMER_BUILD_DIR/config"
    --security-path "$MULTITIMER_BUILD_DIR/security"
    --scratch-path "$MULTITIMER_BUILD_DIR"
)
if [[ "${MULTITIMER_DISABLE_SWIFTPM_SANDBOX:-0}" == "1" ]]; then
    MULTITIMER_SWIFT_ARGS+=(--disable-sandbox)
fi
if [[ "${MULTITIMER_OFFLINE:-0}" == "1" ]]; then
    MULTITIMER_SWIFT_ARGS+=(--skip-update)
fi

MULTITIMER_SWIFT_ENV=(
    CLANG_MODULE_CACHE_PATH="$MULTITIMER_BUILD_DIR/module-cache"
)
if [[ -d "$MULTITIMER_CLT_DIR" ]]; then
    MULTITIMER_SWIFT_ENV+=(DEVELOPER_DIR="$MULTITIMER_CLT_DIR")
fi

print "Building MultiTimer $MULTITIMER_CONFIGURATION with the macOS SDK..."
/usr/bin/env $MULTITIMER_SWIFT_ENV /usr/bin/swift build \
    $MULTITIMER_SWIFT_ARGS --configuration "$MULTITIMER_CONFIGURATION" --product MultiTimer
/usr/bin/env $MULTITIMER_SWIFT_ENV /usr/bin/swift build \
    $MULTITIMER_SWIFT_ARGS --configuration "$MULTITIMER_CONFIGURATION" --product MultiTimerCLI

MULTITIMER_BIN_DIR="$(
    /usr/bin/env $MULTITIMER_SWIFT_ENV /usr/bin/swift build \
        $MULTITIMER_SWIFT_ARGS --configuration "$MULTITIMER_CONFIGURATION" --show-bin-path
)"

readonly MULTITIMER_STAGE="$(/usr/bin/mktemp -d "$MULTITIMER_OUTPUT_DIR/.MultiTimer.XXXXXX")"
trap '/bin/rm -rf "$MULTITIMER_STAGE"' EXIT
readonly MULTITIMER_STAGED_APP="$MULTITIMER_STAGE/MultiTimer.app"
readonly MULTITIMER_RESOURCES="$MULTITIMER_STAGED_APP/Contents/Resources"

mkdir -p "$MULTITIMER_STAGED_APP/Contents/MacOS" "$MULTITIMER_RESOURCES/bin"
/usr/bin/install -m 755 "$MULTITIMER_BIN_DIR/MultiTimer" "$MULTITIMER_STAGED_APP/Contents/MacOS/MultiTimer"
/usr/bin/install -m 755 "$MULTITIMER_BIN_DIR/MultiTimerCLI" "$MULTITIMER_RESOURCES/bin/multitimer"
/usr/bin/install -m 644 "$MULTITIMER_ROOT/Support/Info.plist" "$MULTITIMER_STAGED_APP/Contents/Info.plist"
/usr/bin/install -m 644 "$MULTITIMER_ROOT/assets/MultiTimer.icns" "$MULTITIMER_RESOURCES/MultiTimer.icns"

for bundle in "$MULTITIMER_BIN_DIR"/*.bundle; do
    /usr/bin/ditto "$bundle" "$MULTITIMER_RESOURCES/${bundle:t}"
done

for localization in en zh-Hans; do
    /usr/bin/ditto \
        "$MULTITIMER_ROOT/MultiTimer/Resources/$localization.lproj" \
        "$MULTITIMER_RESOURCES/$localization.lproj"
done

readonly MULTITIMER_LAUNCH_BUNDLE="$MULTITIMER_BIN_DIR/LaunchAtLogin_LaunchAtLogin.bundle"
readonly MULTITIMER_LOGIN_ITEMS="$MULTITIMER_STAGED_APP/Contents/Library/LoginItems"
if [[ -f "$MULTITIMER_LAUNCH_BUNDLE/LaunchAtLoginHelper.zip" ]]; then
    mkdir -p "$MULTITIMER_LOGIN_ITEMS"
    /usr/bin/ditto -x -k "$MULTITIMER_LAUNCH_BUNDLE/LaunchAtLoginHelper.zip" "$MULTITIMER_LOGIN_ITEMS"
    readonly MULTITIMER_HELPER="$MULTITIMER_LOGIN_ITEMS/LaunchAtLoginHelper.app"
    /usr/libexec/PlistBuddy \
        -c "Set :CFBundleIdentifier io.github.echoforger.multitimer-LaunchAtLoginHelper" \
        "$MULTITIMER_HELPER/Contents/Info.plist"
    /usr/bin/codesign --force --deep --sign - \
        --entitlements "$MULTITIMER_LAUNCH_BUNDLE/LaunchAtLogin.entitlements" \
        "$MULTITIMER_HELPER"
fi

/usr/bin/codesign --force --deep --sign - \
    --entitlements "$MULTITIMER_ROOT/Support/MultiTimer.entitlements" \
    "$MULTITIMER_STAGED_APP"

if [[ -e "$MULTITIMER_APP" ]]; then /bin/rm -rf "$MULTITIMER_APP"; fi
/bin/mv "$MULTITIMER_STAGED_APP" "$MULTITIMER_APP"
print "Built: $MULTITIMER_APP"
