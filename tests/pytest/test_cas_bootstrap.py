"""Tests for scripts/cas_bootstrap.py.

Offline: the registry is replaced by fake `fetch_manifest` and `opener`
functions, and the archives are small tar files. The extraction test needs
real `zstd` and `tar` and is skipped without them.
"""

import argparse
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.error
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("cas_bootstrap", SCRIPTS / "cas_bootstrap.py")
cas_bootstrap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cas_bootstrap)

REF = "ghcr.io/tuna-os/tromso/cache-tromso-core:latest"
MEDIA_TYPE = "application/vnd.buildstream.cas.tar.zst"


def sha256(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def manifest_for(data, created="2026-11-24T10:32:14Z"):
    return {
        "layers": [{"mediaType": MEDIA_TYPE, "digest": sha256(data), "size": len(data)}],
        "annotations": {"org.opencontainers.image.created": created},
    }


class FakeResponse(io.BytesIO):
    def __init__(self, data, status):
        super().__init__(data)
        self.status = status


def fake_registry(data, cut_after=None, ignore_range=False):
    """An opener that serves `data`, honours Range, and can cut each response."""
    requests = []

    def opener(request, timeout=None):
        start = 0
        header = request.get_header("Range")
        requests.append(header)
        if header and not ignore_range:
            start = int(header.removeprefix("bytes=").rstrip("-"))
        body = data[start:]
        if cut_after is not None:
            body = body[:cut_after]
        return FakeResponse(body, 206 if header and not ignore_range else 200)

    opener.requests = requests
    return opener


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(cas_bootstrap, "pull_token", lambda *a, **k: "token")


def pull_args(**overrides):
    values = {"auth_file": None, "keep_archives": False, "reserve_gib": 0}
    values.update(overrides)
    return argparse.Namespace(**values)


def test_split_ref():
    assert cas_bootstrap.split_ref(REF) == ("ghcr.io", "tuna-os/tromso/cache-tromso-core", "latest")


def test_stage_refs_use_the_transport_reference_format():
    args = argparse.Namespace(
        repository="Tuna-OS/Brussels", image_name="brussels", arch_suffix="-aarch64", tag="latest", stage=[]
    )
    assert cas_bootstrap.stage_refs(args) == [
        ("core", "ghcr.io/tuna-os/brussels/cache-brussels-aarch64-core:latest")
    ]


def test_cas_layer_needs_the_cas_media_type():
    assert cas_bootstrap.cas_layer(manifest_for(b"abc")) == (sha256(b"abc"), 3)
    with pytest.raises(SystemExit):
        cas_bootstrap.cas_layer({"layers": [{"mediaType": "application/x-other", "digest": "x", "size": 1}]})


def test_download_verifies_the_digest(tmp_path):
    data = b"cas-archive-bytes" * 100
    target = tmp_path / "blob"
    cas_bootstrap.download(REF, sha256(data), len(data), target, opener=fake_registry(data))
    assert target.read_bytes() == data
    assert not Path(f"{target}.part").exists()


def test_download_resumes_a_partial_file(tmp_path):
    data = bytes(range(256)) * 40
    target = tmp_path / "blob"
    Path(f"{target}.part").write_bytes(data[:1000])
    opener = fake_registry(data)
    cas_bootstrap.download(REF, sha256(data), len(data), target, opener=opener)
    assert target.read_bytes() == data
    assert opener.requests == ["bytes=1000-"]


def test_download_continues_after_cut_connections(tmp_path):
    data = bytes(range(256)) * 40
    target = tmp_path / "blob"
    opener = fake_registry(data, cut_after=3000)
    cas_bootstrap.download(REF, sha256(data), len(data), target, opener=opener, pause=lambda s: None)
    assert target.read_bytes() == data
    assert opener.requests[:3] == [None, "bytes=3000-", "bytes=6000-"]


def test_download_retries_http_errors(tmp_path):
    data = b"x" * 5000
    good = fake_registry(data)
    calls = []

    def opener(request, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 502, "bad gateway", {}, None)
        return good(request)

    target = tmp_path / "blob"
    cas_bootstrap.download(REF, sha256(data), len(data), target, opener=opener, pause=lambda s: None)
    assert target.read_bytes() == data


def test_download_rejects_a_wrong_digest_and_removes_the_file(tmp_path):
    data = b"tampered" * 10
    target = tmp_path / "blob"
    with pytest.raises(SystemExit, match="digest mismatch"):
        cas_bootstrap.download(REF, sha256(b"expected"), len(data), target, opener=fake_registry(data))
    assert not target.exists()
    assert not Path(f"{target}.part").exists()


def test_download_refuses_a_server_that_ignores_range(tmp_path):
    data = b"y" * 4000
    target = tmp_path / "blob"
    Path(f"{target}.part").write_bytes(data[:100])
    with pytest.raises(SystemExit, match="ignored Range"):
        cas_bootstrap.download(
            REF, sha256(data), len(data), target, opener=fake_registry(data, ignore_range=True)
        )


def make_archive(tmp_path):
    """A zstd tar of a tiny cache tree, with one path the filter must drop."""
    tree = tmp_path / "tree"
    (tree / "cas/objects/ab").mkdir(parents=True)
    (tree / "cas/objects/ab/cdef").write_text("blob")
    (tree / "artifacts/refs/tromso/x").mkdir(parents=True)
    (tree / "artifacts/refs/tromso/x/key").write_text("ref")
    (tree / "sources").mkdir()
    (tree / "sources/big").write_text("not wanted")
    plain = tmp_path / "cas.tar"
    with tarfile.open(plain, "w") as tar:
        tar.add(tree, arcname=".")
    packed = tmp_path / "cas.tar.zst"
    subprocess.run(["zstd", "-q", "-f", str(plain), "-o", str(packed)], check=True)
    return packed.read_bytes()


needs_zstd = pytest.mark.skipif(
    not (shutil.which("zstd") and shutil.which("tar")), reason="needs zstd and tar"
)


@needs_zstd
def test_pull_stage_seeds_then_skips(tmp_path, monkeypatch):
    data = make_archive(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    downloads = []

    def fake_download(reference, digest, size, target, auth_file=None):
        downloads.append(reference)
        Path(target).write_bytes(data)
        return 1.0

    monkeypatch.setattr(cas_bootstrap, "fetch_manifest", lambda ref, auth=None: manifest_for(data))
    monkeypatch.setattr(cas_bootstrap, "download", fake_download)

    row = cas_bootstrap.pull_stage(REF, "core", cache, pull_args())
    assert row["status"].startswith("seeded")
    assert (cache / "cas/objects/ab/cdef").read_text() == "blob"
    assert (cache / "artifacts/refs/tromso/x/key").read_text() == "ref"
    assert not (cache / "sources").exists(), "the transport filter must apply"
    stamp = json.loads((cache / ".cas-bootstrap/core.json").read_text())
    assert stamp["digest"] == sha256(data)
    assert stamp["ref"] == REF
    assert not list((cache / ".cas-bootstrap").glob("*.tar.zst")), "archive is removed by default"

    row = cas_bootstrap.pull_stage(REF, "core", cache, pull_args())
    assert row["status"] == "already seeded"
    assert downloads == [REF], "a seeded digest must not be downloaded again"


@needs_zstd
def test_pull_stage_reseeds_when_the_published_digest_changes(tmp_path, monkeypatch):
    data = make_archive(tmp_path)
    cache = tmp_path / "cache"
    (cache / ".cas-bootstrap").mkdir(parents=True)
    (cache / ".cas-bootstrap/core.json").write_text(json.dumps({"digest": "sha256:old"}))
    monkeypatch.setattr(cas_bootstrap, "fetch_manifest", lambda ref, auth=None: manifest_for(data))
    monkeypatch.setattr(
        cas_bootstrap, "download", lambda ref, digest, size, target, auth=None: Path(target).write_bytes(data)
    )
    row = cas_bootstrap.pull_stage(REF, "core", cache, pull_args(keep_archives=True))
    assert row["status"].startswith("seeded")
    assert len(list((cache / ".cas-bootstrap").glob("*.tar.zst"))) == 1


def test_pull_stage_refuses_when_the_disk_is_too_small(tmp_path, monkeypatch):
    data = b"z" * 100
    monkeypatch.setattr(cas_bootstrap, "fetch_manifest", lambda ref, auth=None: manifest_for(data))
    monkeypatch.setattr(
        cas_bootstrap.shutil, "disk_usage", lambda path: argparse.Namespace(free=50, total=100, used=50)
    )
    with pytest.raises(SystemExit, match="free in"):
        cas_bootstrap.pull_stage(REF, "core", tmp_path, pull_args())


def test_pull_stage_explains_a_missing_or_private_package(tmp_path, monkeypatch):
    monkeypatch.setattr(cas_bootstrap, "fetch_manifest", lambda ref, auth=None: None)
    with pytest.raises(SystemExit, match="read:packages"):
        cas_bootstrap.pull_stage(REF, "core", tmp_path, pull_args())


def test_count_states_ignores_log_noise():
    lines = [
        "[--:--:--] START   Loading elements",
        "core/a.bst||cached",
        "core/b.bst||buildable",
        "freedesktop-sdk.bst:components/c.bst||waiting",
        "core/d.bst||cached",
        "",
    ]
    assert cas_bootstrap.count_states(lines) == {"cached": 2, "buildable": 1, "waiting": 1}


def test_states_command_prints_the_share(tmp_path, capsys):
    report = tmp_path / "show.txt"
    report.write_text("a.bst||cached\nb.bst||cached\nc.bst||cached\nd.bst||buildable\n")
    assert cas_bootstrap.main(["states", str(report)]) == 0
    assert "3 of 4 elements are in the local cache (75%), 1 to build" in capsys.readouterr().out


def test_the_script_has_no_push_path():
    """A developer machine must never write to the shared cache."""
    source = (SCRIPTS / "cas_bootstrap.py").read_text()
    assert "cas_transport.push" not in source
    assert "cas_transport.archive" not in source
    assert '"oras"' not in source
    assert source.count("scope=repository:") == 1
    assert "scope=repository:{name}:pull" in source
    with pytest.raises(SystemExit):
        cas_bootstrap.main(["push", "x"])
