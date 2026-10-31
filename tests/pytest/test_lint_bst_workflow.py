"""Contract tests for the reusable .github/workflows/lint-bst.yml.

The lint step's shell runs against a throwaway git repository, so the
changed-file selection and strictness are exercised as consumers see them."""
import os
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github/workflows/lint-bst.yml"
LINT_BST = REPO / "scripts/lint_bst.py"


def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def steps():
    return workflow()["jobs"]["lint-bst"]["steps"]


def named_step(name):
    return next(step for step in steps() if step.get("name") == name)


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def commit(repo, files, message):
    for relpath, content in files.items():
        p = repo / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
        "commit", "-q", "-m", message)
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                         capture_output=True, text=True)
    return out.stdout.strip()


def run_lint(repo, base_sha="", roots="elements", strict="false"):
    env = {
        **os.environ,
        "ELEMENTS_ROOTS": roots,
        "STRICT": strict,
        "BASE_SHA": base_sha,
        "LINT_BST": str(LINT_BST),
    }
    return subprocess.run(["bash", "-c", named_step("Lint .bst files")["run"]],
                          cwd=repo, env=env, capture_output=True, text=True)


def base_repo(tmp_path):
    git(tmp_path, "init", "-q")
    base = commit(tmp_path, {
        "elements/existing.bst":
            "kind: manual\ndepends:\n- freedesktop-sdk.bst:components/known.bst\n",
    }, "base")
    return tmp_path, base


NEW_DEP = "kind: manual\ndepends:\n- freedesktop-sdk.bst:components/novel.bst\n"


def test_public_inputs():
    inputs = workflow()[True]["workflow_call"]["inputs"]
    assert set(inputs) == {"elements_roots", "strict"}
    assert inputs["elements_roots"]["default"] == "elements"
    assert inputs["strict"]["type"] == "boolean"
    assert inputs["strict"]["default"] is False


def test_permissions_are_read_only():
    assert workflow()["permissions"] == {"contents": "read"}


def test_linter_checkout_uses_called_workflow_sha():
    checkout = named_step("Checkout bst-ci scripts")
    assert checkout["with"]["repository"] == "tuna-os/bst-ci"
    assert checkout["with"]["ref"] == "${{ job.workflow_sha }}"


def test_pull_request_reports_unconfirmed_dep_in_changed_file(tmp_path):
    repo, base = base_repo(tmp_path)
    commit(repo, {"elements/new.bst": NEW_DEP}, "add new element")
    result = run_lint(repo, base_sha=base)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "elements/new.bst" in result.stdout
    assert "WARNING: elements/new.bst: 'freedesktop-sdk.bst:components/novel.bst'" in result.stdout


def test_strict_makes_unconfirmed_dep_fatal(tmp_path):
    repo, base = base_repo(tmp_path)
    commit(repo, {"elements/new.bst": NEW_DEP}, "add new element")
    result = run_lint(repo, base_sha=base, strict="true")
    assert result.returncode == 1
    assert "ERROR: elements/new.bst" in result.stdout


def test_changes_outside_roots_are_ignored(tmp_path):
    repo, base = base_repo(tmp_path)
    commit(repo, {"other/new.bst": NEW_DEP}, "add element outside roots")
    result = run_lint(repo, base_sha=base, strict="true")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No .bst files changed" in result.stdout


def test_dot_slash_root_matches_changed_paths(tmp_path):
    repo, base = base_repo(tmp_path)
    commit(repo, {"elements/new.bst": NEW_DEP}, "add new element")
    result = run_lint(repo, base_sha=base, roots="./elements/", strict="true")
    assert result.returncode == 1
    assert "ERROR: elements/new.bst" in result.stdout


def test_without_base_runs_structural_checks_only(tmp_path):
    repo, _ = base_repo(tmp_path)
    commit(repo, {"elements/new.bst": NEW_DEP}, "add new element")
    result = run_lint(repo, strict="true")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "structural checks only" in result.stdout
    assert "0 unconfirmed dependencies" in result.stdout


def test_structural_error_fails_without_base(tmp_path):
    repo, _ = base_repo(tmp_path)
    commit(repo, {"elements/broken.bst": "sources: []\n"}, "missing kind")
    result = run_lint(repo)
    assert result.returncode == 1
    assert "ERROR" in result.stdout


def test_empty_roots_fail(tmp_path):
    repo, _ = base_repo(tmp_path)
    result = run_lint(repo, roots="  ")
    assert result.returncode == 1
    assert "elements_roots is empty" in result.stdout
