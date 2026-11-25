"""cas_untar.py writes an object only when its content matches its name."""

import hashlib
import io
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import cas_untar  # noqa: E402

GOOD = b"x" * 2000


def name_of(data):
    digest = hashlib.sha256(data).hexdigest()
    return f"cas/objects/{digest[:2]}/{digest[2:]}"


def stream(*files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in files:
            info = tarfile.TarInfo("./" + name)
            info.size, info.mtime, info.mode = len(data), 1700000000, 0o444
            tar.addfile(info, io.BytesIO(data))
    return io.BytesIO(buffer.getvalue())


def test_writes_a_good_object_with_its_mode_and_time(tmp_path):
    assert cas_untar.extract(stream((name_of(GOOD), GOOD)), tmp_path) == (1, 0)
    path = tmp_path / name_of(GOOD)
    assert path.read_bytes() == GOOD
    assert path.stat().st_mode & 0o777 == 0o444
    assert path.stat().st_mtime == 1700000000


def test_drops_a_truncated_object(tmp_path, capsys):
    other = b"other"
    source = stream((name_of(GOOD), GOOD[:512]), (name_of(other), other))
    assert cas_untar.extract(source, tmp_path) == (1, 1)
    assert not (tmp_path / name_of(GOOD)).exists()
    assert (tmp_path / name_of(other)).read_bytes() == other
    assert "::warning::dropped CAS object" in capsys.readouterr().out


def test_a_bad_copy_does_not_replace_a_good_object(tmp_path):
    cas_untar.extract(stream((name_of(GOOD), GOOD)), tmp_path)
    assert cas_untar.extract(stream((name_of(GOOD), GOOD[:512])), tmp_path) == (0, 1)
    assert (tmp_path / name_of(GOOD)).read_bytes() == GOOD


def test_a_good_copy_replaces_a_short_object(tmp_path):
    path = tmp_path / name_of(GOOD)
    path.parent.mkdir(parents=True)
    path.write_bytes(GOOD[:512])
    assert cas_untar.extract(stream((name_of(GOOD), GOOD)), tmp_path) == (1, 0)
    assert path.read_bytes() == GOOD


def test_a_stream_that_stops_leaves_no_short_object(tmp_path):
    cut = io.BytesIO(stream((name_of(GOOD), GOOD)).getvalue()[:1024])
    with pytest.raises(tarfile.ReadError):
        cas_untar.extract(cut, tmp_path)
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


def test_replaces_a_read_only_reference_and_refuses_to_leave_the_cache(tmp_path):
    cas_untar.extract(stream(("artifacts/refs/a", b"old")), tmp_path)
    cas_untar.extract(stream(("artifacts/refs/a", b"new")), tmp_path)
    assert (tmp_path / "artifacts/refs/a").read_bytes() == b"new"
    with pytest.raises(tarfile.FilterError):
        cas_untar.extract(stream(("../outside", b"x")), tmp_path / "cache")
