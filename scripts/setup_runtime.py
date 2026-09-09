"""Optional local-only Neo4j runtime. Downloads dependencies, never evidence.

Uses a portable JRE and Neo4j Community in .runtime; no services or global PATH
changes. Invoke with --start after setup to run the database in the background.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
NEO_VERSION = "5.26.30"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "DFIR-local-development/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def download(url, target, expected):
    if target.exists():
        with target.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() == expected:
                return
    print("Downloading " + target.name, flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "DFIR-local-development/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as output:
        while block := response.read(1024 * 1024):
            output.write(block)
    with target.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise RuntimeError("SHA-256 mismatch: " + target.name)


def extract(archive):
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            target = (RUNTIME / entry.filename).resolve()
            if RUNTIME.resolve() not in target.parents:
                raise ValueError("Archive member outside runtime directory")
        z.extractall(RUNTIME)


def install():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    info_file = RUNTIME / "connection.json"
    if info_file.exists():
        return json.loads(info_file.read_text(encoding="utf-8"))
    api = "https://api.adoptium.net/v3/assets/latest/21/hotspot?architecture=x64&image_type=jre&os=windows&vendor=eclipse"
    package = json.loads(fetch(api))[0]["binary"]["package"]
    java_zip = RUNTIME / package["name"]
    download(package["link"], java_zip, package["checksum"])
    extract(java_zip)
    java = next(RUNTIME.glob("jdk*-jre/bin/java.exe"))
    neo_zip = RUNTIME / f"neo4j-community-{NEO_VERSION}-windows.zip"
    url = "https://dist.neo4j.org/" + neo_zip.name
    checksum = fetch(url + ".sha256").decode().strip().split()[0]
    download(url, neo_zip, checksum)
    extract(neo_zip)
    neo_home = RUNTIME / f"neo4j-community-{NEO_VERSION}"
    password = secrets.token_urlsafe(24)
    config = "\n".join([
        "server.default_listen_address=127.0.0.1", "server.default_advertised_address=127.0.0.1",
        "server.bolt.enabled=true", "server.bolt.listen_address=127.0.0.1:17687",
        "server.bolt.advertised_address=127.0.0.1:17687", "server.http.enabled=true",
        "server.http.listen_address=127.0.0.1:17474", "server.http.advertised_address=127.0.0.1:17474",
        "server.https.enabled=false", "server.memory.heap.initial_size=256m",
        "server.memory.heap.max_size=512m", "server.memory.pagecache.size=256m",
        "dbms.memory.transaction.total.max=128m", "dbms.security.auth_enabled=true",
        "dbms.usage_report.enabled=false", ""])
    (neo_home / "conf" / "neo4j.conf").write_text(config, encoding="utf-8")
    env = os.environ.copy()
    env["JAVA_HOME"] = str(java.parents[1])
    subprocess.run([str(neo_home / "bin" / "neo4j-admin.bat"), "dbms", "set-initial-password", password],
                   env=env, check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--target",
                    str(RUNTIME / "python-libs"), "-r", str(ROOT / "requirements.txt")], check=True)
    info = {"uri": "bolt://127.0.0.1:17687", "browser": "http://127.0.0.1:17474",
            "user": "neo4j", "password": password, "java_home": str(java.parents[1]),
            "neo4j_home": str(neo_home), "neo4j_version": NEO_VERSION,
            "java_archive_sha256": package["checksum"], "neo4j_archive_sha256": checksum}
    info_file.write_text(json.dumps(info, indent=2), encoding="utf-8")
    print("Portable runtime installed in " + str(RUNTIME), flush=True)
    return info


def start(info):
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 17687)) == 0:
            print("Port 17687 is already in use; no additional server started.")
            return
    env = os.environ.copy()
    env["JAVA_HOME"] = info["java_home"]
    with (RUNTIME / "server.stdout.log").open("ab") as log:
        process = subprocess.Popen([str(Path(info["neo4j_home"]) / "bin" / "neo4j.bat"), "console"],
                                   cwd=info["neo4j_home"], env=env, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    (RUNTIME / "server-process.json").write_text(json.dumps({"pid": process.pid}), encoding="utf-8")
    deadline = time.monotonic() + 55
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Neo4j exited; inspect .runtime/server.stdout.log")
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 17687)) == 0:
                print("Neo4j ready: " + info["browser"], flush=True)
                return
        time.sleep(1)
    raise RuntimeError("Neo4j startup not confirmed after 55 seconds; inspect .runtime/server.stdout.log")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", action="store_true")
    args = parser.parse_args()
    configuration = install()
    if args.start:
        start(configuration)
