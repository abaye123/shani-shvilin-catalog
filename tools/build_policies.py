#!/usr/bin/env python3
"""Merges policies/**/*.json into a single policies.json and validates it.

The catalog answers "who": which apps exist and which of them get network.
This file answers "what": once an app is allowed out, which hosts it may
reach. The format is KDroidDatabase's, so a document can be copied from there
unchanged.

Usage:
    python tools/build_policies.py --out policies.json
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

from build_catalog import CATEGORIES, DIR_TO_CATEGORY, PACKAGE_RE, write_json

TYPES = {"Fixed", "ModeBased", "MultiMode"}
NETWORK_MODES = {"OFFLINE", "FULL_OPEN", "WHITELIST", "BLACKLIST"}
USER_MODES = {
    "OFFLINE", "LOCAL_ONLY", "NAVIGATION_ONLY", "NAVIGATION_AND_MAIL_ONLY",
    "REDUCED_RISK", "MOST_OPEN",
}
HOST_RE = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def validate_network_policy(where, policy, errors):
    mode = policy.get("mode")
    if mode not in NETWORK_MODES:
        errors.append(f"{where}: unknown network mode '{mode}'")
        return

    spec = policy.get("spec")
    if mode in ("WHITELIST", "BLACKLIST"):
        if not isinstance(spec, dict) or spec.get("type") != "HostList":
            errors.append(f"{where}: {mode} needs a HostList spec")
            return
        hosts = spec.get("hosts")
        if not isinstance(hosts, list) or not hosts:
            errors.append(f"{where}: {mode} with an empty host list")
            return
        for host in hosts:
            if not isinstance(host, str) or not HOST_RE.match(host.strip().lower()):
                errors.append(f"{where}: '{host}' is not a hostname")
    elif spec is not None:
        errors.append(f"{where}: {mode} takes no spec")


def validate(path, doc, errors):
    def err(msg):
        errors.append(f"{path}: {msg}")

    kind = doc.get("type")
    if kind not in TYPES:
        err(f"unknown policy type '{kind}'")

    pkg = doc.get("packageName", "")
    if not PACKAGE_RE.match(pkg):
        err(f"invalid packageName '{pkg}'")

    expected_name = os.path.basename(path)[:-5]
    if pkg != expected_name:
        err(f"filename '{expected_name}.json' does not match packageName '{pkg}'")

    category = doc.get("category")
    if category not in CATEGORIES:
        err(f"unknown category '{category}'")

    parent = os.path.basename(os.path.dirname(path))
    if DIR_TO_CATEGORY.get(parent) != category:
        err(f"file sits in '{parent}/' but declares category '{category}'")

    if not isinstance(doc.get("minimumVersionCode"), int):
        err("minimumVersionCode must be an integer")

    if kind == "Fixed":
        policy = doc.get("networkPolicy")
        if not isinstance(policy, dict):
            err("Fixed needs a networkPolicy")
        else:
            validate_network_policy(f"{path} networkPolicy", policy, errors)

    elif kind == "ModeBased":
        modes = doc.get("modePolicies")
        if not isinstance(modes, dict) or not modes:
            err("ModeBased needs a non empty modePolicies")
        else:
            for mode, policy in modes.items():
                if mode not in USER_MODES:
                    err(f"unknown user mode '{mode}' in modePolicies")
                validate_network_policy(f"{path} modePolicies.{mode}", policy, errors)

    elif kind == "MultiMode":
        variants = doc.get("modeVariants")
        if not isinstance(variants, list) or not variants:
            err("MultiMode needs a non empty modeVariants")
            return
        for group in variants:
            mode = group.get("userMode")
            if mode not in USER_MODES:
                err(f"unknown user mode '{mode}' in modeVariants")
            ids = [v.get("id") for v in group.get("variants", [])]
            if not ids:
                err(f"modeVariants for '{mode}' has no variants")
            if len(ids) != len(set(ids)):
                err(f"modeVariants for '{mode}' has duplicate variant ids")
            default = group.get("defaultVariantId")
            if default is not None and default not in ids:
                err(f"defaultVariantId '{default}' is not one of {ids}")


def source_tag_of(policies):
    canonical = json.dumps(policies, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def build(root):
    paths = sorted(glob.glob(os.path.join(root, "*", "*.json")))
    policies, errors, seen = [], [], {}

    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception as exc:
            errors.append(f"{path}: unparsable JSON ({exc})")
            continue

        validate(path, doc, errors)

        pkg = doc.get("packageName")
        if pkg in seen:
            errors.append(f"{path}: duplicate of {seen[pkg]}")
        else:
            seen[pkg] = path
        policies.append(doc)

    return sorted(policies, key=lambda p: p["packageName"]), errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="policies.json")
    parser.add_argument("--root", default="policies")
    parser.add_argument("--check", action="store_true",
                        help="compare against the committed file instead of "
                             "writing, for CI")
    args = parser.parse_args()

    policies, errors = build(args.root)
    if errors:
        print("Policy validation failed:\n", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    tag = source_tag_of(policies)

    if args.check:
        try:
            with open(args.out, encoding="utf-8") as fh:
                committed = json.load(fh)
        except Exception as exc:
            print(f"Cannot read {args.out} ({exc}); run tools/release.sh",
                  file=sys.stderr)
            return 1
        if committed.get("policies") != policies:
            print(f"{args.out} does not match {args.root}/; run tools/release.sh",
                  file=sys.stderr)
            return 1
        if committed.get("sourceTag") != tag:
            print(f"{args.out} carries sourceTag {committed.get('sourceTag')}, "
                  f"the data says {tag}; run tools/release.sh", file=sys.stderr)
            return 1
        print(f"policies.json is in sync with {args.root}/: "
              f"{len(policies)} policies, tag {tag}")
        return 0

    write_json(args.out, {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sourceTag": tag,
        "policies": policies,
    })

    print(f"Wrote {args.out}: {len(policies)} policies, tag {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
