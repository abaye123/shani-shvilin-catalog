#!/usr/bin/env python3
"""Merges apps/**/*.json into a single catalog.json and validates it.

Usage:
    python tools/build_catalog.py --out catalog.json
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

CATEGORIES = {
    "NAVIGATION", "MAIL", "COMMUNICATION", "MUSIC_AUDIO", "VIDEO", "TORAH",
    "PRODUCTIVITY", "TOOLS", "FINANCE", "HEALTH_FITNESS", "NEWS", "GOVERNMENT",
    "HOME", "SYSTEM",
}
MODES = {
    "OFFLINE", "LOCAL_ONLY", "NAVIGATION_ONLY", "NAVIGATION_AND_MAIL_ONLY",
    "REDUCED_RISK", "MOST_OPEN",
}
DIR_TO_CATEGORY = {
    "navigation": "NAVIGATION", "mail": "MAIL", "communication": "COMMUNICATION",
    "music-audio": "MUSIC_AUDIO", "video": "VIDEO", "torah": "TORAH",
    "productivity": "PRODUCTIVITY", "tools": "TOOLS", "finance": "FINANCE",
    "health-fitness": "HEALTH_FITNESS", "news": "NEWS",
    "governement": "GOVERNMENT", "home": "HOME", "system": "SYSTEM",
}
POLICY_BUNDLE = "policies.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PACKAGE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+$")


def validate(path, entry, errors, warnings):
    def err(msg):
        errors.append(f"{path}: {msg}")

    def warn(msg):
        warnings.append(f"{path}: {msg}")

    pkg = entry.get("packageName", "")
    if not PACKAGE_RE.match(pkg):
        err(f"invalid packageName '{pkg}'")

    expected_name = os.path.basename(path)[:-5]
    if pkg != expected_name:
        err(f"filename '{expected_name}.json' does not match packageName '{pkg}'")

    category = entry.get("category")
    if category not in CATEGORIES:
        err(f"unknown category '{category}'")

    parent = os.path.basename(os.path.dirname(path))
    if DIR_TO_CATEGORY.get(parent) != category:
        err(f"file sits in '{parent}/' but declares category '{category}'")

    names = entry.get("displayName", {})
    for lang in ("he", "en"):
        if not names.get(lang):
            err(f"displayName is missing '{lang}'")

    sha = entry.get("sha256", "")
    if category == "SYSTEM":
        if sha and not SHA256_RE.match(sha):
            err("sha256 must be 64 lower case hex characters, or empty for SYSTEM")
    else:
        if not SHA256_RE.match(sha):
            err("sha256 must be exactly 64 lower case hex characters")
        if sha == "0" * 64:
            err("sha256 is still the placeholder; compute the real digest")

    extra = entry.get("additionalSha256", [])
    if not isinstance(extra, list):
        err("additionalSha256 must be a list")
    else:
        for digest in extra:
            if not isinstance(digest, str) or not SHA256_RE.match(digest):
                err(f"additionalSha256 entry '{digest}' is not 64 lower case hex "
                    f"characters")
            elif digest == sha:
                err("additionalSha256 repeats the primary sha256")
        if extra:
            # Every certificate here is another key allowed to speak for this
            # package, so it should be a deliberate exception and visible on
            # every build rather than something that accumulates quietly.
            warn(f"accepts {len(extra) + 1} signing certificates")

    if not isinstance(entry.get("minimumVersionCode"), int):
        err("minimumVersionCode must be an integer")

    mode = entry.get("minUserMode", "MOST_OPEN")
    if mode not in MODES:
        err(f"unknown minUserMode '{mode}'")

    # A network granting entry with no minimum version is a downgrade hole,
    # but only where we are the ones handing out the file. An entry that is not
    # available in the store is preinstalled: it arrives from the system image
    # or an OEM update, so a minimum version code here would decide nothing.
    #
    # Where we do serve the file, a certificate pin already rules out a
    # substituted app. What is left is an older genuine build, which is worth
    # saying out loud on every run without refusing to publish over it.
    if (
        entry.get("grantsNetworkAccess")
        and entry.get("minimumVersionCode", 0) == 0
        and entry.get("availableInStore")
        and category != "SYSTEM"
    ):
        if SHA256_RE.match(sha):
            warn("grantsNetworkAccess with minimumVersionCode 0: pinned to a "
                 "certificate, so an older genuine build can still install")
        else:
            err("grantsNetworkAccess with minimumVersionCode 0 and no sha256 "
                "pin allows a downgrade")


def revision_of(entries):
    """A fingerprint of the data, and of nothing else.

    Deliberately not the hash of the output file: that file carries a build
    timestamp, so hashing it would produce a new revision on every rebuild, and
    every device on the network would redownload an identical catalog. The
    revision is what the app compares against, so it tracks the entries alone.
    """
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def build(root, allow_placeholder):
    """Returns (entries, errors, warnings)."""
    paths = sorted(glob.glob(os.path.join(root, "*", "*.json")))
    entries, errors, warnings, seen = [], [], [], {}

    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                entry = json.load(fh)
        except Exception as exc:
            errors.append(f"{path}: unparsable JSON ({exc})")
            continue

        validate(path, entry, errors, warnings)

        pkg = entry.get("packageName")
        if pkg in seen:
            errors.append(f"{path}: duplicate of {seen[pkg]}")
        else:
            seen[pkg] = path
        entries.append(entry)

    if allow_placeholder:
        errors = [e for e in errors if "placeholder" not in e]

    return sorted(entries, key=lambda e: e["packageName"]), errors, warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="catalog.json")
    parser.add_argument("--version-out", default="catalog.version",
                        help="side car the app polls before downloading")
    parser.add_argument("--root", default="apps")
    parser.add_argument("--allow-placeholder", action="store_true",
                        help="permit the all zero sha256, for local testing only")
    parser.add_argument("--check", action="store_true",
                        help="validate and compare against the committed files "
                             "instead of writing, for CI")
    args = parser.parse_args()

    entries, errors, warnings = build(args.root, args.allow_placeholder)

    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)

    if errors:
        print("Catalog validation failed:\n", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    revision = revision_of(entries)

    if args.check:
        try:
            with open(args.out, encoding="utf-8") as fh:
                committed = json.load(fh)
            with open(args.version_out, encoding="utf-8") as fh:
                side = json.load(fh)
        except Exception as exc:
            print(f"Cannot read the committed build ({exc}); "
                  f"run tools/release.sh", file=sys.stderr)
            return 1

        if committed.get("entries") != entries:
            print(f"{args.out} does not match apps/; run tools/release.sh",
                  file=sys.stderr)
            return 1
        if side.get("revision") != revision:
            print(f"{args.version_out} carries revision {side.get('revision')}, "
                  f"the data says {revision}; run tools/release.sh",
                  file=sys.stderr)
            return 1

        print(f"catalog.json is in sync with apps/: "
              f"{len(entries)} entries, revision {revision}")
        return 0

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    document = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "entries": entries,
    }
    write_json(args.out, document)

    # The side car names both documents on purpose. It is the one small file a
    # device polls before downloading anything, so it is also the only place
    # that can say "this catalog and these policies were published together".
    # Without the policy tag here the app had nothing to compare against and
    # redownloaded the policy bundle on every run.
    policy_tag = None
    if os.path.exists(POLICY_BUNDLE):
        try:
            with open(POLICY_BUNDLE, encoding="utf-8") as fh:
                policy_tag = json.load(fh).get("sourceTag")
        except Exception as exc:
            print(f"warning: cannot read {POLICY_BUNDLE} ({exc}); "
                  f"the side car will not carry a policy tag", file=sys.stderr)

    write_json(args.version_out, {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "entryCount": len(entries),
        "revision": revision,
        "policyTag": policy_tag,
    })

    granting = sum(1 for e in entries if e.get("grantsNetworkAccess"))
    print(f"Wrote {args.out}: {len(entries)} entries, {granting} granted network, "
          f"revision {revision}")
    return 0


def write_json(path, document):
    # newline="\n" on purpose. The signature covers the exact bytes GitHub
    # serves, and a CRLF translation on the way to disk would invalidate it.
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(document, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


if __name__ == "__main__":
    sys.exit(main())
