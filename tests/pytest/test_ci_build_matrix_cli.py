"""End-to-end CLI tests for scripts/ci-build-matrix.py.

Unlike test_ci_build_matrix.py (unit tests for the pure functions),
this drives the script as a subprocess against a synthetic build-plan.txt
-- no BuildStream, podman, or bst2 container required. Catches breakage
in argument parsing, the build-plan.txt lookup, and the final JSON shape
that the unit tests alone wouldn't.
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "ci-build-matrix.py"


def run_matrix(tmp_path, plan_lines, target, num_chunks, core_split):
    plan_file = tmp_path / "build-plan.txt"
    plan_file.write_text("\n".join(plan_lines) + "\n" if plan_lines else "")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), target, str(num_chunks), str(core_split)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_full_pipeline_splits_core_and_chunks(tmp_path):
    data = run_matrix(
        tmp_path,
        [
            "core/glibc.bst||wait||key1",
            "core/systemd.bst||wait||key2",
            "leaf/a.bst||wait||key3",
            "leaf/b.bst||wait||key4",
            "leaf/c.bst||wait||key5",
            "target.bst||wait||key6",
        ],
        target="target.bst",
        num_chunks=3,
        core_split=2,
    )
    assert data["core"] == "core/glibc.bst core/systemd.bst"
    assert data["final"] == "target.bst"
    # target.bst must never appear in a chunk -- build_final builds it
    # directly and shouldn't need to archive/restore a chunk CAS for it.
    all_chunk_targets = " ".join(data["matrix"].values())
    assert "target.bst" not in all_chunk_targets
    assert len(data["matrix"]) == 3
    assert set(data["cache_keys"].keys()) == set(data["matrix"].keys())


def test_nothing_to_build_emits_empty_matrix(tmp_path):
    data = run_matrix(
        tmp_path,
        ["target.bst||cached||key1"],
        target="target.bst",
        num_chunks=5,
        core_split=2,
    )
    assert data == {"core": "", "matrix": {}, "cache_keys": {}, "final": "target.bst"}


def test_fewer_leaf_elements_than_chunks_shrinks_matrix(tmp_path):
    # chunk_list() caps chunk count at len(leaf_elements) -- verify the
    # CLI path actually exercises that, not just the unit-tested function.
    data = run_matrix(
        tmp_path,
        [
            "core/a.bst||wait||key1",
            "leaf/x.bst||wait||key2",
        ],
        target="target.bst",
        num_chunks=10,
        core_split=1,
    )
    assert len(data["matrix"]) == 1
