#!/usr/bin/env bash
# Builds the two files the app downloads, and signs them.
#
#   ./tools/release.sh [path/to/private-key.pem]
#
# The private key never lives in this repository and never reaches GitHub.
# Signing happens here, on the machine that holds it; CI only verifies. The
# default path is outside the working tree on purpose.
#
# Produces, at the repository root:
#   catalog.json      catalog.version
#   policies.json
#   signatures.json   base64 signatures for both, which is what the app reads
#   catalog.json.sig  policies.json.sig    the same signatures as raw bytes,
#                                          for openssl and for people
#
# Commit them together. The app fetches them straight from
# raw.githubusercontent.com, so the bytes committed here are the bytes verified
# on the device: a file changed without its signature is a file every device
# rejects, and they carry on with the copy they already have.
set -euo pipefail

cd "$(dirname "$0")/.."

KEY="${1:-${CATALOG_SIGNING_KEY:-../keys/shani-shvilin-signing.pem}}"

if [ ! -f "$KEY" ]; then
    cat >&2 <<EOF
No private key at: $KEY

Pass one as the first argument, or set CATALOG_SIGNING_KEY.
To create a fresh pair (this replaces the pinned key, so the app has to be
rebuilt with the new public value before any device will accept a release):

    openssl genpkey -algorithm ed25519 -out signing.pem
    openssl pkey -in signing.pem -pubout -outform DER | xxd -p -c 256
EOF
    exit 1
fi

python tools/build_catalog.py --out catalog.json --version-out catalog.version
python tools/build_policies.py --out policies.json

sign() {
    openssl pkeyutl -sign -rawin -inkey "$KEY" -in "$1" -out "$1.sig"
    printf '  signed %s -> %s.sig (%s bytes)\n' "$1" "$1" "$(wc -c <"$1.sig" | tr -d ' ')"
}

echo "Signing:"
sign catalog.json
sign policies.json

# And the same signatures again, base64 inside a JSON document.
#
# Not decoration. raw.githubusercontent.com serves a .sig as
# application/octet-stream, and the content filters this product is deployed
# behind answer that with a block page: measured on a live network, catalog.json
# came back 200 as text/plain while catalog.json.sig came back an HTML block
# page. A device would have fetched that page, failed verification, and stayed
# on its embedded copy forever without a word about why. .json is served as
# text, and passes.
python - <<'PY'
import base64, hashlib, json

files = ["catalog.json", "policies.json"]
document = {
    "schemaVersion": 1,
    "algorithm": "Ed25519",
    "signatures": {
        name: base64.b64encode(open(name + ".sig", "rb").read()).decode("ascii")
        for name in files
    },
    # Not used for verification, which is the signature's job. Here so that a
    # mismatch can be told apart from a corrupted download at a glance.
    "sha256": {
        name: hashlib.sha256(open(name, "rb").read()).hexdigest()
        for name in files
    },
}
with open("signatures.json", "w", encoding="utf-8", newline="\n") as fh:
    json.dump(document, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
print("  wrote signatures.json")
PY

# Sign then verify, always. A signature nobody checked is a signature that can
# be produced by the wrong key, and the first thing that notices is a fleet of
# devices that quietly stop updating.
echo
./tools/verify.sh

cat <<EOF

Ready to commit:
  catalog.json  catalog.version  policies.json
  signatures.json
  catalog.json.sig  policies.json.sig
EOF
