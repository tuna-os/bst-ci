"""Tests for the untested paths of scripts/ci-build-matrix.py.

Covers the `bst show` subprocess branch of get_build_plan() (the
build-plan.txt fast path is already tested), arch passthrough via the
BST_ARCH env var, subprocess failure handling, and the CLI usage error
path — closing the remaining coverage gap in the script.
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = str(Path(__file__).resolve().parent.parent.parent / "scripts" / "ci-build-matrix.py")
spec = importlib.util.spec_from_file_location("ci_build_matrix_extra", SCRIPT_PATH)
ci_build_matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_build_matrix)

get_build_plan = ci_build_matrix.get_build_plan


class TestGetBuildPlanBstSubprocess:
    """get_build_plan() when no pre-generated build-plan.txt exists."""

    def test_invokes_bst_show_and_parses_output(self, monkeypatch):
        captured = {}

        def fake_run(cmd, capture_output, text, check):
            captured["cmd"] = cmd
            assert capture_output is True
            assert text is True
            assert check is True
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="core/a.bst||wait||keyA\ncore/b.bst||cached||keyB\ncore/c.bst||wait||keyC\n",
                stderr="",
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        elements = get_build_plan("target.bst")
        # bst show invocation shape, no arch by default
        assert captured["cmd"] == [
            "bst",
            "show",
            "--deps", "all",
            "--order", "stage",
            "--format", "%{name}||%{state}||%{full-key}",
            "target.bst",
        ]
        # cached elements dropped
        assert [e["name"] for e in elements] == ["core/a.bst", "core/c.bst"]

    def test_arch_passthrough_from_env(self, monkeypatch):
        captured = {}

        def fake_run(cmd, capture_output, text, check):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        get_build_plan("target.bst", arch="aarch64")
        assert captured["cmd"][:3] == ["bst", "-o", "arch"]
        assert captured["cmd"][3] == "aarch64"

    def test_subprocess_failure_propagates(self, monkeypatch):
        import pytest

        def fake_run(cmd, capture_output, text, check):
            raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(subprocess.CalledProcessError):
            get_build_plan("target.bst")

    def test_missing_plan_file_falls_back_to_bst(self, monkeypatch):
        captured = []

        def fake_run(cmd, capture_output, text, check):
            captured.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        get_build_plan("target.bst", plan_file="/nonexistent/build-plan.txt")
        assert captured, "should have fallen back to invoking bst"

    def test_plan_file_preferred_over_bst(self, monkeypatch, tmp_path):
        plan = tmp_path / "plan.txt"
        plan.write_text("only.bst||wait||k\n")

        def fake_run(cmd, capture_output, text, check):
            raise AssertionError("bst must not run when plan_file exists")

        monkeypatch.setattr(subprocess, "run", fake_run)
        elements = get_build_plan("target.bst", plan_file=str(plan))
        assert [e["name"] for e in elements] == ["only.bst"]


class TestCliUsageError:
    """CLI invocation with insufficient arguments."""

    def test_usage_error_exits_nonzero(self):
        result = subprocess.run(
            [sys.executable, SCRIPT_PATH, "target.bst"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "Usage:" in result.stderr

    def test_non_numeric_chunks_rejected(self):
        result = subprocess.run(
            [sys.executable, SCRIPT_PATH, "target.bst", "notanumber"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
