#!/usr/bin/env bash
# Prints the SHA-256 of an installed package's signing certificate.
#
#   ./tools/compute-signature.sh com.waze
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "usage: $0 <packageName>" >&2
    exit 1
fi

PKG="$1"
APK_PATH="$(adb shell pm path "$PKG" | head -1 | tr -d '\r' | sed 's/^package://')"
if [ -z "$APK_PATH" ]; then
    echo "Package $PKG is not installed on the device" >&2
    exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
adb pull "$APK_PATH" "$TMP/app.apk" >/dev/null

apksigner verify --print-certs "$TMP/app.apk" \
    | grep -i "SHA-256 digest" \
    | head -1 \
    | awk '{print $NF}' \
    | tr 'A-Z' 'a-z'
