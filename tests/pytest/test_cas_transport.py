"""Tests for scripts/cas_transport.py.

The CLI tests run the script as a subprocess with stub `oras`, `podman` and
`zstd` commands first on PATH, so no registry, container runtime or bst2
image is needed. The `zstd` stub passes bytes through unchanged, so the
archives in these tests are plain tar streams.
"""

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import textwrap
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "cas_transport.py"

_spec = importlib.util.spec_from_file_location("cas_transport", SCRIPT_PATH)
cas_transport = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cas_transport)

REF = "ghcr.io/tuna-os/tromso/cache-tromso-core:latest"
DIGEST = "sha256:" + "a" * 64

# Every stub appends one JSON line per call to $STUB_LOG and reads its
# behaviour from the JSON file at $STUB_CONFIG.
STUB_PRELUDE = f"""\
#!{sys.executable}
import json, os, subprocess, sys
config = json.load(open(os.environ["STUB_CONFIG"]))
with open(os.environ["STUB_LOG"], "a") as log:
    log.write(json.dumps([os.path.basename(sys.argv[0]), *sys.argv[1:]]) + "\\n")
args = sys.argv[1:]
"""

ORAS_STUB = """
if args[:2] == ["manifest", "fetch"]:
    manifest = config.get("manifests", {}).get(args[2])
    if manifest is None:
        sys.exit(1)
    print(json.dumps(manifest))
elif args[:2] == ["blob", "fetch"]:
    if config.get("blob_rc"):
        sys.exit(config["blob_rc"])
    sys.stdout.buffer.write(open(config["blobs"][args[-1]], "rb").read())
elif args[0] == "push":
    rcs = config.get("push_rcs", [0])
    calls = sum(1 for line in open(os.environ["STUB_LOG"]) if '"push"' in line)
    sys.exit(rcs[min(calls, len(rcs)) - 1])
"""

ZSTD_STUB = """
sys.stdout.buffer.write(sys.stdin.buffer.read())
"""

PODMAN_STUB = """
if args[0] == "ps":
    print("\\n".join(config.get("ps", [])))
elif args[0] == "inspect":
    source = config.get("mounts", {}).get(args[-1])
    if source is None:
        sys.exit(125)
    print(source)
elif args[:2] == ["container", "exists"]:
    sys.exit(config.get("exists_rc", {}).get(args[2], 0))
elif args[0] == "stop":
    pass
elif args[0] == "run":
    if config.get("run_rc"):
        sys.exit(config["run_rc"])
    mounts = {}
    rest = args[2:]
    while rest[0] == "-v":
        source, target, _mode = rest[1].split(":")
        mounts[target] = source
        rest = rest[2:]
    command = rest[-1]
    for target, source in mounts.items():
        command = command.replace(target, source)
    sys.exit(subprocess.run(["bash", "-o", "pipefail", "-c", command]).returncode)
"""


@pytest.fixture
def stubs(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("oras", ORAS_STUB), ("podman", PODMAN_STUB), ("zstd", ZSTD_STUB)):
        stub = bin_dir / name
        stub.write_text(STUB_PRELUDE + textwrap.dedent(body))
        stub.chmod(0o755)
    config_path = tmp_path / "stub-config.json"
    log_path = tmp_path / "stub-log.jsonl"
    log_path.touch()

    class Stubs:
        config = {}

        def run(self, *args):
            config_path.write_text(json.dumps(self.config))
            env = {
                **os.environ,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "STUB_CONFIG": str(config_path),
                "STUB_LOG": str(log_path),
                "CAS_PUSH_RETRY_DELAY": "0",
                "CAS_FETCH_RETRY_DELAY": "0",
                "DOCKER_CONFIG": str(tmp_path / "no-docker-config"),
                "HOME": str(tmp_path),
            }
            return subprocess.run(
                [sys.executable, str(SCRIPT_PATH), *map(str, args)],
                capture_output=True,
                text=True,
                env=env,
            )

        def calls(self, tool=None):
            calls = [json.loads(line) for line in log_path.read_text().splitlines()]
            return [c for c in calls if tool is None or c[0] == tool]

    return Stubs()


# The name of a CAS object is the SHA-256 of its content.
OBJECT = "cas/objects/" + hashlib.sha256(b"object").hexdigest()
OBJECT = OBJECT[:14] + "/" + OBJECT[14:]


def make_cache(root):
    files = {
        OBJECT: "object",
        "artifacts/refs/tromso/core": "ref",
        "sources/git/repo": "source",
        "logs/build.log": "log",
        "cas/staging/partial": "staging",
        "cas/tmp/partial": "tmp",
        "casd.sock": "socket",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def files_under(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def tar_bytes(source):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        tar.add(source, arcname=".")
    return buffer.getvalue()


KEPT = ["artifacts/refs/tromso/core", OBJECT]


# ── reference format ────────────────────────────────────────────────


def test_ref_lowercases_repository():
    assert (
        cas_transport.ref("Tuna-OS/Tromso", "tromso", "", "core", "latest")
        == "ghcr.io/tuna-os/tromso/cache-tromso-core:latest"
    )


def test_ref_appends_arch_suffix_to_the_image_name():
    assert (
        cas_transport.ref("tuna-os/brussels", "brussels", "-aarch64", "chunk1-glib", "f00d")
        == "ghcr.io/tuna-os/brussels/cache-brussels-aarch64-chunk1-glib:f00d"
    )


def test_ref_cli_prints_the_reference(stubs):
    result = stubs.run("ref", "Tuna-OS/Tromso", "tromso", "", "core", "latest")
    assert result.returncode == 0
    assert result.stdout.strip() == REF


# ── exists ──────────────────────────────────────────────────────────


def test_exists_reports_manifest_presence(stubs):
    stubs.config = {"manifests": {REF: {"layers": []}}}
    assert stubs.run("exists", REF).returncode == 0
    assert stubs.run("exists", REF.replace("core", "chunk1")).returncode == 1


# ── restore ───────────────────────────────────────────────────
#
# The manifest still comes from the `oras` stub. The blob comes over HTTP
# from a registry on 127.0.0.1, so these tests run the real resume code.


class Registry:
    """A loopback registry: a token endpoint and blobs with Range support."""

    def __init__(self):
        import http.server
        import threading

        registry = self
        self.blobs = {}
        self.cut_after = None  # serve at most this many bytes per connection
        self.fail_first = 0  # answer this many blob requests with HTTP 502
        self.ranges = []
        self.authorizations = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path.startswith("/token"):
                    registry.authorizations.append(self.headers.get("Authorization"))
                    body = json.dumps({"token": "t"}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                digest = self.path.rsplit("/", 1)[-1]
                data = registry.blobs.get(digest)
                header = self.headers.get("Range")
                registry.ranges.append(header)
                if data is None:
                    self.send_error(404)
                    return
                if registry.fail_first:
                    registry.fail_first -= 1
                    self.send_error(502)
                    return
                start = int(header.removeprefix("bytes=").rstrip("-")) if header else 0
                body = data[start:]
                self.send_response(206 if header else 200)
                # The full length is announced, then the connection is cut short.
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if registry.cut_after is not None:
                    body = body[: registry.cut_after]
                self.wfile.write(body)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        self.ref = f"{self.host}/tuna-os/tromso/cache-tromso-core:latest"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def publish(self, stubs, data):
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        self.blobs[digest] = data
        layer = {"mediaType": cas_transport.MEDIA_TYPE, "digest": digest, "size": len(data)}
        config = {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": "sha256:0", "size": 2}
        stubs.config = {"manifests": {self.ref: {"layers": [config, layer]}}}
        return digest


@pytest.fixture
def registry():
    reg = Registry()
    yield reg
    reg.server.shutdown()


def test_restore_extracts_the_cas_layer_without_excluded_paths(stubs, registry, tmp_path):
    source = tmp_path / "source"
    make_cache(source)
    registry.publish(stubs, tar_bytes(source))
    dest = tmp_path / "dest"

    result = stubs.run("restore", registry.ref, dest)

    assert result.returncode == 0, result.stderr
    assert files_under(dest) == KEPT
    assert registry.ranges == [None]
    assert not [c for c in stubs.calls("oras") if c[1] == "blob"], "the blob must not come through oras"


def test_restore_resumes_after_the_registry_cuts_the_stream(stubs, registry, tmp_path):
    """GHCR cuts large blobs mid-stream; the restore must continue, not fail."""
    source = tmp_path / "source"
    make_cache(source)
    data = tar_bytes(source)
    registry.publish(stubs, data)
    registry.cut_after = 3000
    dest = tmp_path / "dest"

    result = stubs.run("restore", registry.ref, dest)

    assert result.returncode == 0, result.stderr
    assert files_under(dest) == KEPT
    assert len(registry.ranges) > 1
    assert registry.ranges[:2] == [None, "bytes=3000-"]
    assert "complete after" in result.stderr


def test_restore_retries_a_registry_error(stubs, registry, tmp_path):
    source = tmp_path / "source"
    make_cache(source)
    registry.publish(stubs, tar_bytes(source))
    registry.fail_first = 2
    dest = tmp_path / "dest"

    result = stubs.run("restore", registry.ref, dest)

    assert result.returncode == 0, result.stderr
    assert files_under(dest) == KEPT


def test_restore_fails_when_the_stream_is_not_the_manifest_digest(stubs, registry, tmp_path):
    source = tmp_path / "source"
    make_cache(source)
    data = tar_bytes(source)
    digest = registry.publish(stubs, data)
    registry.blobs[digest] = data[:-1] + bytes([data[-1] ^ 1])

    result = stubs.run("restore", registry.ref, tmp_path / "dest")

    assert result.returncode != 0
    assert "the manifest says" in result.stderr


def test_restore_uses_the_login_that_oras_stored(stubs, registry, tmp_path):
    source = tmp_path / "source"
    make_cache(source)
    registry.publish(stubs, tar_bytes(source))
    config_dir = tmp_path / "no-docker-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({"auths": {registry.host: {"auth": "dTpw"}}}))

    assert stubs.run("restore", registry.ref, tmp_path / "dest").returncode == 0
    assert registry.authorizations == ["Basic dTpw"]


def test_restore_without_manifest_is_a_cold_start(stubs, tmp_path):
    dest = tmp_path / "dest"

    result = stubs.run("restore", REF, dest)

    assert result.returncode == 0
    assert "starting fresh" in result.stdout
    assert dest.is_dir()


def test_restore_fails_when_manifest_has_no_cas_layer(stubs, tmp_path):
    stubs.config = {"manifests": {REF: {"layers": [{"mediaType": "other", "digest": DIGEST}]}}}

    result = stubs.run("restore", REF, tmp_path / "dest")

    assert result.returncode != 0
    assert cas_transport.MEDIA_TYPE in result.stderr


def test_restore_fails_when_the_blob_is_missing(stubs, registry, tmp_path, monkeypatch):
    registry.publish(stubs, b"x" * 10)
    registry.blobs.clear()

    result = stubs.run("restore", registry.ref, tmp_path / "dest")

    assert result.returncode != 0
    assert "HTTP 404" in result.stderr
    assert len(registry.ranges) == 1, "a missing blob is not retried"


# ── stop-builders ───────────────────────────────────────────────────


def test_stop_builders_stops_only_containers_of_this_workspace(stubs, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    stubs.config = {
        "ps": ["mine", "peer", "gone"],
        "mounts": {"mine": str(workspace), "peer": str(tmp_path / "other")},
        "exists_rc": {"gone": 1},
    }

    result = stubs.run("stop-builders", "bst2:pin", workspace)

    assert result.returncode == 0, result.stderr
    stopped = [c[-1] for c in stubs.calls("podman") if c[1] == "stop"]
    assert stopped == ["mine"]


def test_stop_builders_fails_when_a_builder_cannot_be_inspected(stubs, tmp_path):
    stubs.config = {"ps": ["broken"], "exists_rc": {"broken": 125}}

    result = stubs.run("stop-builders", "bst2:pin", tmp_path)

    assert result.returncode != 0


# ── archive ─────────────────────────────────────────────────────────


def test_archive_omits_excluded_paths(stubs, tmp_path):
    cache = tmp_path / "cache"
    make_cache(cache)
    out = tmp_path / "out"
    out.mkdir()

    result = stubs.run("archive", "bst2:pin", cache, out, "cas-core.tar.zst")

    assert result.returncode == 0, result.stderr
    with tarfile.open(out / "cas-core.tar.zst") as tar:
        members = sorted(m.name.removeprefix("./") for m in tar.getmembers() if m.isfile())
    assert members == KEPT


def test_archive_round_trips_through_restore(stubs, registry, tmp_path):
    cache = tmp_path / "cache"
    make_cache(cache)
    out = tmp_path / "out"
    out.mkdir()
    assert stubs.run("archive", "bst2:pin", cache, out, "cas.tar.zst").returncode == 0
    registry.publish(stubs, (out / "cas.tar.zst").read_bytes())

    assert stubs.run("restore", registry.ref, tmp_path / "dest").returncode == 0
    assert files_under(tmp_path / "dest") == KEPT


def test_archive_failure_without_reserve_is_an_error(stubs, tmp_path):
    stubs.config = {"run_rc": 2}
    (tmp_path / "cas.tar.zst").write_text("partial")

    result = stubs.run("archive", "bst2:pin", tmp_path, tmp_path, "cas.tar.zst")

    assert result.returncode != 0
    assert not (tmp_path / "cas.tar.zst").exists()


def test_archive_failure_with_reserve_warns_and_removes_partial_file(stubs, tmp_path):
    stubs.config = {"run_rc": 141}
    (tmp_path / "cas.tar.zst").write_text("partial")

    result = stubs.run("archive", "bst2:pin", tmp_path, tmp_path, "cas.tar.zst", "--reserve-bytes", "1")

    assert result.returncode == 1
    assert "::warning::CAS archive failed" in result.stdout
    assert not (tmp_path / "cas.tar.zst").exists()


def test_archive_skips_when_free_space_is_below_reserve(stubs, tmp_path):
    huge = 1 << 62

    result = stubs.run("archive", "bst2:pin", tmp_path, tmp_path, "cas.tar.zst", "--reserve-bytes", huge)

    assert result.returncode == 1
    assert "skipping the CAS archive" in result.stdout
    assert not [c for c in stubs.calls("podman") if c[1] == "run"]


def test_archive_with_reserve_caps_the_archive_size(stubs, tmp_path):
    cache = tmp_path / "cache"
    make_cache(cache)

    result = stubs.run("archive", "bst2:pin", cache, tmp_path, "cas.tar.zst", "--reserve-bytes", "1")

    assert result.returncode == 0, result.stderr
    run = next(c for c in stubs.calls("podman") if c[1] == "run")
    assert " | head -c " in run[-1]


# ── push ────────────────────────────────────────────────────────────


def test_push_sends_the_file_as_the_cas_layer(stubs, tmp_path):
    result = stubs.run("push", REF, "cas-core.tar.zst")

    assert result.returncode == 0
    assert stubs.calls("oras") == [["oras", "push", REF, f"cas-core.tar.zst:{cas_transport.MEDIA_TYPE}"]]


def test_push_failure_is_an_error_without_best_effort(stubs):
    stubs.config = {"push_rcs": [1]}

    result = stubs.run("push", REF, "cas.tar.zst")

    assert result.returncode != 0
    assert len(stubs.calls("oras")) == 1


def test_best_effort_push_retries_then_succeeds(stubs):
    stubs.config = {"push_rcs": [1, 0]}

    result = stubs.run("push", REF, "cas.tar.zst", "--best-effort")

    assert result.returncode == 0
    assert len(stubs.calls("oras")) == 2
    assert "::warning::" not in result.stdout


def test_best_effort_push_warns_after_three_failures(stubs):
    stubs.config = {"push_rcs": [1, 1, 1]}

    result = stubs.run("push", REF, "cas.tar.zst", "--best-effort")

    assert result.returncode == 0
    assert len(stubs.calls("oras")) == 3
    assert f"::warning::cache push to {REF} failed after 3 attempts" in result.stdout
