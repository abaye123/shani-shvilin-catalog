#!/usr/bin/env python3
"""Reads an APK and prints the hosts it appears to talk to.

    python tools/extract_hosts.py app.apk
    python tools/extract_hosts.py app.apk --json      # a hosts array to paste

Why this exists
---------------
Writing a policy means naming hosts. Watching the tunnel answers that question
for an application that is running on a device, through it, right now; this
answers it for an APK sitting on a disk, before anything is installed and
without a device in the loop at all.

The two disagree in useful ways. This finds names the application carries and
may never use, including the ones it only reaches on a screen nobody opened
during a test. It cannot find a name assembled at runtime, fetched from a
server or hidden in an encrypted blob. So: run both, and treat neither as the
answer on its own.

What it reads
-------------
Everything in the archive that can hold a string, which in practice means the
dex files, the compiled resources, the manifest and the assets. Strings are
pulled out the way `strings` does it, because the dex string pool is a length
prefixed MUTF-8 table and reconstructing it properly buys nothing here: a run
of printable bytes is exactly what a URL looks like in it.

The network security configuration, when there is one, is read separately and
reported separately. It is the highest quality signal in the file: a list of
domains the developer wrote down on purpose.

What it gets wrong
------------------
It over reports. Analytics endpoints, SDK defaults, documentation links and
schema URLs all live in the same string pool as the real ones, and a Java
package name is spelled exactly like a hostname backwards, which is why
com.google.android.gms is not in the output and maps.googleapis.com is. Read
the list, do not paste it.
"""
import argparse
import io
import json
import re
import sys
import zipfile
from collections import defaultdict

# Anything that can hold a string. res/ and assets/ are globbed rather than
# named because an application can put a configuration file anywhere.
INTERESTING = (
    'classes', '.dex', 'resources.arsc', 'AndroidManifest.xml',
    'res/', 'assets/',
)

PRINTABLE = re.compile(rb'[\x20-\x7e]{6,}')
URL = re.compile(r'https?://([a-z0-9][a-z0-9\-._]*[a-z0-9])', re.I)
BARE_HOST = re.compile(r'\b([a-z0-9][a-z0-9\-]*(?:\.[a-z0-9][a-z0-9\-]*)+)\b', re.I)

# The first label of a Java package, and never the first label of a hostname
# anyone serves from. This is what keeps com.google.android.gms.internal out.
PACKAGE_PREFIXES = {
    'com', 'org', 'net', 'io', 'android', 'androidx', 'java', 'javax', 'kotlin',
    'kotlinx', 'dalvik', 'sun', 'jdk', 'de', 'uk', 'fr', 'ru', 'cn', 'jp', 'il',
    'me', 'co', 'edu', 'gov', 'info', 'biz', 'tv', 'app', 'dev', 'ai',
}

# Present in every application and never worth blocking.
NOISE_SUFFIXES = (
    'schemas.android.com', 'w3.org', 'apache.org', 'xml.org', 'example.com',
    'example.org', 'localhost', 'json-schema.org', 'purl.org', 'iana.org',
    'ietf.org', 'gnu.org', 'opensource.org', 'creativecommons.org',
    'oracle.com', 'sun.com', 'kotlinlang.org', 'jetbrains.com',
    'schema.org', 'xmlpull.org', 'slf4j.org', 'unicode.org',
)

TLD = re.compile(r'\.[a-z]{2,24}$', re.I)


def strings_in(data: bytes):
    for match in PRINTABLE.finditer(data):
        yield match.group().decode('ascii', 'ignore')


def looks_like_host(candidate: str) -> bool:
    host = candidate.lower().strip('.')
    if len(host) < 4 or '.' not in host:
        return False
    if not TLD.search(host):
        return False
    if host.split('.')[0] in PACKAGE_PREFIXES:
        # com.something is a package name; www.something is not.
        return False
    if any(host == n or host.endswith('.' + n) for n in NOISE_SUFFIXES):
        return False
    # A label that is all digits at the end means an address, not a name.
    if host.split('.')[-1].isdigit():
        return False
    # Filenames caught by the same shape: image.png, strings.xml.
    if host.rsplit('.', 1)[-1] in {
        'png', 'jpg', 'jpeg', 'gif', 'webp', 'xml', 'json', 'txt', 'so', 'js',
        'css', 'html', 'htm', 'ttf', 'otf', 'svg', 'md', 'properties', 'proto',
        'kt', 'java', 'class', 'dex', 'apk', 'zip', 'gz', 'pb', 'bin', 'dat',
        'ini', 'cfg', 'yml', 'yaml', 'db', 'sql', 'lock', 'map', 'ico', 'mp3',
        'mp4', 'wav', 'ogg', 'pdf', 'woff', 'woff2', 'eot',
    }:
        return False
    return True


def scan(path: str):
    """Returns (from_urls, bare_candidates, security_config)."""
    from_urls = defaultdict(set)
    bare = set()
    security_config = set()

    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            name = info.filename
            if not any(k in name for k in INTERESTING):
                continue
            try:
                data = zf.read(info)
            except Exception:
                continue

            # A network security configuration is worth reading as text even
            # though it is compiled: the domain names survive as strings.
            is_nsc = 'network_security' in name or 'network-security' in name

            for text in strings_in(data):
                for match in URL.finditer(text):
                    host = match.group(1).lower().rstrip('.')
                    if looks_like_host(host):
                        from_urls[host].add(name)
                if is_nsc:
                    for match in BARE_HOST.finditer(text):
                        host = match.group(1).lower()
                        if looks_like_host(host):
                            security_config.add(host)
                else:
                    for match in BARE_HOST.finditer(text):
                        host = match.group(1).lower()
                        if looks_like_host(host):
                            bare.add(host)

    return from_urls, bare, security_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('apk')
    parser.add_argument('--json', action='store_true',
                        help='print a hosts array ready to paste into a policy')
    parser.add_argument('--all', action='store_true',
                        help='include the low confidence candidates')
    args = parser.parse_args()

    try:
        from_urls, bare, nsc = scan(args.apk)
    except FileNotFoundError:
        print(f'No such file: {args.apk}', file=sys.stderr)
        return 1
    except zipfile.BadZipFile:
        print(f'Not an APK: {args.apk}', file=sys.stderr)
        return 1

    confident = sorted(set(from_urls) | nsc)
    candidates = sorted(bare - set(confident))

    if args.json:
        chosen = confident + (candidates if args.all else [])
        print(json.dumps(sorted(set(chosen)), indent=2, ensure_ascii=False))
        return 0

    print(f'{args.apk}\n')

    if nsc:
        print(f'Network security configuration ({len(nsc)}):')
        print('  the domains the developer wrote down on purpose')
        for host in sorted(nsc):
            print(f'    {host}')
        print()

    print(f'Hosts found inside URLs ({len(from_urls)}):')
    for host in sorted(from_urls):
        print(f'    {host}')
    print()

    print(f'Other dotted names ({len(candidates)}):')
    print('  lower confidence: these are not inside a URL, so some are not hosts')
    for host in candidates[:200]:
        print(f'    {host}')
    if len(candidates) > 200:
        print(f'    ... and {len(candidates) - 200} more')

    print()
    print('Read the list, do not paste it. A name here is one the application '
          'carries, not one it necessarily uses, and a name it builds at '
          'runtime will not be here at all.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
