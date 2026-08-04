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

# The device reads the base64 copies in signatures.json, not the .sig files, so
# a drift between the two would pass every check above and still leave the
# fleet unable to update. Verify the bytes the device actually gets.
python - <<'PY' || failed=1
import base64, hashlib, json, subprocess, sys, tempfile, os

try:
    document = json.load(open("signatures.json", encoding="utf-8"))
except Exception as exc:
    print(f"  MISSING signatures.json ({exc})", file=sys.stderr)
    sys.exit(1)

keys = [k for k in ("keys/signing-current.pub.pem", "keys/signing-standby.pub.pem")
        if os.path.exists(k)]
bad = False

for name in ("catalog.json", "policies.json"):
    encoded = document.get("signatures", {}).get(name)
    if not encoded:
        print(f"  MISSING signatures.json has no signature for {name}", file=sys.stderr)
        bad = True
        continue

    signature = base64.b64decode(encoded)
    with tempfile.NamedTemporaryFile(delete=False) as fh:
        fh.write(signature)
        sig_path = fh.name

    try:
        accepted = next(
            (key for key in keys if subprocess.run(
                ["openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", key,
                 "-in", name, "-sigfile", sig_path],
                capture_output=True).returncode == 0),
            None,
        )
    finally:
        os.unlink(sig_path)

    if accepted:
        print(f"  OK      {name} verifies against signatures.json")
    else:
        print(f"  BAD     signatures.json carries a bad signature for {name}",
              file=sys.stderr)
        bad = True

    declared = document.get("sha256", {}).get(name)
    actual = hashlib.sha256(open(name, "rb").read()).hexdigest()
    if declared != actual:
        print(f"  BAD     signatures.json records sha256 {declared} for {name}, "
              f"the file is {actual}", file=sys.stderr)
        bad = True

sys.exit(1 if bad else 0)
PY

if [ "$failed" -ne 0 ]; then
    echo "Verification failed." >&2
    exit 1
fi

echo "All published files verify."
