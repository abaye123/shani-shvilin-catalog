#!/usr/bin/env bash
# Checks the published files against the public keys committed here.
#
#   ./tools/verify.sh
#
# This is exactly what the device does: fetch the file, fetch the detached
# signature, verify with a pinned key, and refuse the file otherwise. Runs in
# CI on every push, so a bad or missing signature is caught here rather than by
# a fleet that stops receiving updates without saying why.
set -euo pipefail

cd "$(dirname "$0")/.."

KEYS=(keys/signing-current.pub.pem keys/signing-standby.pub.pem)
FILES=(catalog.json policies.json)
failed=0

for file in "${FILES[@]}"; do
    if [ ! -f "$file" ] || [ ! -f "$file.sig" ]; then
        echo "  MISSING $file or $file.sig" >&2
        failed=1
        continue
    fi

    accepted=""
    for key in "${KEYS[@]}"; do
        [ -f "$key" ] || continue
        if openssl pkeyutl -verify -rawin -pubin -inkey "$key" \
                -in "$file" -sigfile "$file.sig" >/dev/null 2>&1; then
            accepted="$key"
            break
        fi
    done

    if [ -n "$accepted" ]; then
        echo "  OK      $file verified with $(basename "$accepted")"
    else
        echo "  BAD     $file is not signed by any pinned key" >&2
        failed=1
    fi
done

if [ "$failed" -ne 0 ]; then
    echo "Verification failed." >&2
    exit 1
fi

echo "All published files verify."
