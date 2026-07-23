"""Unit tests for scripts/lint_bst.py, using synthetic element trees
(no real BuildStream project needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import lint_bst  # noqa: E402


def write(root: Path, relpath: str, content: str) -> Path:
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_valid_element_no_findings(tmp_path):
    write(tmp_path, "foo.bst", "kind: manual\nsources: []\n")
    files = lint_bst.find_bst_files(tmp_path)
    docs = {f: lint_bst.load_yaml(f) for f in files}
    errors, warnings = [], []
    for f, doc in docs.items():
        lint_bst.lint_file(f, doc, errors, warnings)
    assert errors == []
    assert warnings == []


def test_invalid_yaml_is_an_error(tmp_path):
    write(tmp_path, "bad.bst", "kind: manual\n  bad indent: [\n")
    files = lint_bst.find_bst_files(tmp_path)
    docs = {f: lint_bst.load_yaml(f) for f in files}
    errors, warnings = [], []
    for f, doc in docs.items():
        lint_bst.lint_file(f, doc, errors, warnings)
    assert len(errors) == 1
    assert "invalid YAML" in errors[0]


def test_missing_kind_is_an_error(tmp_path):
    write(tmp_path, "nokind.bst", "sources: []\n")
    files = lint_bst.find_bst_files(tmp_path)
    docs = {f: lint_bst.load_yaml(f) for f in files}
    errors, warnings = [], []
    for f, doc in docs.items():
        lint_bst.lint_file(f, doc, errors, warnings)
    assert any("missing `kind:`" in e for e in errors)


def test_unknown_kind_is_a_warning(tmp_path):
    write(tmp_path, "weird.bst", "kind: totally-not-a-real-kind\nsources: []\n")
    files = lint_bst.find_bst_files(tmp_path)
    docs = {f: lint_bst.load_yaml(f) for f in files}
    errors, warnings = [], []
    for f, doc in docs.items():
        lint_bst.lint_file(f, doc, errors, warnings)
    assert errors == []
    assert any("not in the known-kinds list" in w for w in warnings)


def test_dependency_used_elsewhere_is_not_flagged(tmp_path):
    write(tmp_path, "existing.bst", "kind: manual\ndepends:\n- freedesktop-sdk.bst:components/gtk4.bst\n")
    new_file = write(tmp_path, "new.bst", "kind: manual\ndepends:\n- freedesktop-sdk.bst:components/gtk4.bst\n")

    files = lint_bst.find_bst_files(tmp_path)
    docs = {f: lint_bst.load_yaml(f) for f in files}
    dep_users = {}
    for f, doc in docs.items():
        for dep in lint_bst.extract_junction_deps(doc):
            dep_users.setdefault(dep, set()).add(f)

    check_new = {new_file}
    unconfirmed = []
    for f in check_new:
        for dep in lint_bst.extract_junction_deps(docs[f]):
            if dep_users.get(dep, set()) <= check_new:
                unconfirmed.append(dep)
    assert unconfirmed == []


def test_dependency_used_only_by_new_file_is_flagged(tmp_path):
    new_file = write(tmp_path, "new.bst", "kind: manual\ndepends:\n- freedesktop-sdk.bst:components/never-seen.bst\n")

    files = lint_bst.find_bst_files(tmp_path)
    docs = {f: lint_bst.load_yaml(f) for f in files}
    dep_users = {}
    for f, doc in docs.items():
        for dep in lint_bst.extract_junction_deps(doc):
            dep_users.setdefault(dep, set()).add(f)

    check_new = {new_file}
    unconfirmed = []
    for f in check_new:
        for dep in lint_bst.extract_junction_deps(docs[f]):
            if dep_users.get(dep, set()) <= check_new:
                unconfirmed.append(dep)
    assert unconfirmed == ["freedesktop-sdk.bst:components/never-seen.bst"]


def test_local_dependency_names_are_ignored(tmp_path):
    # No ':' in the name means it's a same-project element, not a junction
    # reference — nothing to cross-check against an external project.
    write(tmp_path, "local.bst", "kind: manual\ndepends:\n- xfce-linux/deps.bst\n")
    files = lint_bst.find_bst_files(tmp_path)
    docs = {f: lint_bst.load_yaml(f) for f in files}
    deps = lint_bst.extract_junction_deps(docs[files[0]])
    assert deps == set()


def test_main_end_to_end_exit_code(tmp_path, capsys):
    write(tmp_path, "existing.bst", "kind: manual\ndepends:\n- freedesktop-sdk.bst:components/gtk4.bst\n")
    new_file = write(tmp_path, "new.bst", "kind: manual\ndepends:\n- freedesktop-sdk.bst:components/mystery.bst\n")

    # main() parses sys.argv directly, so drive it as a subprocess.
    import subprocess
    script = Path(__file__).resolve().parents[2] / "scripts" / "lint_bst.py"
    result = subprocess.run(
        [sys.executable, str(script), str(tmp_path), "--check-new", str(new_file)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0  # unconfirmed warnings don't fail by default
    assert "mystery.bst" in result.stdout

    result_strict = subprocess.run(
        [sys.executable, str(script), str(tmp_path), "--check-new", str(new_file), "--strict"],
        capture_output=True, text=True,
    )
    assert result_strict.returncode == 1
