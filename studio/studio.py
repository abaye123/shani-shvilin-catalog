#!/usr/bin/env python3
"""Catalog Studio: a local, visual editor for this repository.

    python studio/studio.py            # opens http://127.0.0.1:8765

Everything the README's "adding a new app" walks through by hand, on one page:
look an application up on Google Play, choose which of its screenshots the
store may show, download its APK, read the signing certificate and version
from it, list the hosts it appears to talk to and pick what to block, and write
apps/<category>/<package>.json and policies/<category>/<package>.json. Then
build, sign and commit, from the same page.

It listens on 127.0.0.1 only. It reads and writes this repository and nothing
else, and it never pushes: publishing stays a deliberate step.

Needs: Python 3.10+, `pip install google-play-scraper`, and the Android SDK
build tools (apksigner, aapt2) for reading APKs. Signing uses tools/release.sh
and the private key outside the repository, exactly as by hand.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
import webbrowser
import zipfile
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC = os.path.join(os.path.dirname(__file__), "static")
CACHE = os.path.join(os.path.dirname(__file__), "cache")
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_catalog  # noqa: E402
import build_policies  # noqa: E402
import extract_hosts  # noqa: E402

HOST = "127.0.0.1"
PORT = int(os.environ.get("STUDIO_PORT", "8765"))
PACKAGE_RE = build_catalog.PACKAGE_RE
CATEGORY_TO_DIR = {v: k for k, v in build_catalog.DIR_TO_CATEGORY.items()}

APKPURE = "https://d.apkpure.com/b/{kind}/{pkg}?version=latest"
BROWSER_UA = (
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

def entry_path(category, pkg):
    return os.path.join(ROOT, "apps", CATEGORY_TO_DIR[category], f"{pkg}.json")


def policy_path(category, pkg):
    return os.path.join(ROOT, "policies", CATEGORY_TO_DIR[category], f"{pkg}.json")


def find_file(kind, pkg):
    """The existing file for a package under apps/ or policies/, in any category."""
    base = os.path.join(ROOT, kind)
    for directory in os.listdir(base):
        candidate = os.path.join(base, directory, f"{pkg}.json")
        if os.path.isfile(candidate):
            return candidate
    return None


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def list_apps():
    apps = []
    for directory in sorted(os.listdir(os.path.join(ROOT, "apps"))):
        folder = os.path.join(ROOT, "apps", directory)
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".json"):
                continue
            entry = read_json(os.path.join(folder, name))
            pkg = entry.get("packageName", name[:-5])
            apps.append({
                "packageName": pkg,
                "name": entry.get("displayName", {}).get("he") or pkg,
                "category": entry.get("category"),
                "availableInStore": entry.get("availableInStore", True),
                "grantsNetworkAccess": entry.get("grantsNetworkAccess", False),
                "screenshots": len(entry.get("screenshots", [])),
                "hasPolicy": find_file("policies", pkg) is not None,
            })
    return apps


def load_app(pkg):
    entry = find_file("apps", pkg)
    policy = find_file("policies", pkg)
    return {
        "entry": read_json(entry) if entry else None,
        "policy": read_json(policy) if policy else None,
    }


def save_app(entry, policy):
    """Validates both documents and writes them, moving files on a category change."""
    pkg = entry.get("packageName", "")
    if not PACKAGE_RE.match(pkg):
        return {"ok": False, "errors": [f"שם חבילה לא תקין: {pkg}"]}
    category = entry.get("category")
    if category not in CATEGORY_TO_DIR:
        return {"ok": False, "errors": [f"קטגוריה לא מוכרת: {category}"]}

    target = entry_path(category, pkg)
    errors, warnings = [], []
    build_catalog.validate(target, entry, errors, warnings)

    policy_target = None
    if policy:
        policy = {**policy, "packageName": pkg, "category": category}
        policy_target = policy_path(category, pkg)
        build_policies.validate(policy_target, policy, errors)

    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}

    old_entry, old_policy = find_file("apps", pkg), find_file("policies", pkg)
    write_json(target, entry)
    if old_entry and os.path.abspath(old_entry) != os.path.abspath(target):
        os.remove(old_entry)
    if policy_target:
        write_json(policy_target, policy)
        if old_policy and os.path.abspath(old_policy) != os.path.abspath(policy_target):
            os.remove(old_policy)
    elif old_policy:
        os.remove(old_policy)
    return {"ok": True, "warnings": warnings, "path": os.path.relpath(target, ROOT)}


def run(command, timeout=300):
    """Runs a command in the repository and returns its combined output."""
    try:
        done = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        return {"ok": done.returncode == 0, "code": done.returncode,
                "output": (done.stdout + done.stderr).strip()}
    except FileNotFoundError as e:
        return {"ok": False, "code": -1, "output": f"לא נמצא: {e.filename}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -1, "output": "הפקודה לא הסתיימה בזמן"}


def bash():
    """Git Bash on Windows, plain bash elsewhere."""
    for candidate in (r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash")):
        if candidate and os.path.isfile(candidate):
            return candidate
    return "bash"


# ---------------------------------------------------------------------------
# Google Play
# ---------------------------------------------------------------------------

def play_info(pkg):
    try:
        from google_play_scraper import app as play_app
    except ImportError:
        return {"ok": False, "error": "חסרה הספרייה: pip install google-play-scraper"}
    try:
        info = play_app(pkg, lang="iw", country="il")
    except Exception as e:  # the library raises its own NotFoundError and plain errors
        return {"ok": False, "error": f"לא נמצא ב-Google Play ({type(e).__name__})"}
    keys = (
        "title", "developer", "developerWebsite", "icon", "summary", "description",
        "genre", "installs", "score", "ratings", "version", "updated", "released",
        "contentRating", "containsAds", "offersIAP", "free", "screenshots", "privacyPolicy",
    )
    return {"ok": True, "info": {k: info.get(k) for k in keys}}


# ---------------------------------------------------------------------------
# APK
# ---------------------------------------------------------------------------

def build_tools():
    """The newest Android SDK build-tools directory, or None."""
    roots = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk")]
    for root in filter(None, roots):
        folder = os.path.join(root, "build-tools")
        if os.path.isdir(folder):
            versions = sorted(os.listdir(folder), key=lambda v: [int(p) if p.isdigit() else 0 for p in re.split(r"[.-]", v)])
            if versions:
                return os.path.join(folder, versions[-1])
    return None


def tool(name):
    folder = build_tools()
    if not folder:
        return None
    for suffix in (".bat", ".exe", ""):
        candidate = os.path.join(folder, name + suffix)
        if os.path.isfile(candidate):
            return candidate
    return None


def download_apk(pkg):
    """Fetches the current release from APKPure, bundle first, into the cache."""
    folder = os.path.join(CACHE, pkg)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    last_error = None
    for kind in ("XAPK", "APK"):
        request = urllib.request.Request(APKPURE.format(kind=kind, pkg=pkg), headers={"User-Agent": BROWSER_UA})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
        except Exception as e:
            last_error = f"{kind}: {e}"
            continue
        if not data.startswith(b"PK"):
            last_error = f"{kind}: התקבל דף ולא קובץ (ייתכן חסימה של מסנן הרשת)"
            continue
        archive = os.path.join(folder, f"{pkg}.{kind.lower()}")
        with open(archive, "wb") as fh:
            fh.write(data)
        return unpack(archive, folder, pkg)
    return {"ok": False, "error": last_error or "ההורדה נכשלה"}


def unpack(archive, folder, pkg):
    """Base APK and splits from an XAPK, or the APK itself."""
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        apks = [n for n in names if n.lower().endswith(".apk")]
        if not apks:  # a plain APK: the archive is the base
            base = os.path.join(folder, "base.apk")
            shutil.copyfile(archive, base)
            files = [base]
        else:
            files = []
            for name in apks:
                out = os.path.join(folder, os.path.basename(name))
                with zf.open(name) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                files.append(out)
            stems = {os.path.basename(f)[:-4]: f for f in files}
            base = stems.get("base") or stems.get(pkg) or max(files, key=os.path.getsize)
    return {"ok": True, "archive": os.path.basename(archive), "size": os.path.getsize(archive),
            "base": base, "files": files, **read_apk(base)}


def read_apk(path):
    """Signing certificate digests, package name and versions of one APK."""
    result = {"sha256": [], "versionCode": None, "versionName": None, "packageName": None, "notes": []}
    apksigner = tool("apksigner")
    if apksigner:
        out = run([apksigner, "verify", "--print-certs", path])["output"]
        # Signer lines only: a source stamp certificate prints a digest too,
        # and it says who built the file, not who may speak for the package.
        result["sha256"] = sorted(set(re.findall(r"Signer #\d+ certificate SHA-256 digest:\s*([0-9a-f]{64})", out)))
    else:
        result["notes"].append("apksigner לא נמצא: התקינו את Android SDK build-tools")
    aapt2 = tool("aapt2")
    if aapt2:
        out = run([aapt2, "dump", "badging", path])["output"]
        found = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", out)
        if found:
            result["packageName"], code, result["versionName"] = found.groups()
            result["versionCode"] = int(code)
    else:
        result["notes"].append("aapt2 לא נמצא")
    return result


def hosts_of(pkg):
    """Hosts named in every APK of the cached download, with where each was found."""
    folder = os.path.join(CACHE, pkg)
    if not os.path.isdir(folder):
        return {"ok": False, "error": "צריך להוריד את ה-APK קודם"}
    from_urls, bare, nsc = set(), set(), set()
    for name in os.listdir(folder):
        if name.endswith(".apk"):
            u, b, s = extract_hosts.scan(os.path.join(folder, name))
            from_urls |= set(u)
            bare |= set(b)
            nsc |= set(s or [])
    return {"ok": True, "urls": sorted(from_urls), "bare": sorted(bare - from_urls), "nsc": sorted(nsc)}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC, **kwargs)

    def log_message(self, fmt, *args):  # quiet
        pass

    def send_json(self, value, status=HTTPStatus.OK):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def package(self, value):
        if not value or not PACKAGE_RE.match(value):
            self.send_json({"ok": False, "error": "שם חבילה לא תקין"}, HTTPStatus.BAD_REQUEST)
            return None
        return value

    def do_GET(self):
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/apps":
            return self.send_json({"ok": True, "apps": list_apps(),
                                   "categories": sorted(CATEGORY_TO_DIR), "modes": sorted(build_catalog.MODES)})
        if url.path == "/api/app":
            pkg = self.package(query.get("pkg"))
            return pkg and self.send_json({"ok": True, **load_app(pkg)})
        if url.path == "/api/play":
            pkg = self.package(query.get("pkg"))
            return pkg and self.send_json(play_info(pkg))
        if url.path == "/api/status":
            return self.send_json(run(["git", "status", "--short"]))
        return super().do_GET()

    def do_POST(self):
        url = urlparse(self.path)
        data = self.body()
        if url.path == "/api/save":
            return self.send_json(save_app(data.get("entry") or {}, data.get("policy")))
        if url.path == "/api/apk":
            pkg = self.package(data.get("pkg"))
            return pkg and self.send_json(download_apk(pkg))
        if url.path == "/api/hosts":
            pkg = self.package(data.get("pkg"))
            return pkg and self.send_json(hosts_of(pkg))
        if url.path == "/api/build":
            policies = run([sys.executable, "tools/build_policies.py", "--out", "policies.json"])
            catalog = run([sys.executable, "tools/build_catalog.py", "--out", "catalog.json",
                           "--version-out", "catalog.version"])
            return self.send_json({"ok": policies["ok"] and catalog["ok"],
                                   "output": policies["output"] + "\n" + catalog["output"]})
        if url.path == "/api/release":
            args = [bash(), "tools/release.sh"]
            if data.get("key"):
                args.append(data["key"])
            return self.send_json(run(args))
        if url.path == "/api/commit":
            message = (data.get("message") or "").strip()
            if not message:
                return self.send_json({"ok": False, "output": "חסרה הודעת commit"})
            add = run(["git", "add", "-A", "apps", "policies", "catalog.json", "catalog.version",
                       "policies.json", "signatures.json", "catalog.json.sig", "policies.json.sig"])
            if not add["ok"]:
                return self.send_json(add)
            return self.send_json(run(["git", "commit", "-m", message]))
        return self.send_json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)


def main():
    os.makedirs(CACHE, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    address = f"http://{HOST}:{PORT}/"
    print(f"Catalog Studio: {address}  (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, lambda: webbrowser.open(address)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
