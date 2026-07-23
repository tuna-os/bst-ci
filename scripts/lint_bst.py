#!/usr/bin/env python3
"""Static lint for BuildStream .bst element files.

No BuildStream/network required. Two kinds of checks:

1. Structural: valid YAML, `kind:` present and one of a known set.

2. Cross-reference: every `depends:`/`build-depends:`/`runtime-depends:`
   entry that names a junction element (contains a `:`, e.g.
   `freedesktop-sdk.bst:components/foo.bst`) is checked against a corpus
   built from every other .bst file under the given root(s). A junction
   dependency referenced ONLY by files passed via --check-new (nowhere
   else in the corpus) is flagged as unconfirmed — it may not actually
   exist in the junctioned project; this script has no way to check that,
   only whether this codebase has ever successfully referenced it before.

Usage:
    lint_bst.py <elements-root> [<elements-root> ...]
    lint_bst.py <elements-root> --check-new <file.bst> [<file.bst> ...]

Exit status: 0 if no errors (unconfirmed-dependency warnings don't fail by
default; pass --strict to make them fatal).
"""
import argparse
import sys
from pathlib import Path

import yaml

KNOWN_KINDS = {
    "meson", "cmake", "autotools", "manual", "make", "script", "pyproject",
    "cargo", "import", "stack", "compose", "filter", "junction",
    "collect_initial_scripts", "collect_manifest", "pip", "distutils",
    "qmake", "modulebuild", "x86image", "flatpak_image",
}

DEPENDS_KEYS = {"depends", "build-depends", "runtime-depends"}


def find_bst_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.bst"))


def load_yaml(path: Path):
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        return e


def extract_junction_deps(doc: dict) -> set[str]:
    deps = set()
    for key in DEPENDS_KEYS:
        for entry in doc.get(key, []) or []:
            name = entry if isinstance(entry, str) else entry.get("filename")
            if name and ":" in name:
                deps.add(name)
    return deps


def lint_file(path: Path, doc, errors: list, warnings: list):
    if isinstance(doc, Exception):
        errors.append(f"{path}: invalid YAML — {doc}")
        return
    if not isinstance(doc, dict):
        errors.append(f"{path}: top level is not a mapping")
        return

    kind = doc.get("kind")
    if kind is None:
        errors.append(f"{path}: missing `kind:`")
    elif kind not in KNOWN_KINDS:
        warnings.append(
            f"{path}: kind '{kind}' not in the known-kinds list — "
            "new BuildStream plugin, or a typo?"
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("roots", nargs="+", type=Path)
    ap.add_argument("--check-new", nargs="*", type=Path, default=[],
                     help="Files to report unconfirmed-dependency warnings for")
    ap.add_argument("--strict", action="store_true",
                     help="Treat unconfirmed-dependency warnings as errors")
    args = ap.parse_args()

    all_files: list[Path] = []
    for root in args.roots:
        all_files.extend(find_bst_files(root))

    if not all_files:
        print("No .bst files found under the given root(s)", file=sys.stderr)
        return 1

    docs = {f: load_yaml(f) for f in all_files}

    errors: list[str] = []
    warnings: list[str] = []
    for f, doc in docs.items():
        lint_file(f, doc, errors, warnings)

    # Corpus of junction deps seen anywhere, mapped to the files that use them.
    dep_users: dict[str, set[Path]] = {}
    for f, doc in docs.items():
        if isinstance(doc, dict):
            for dep in extract_junction_deps(doc):
                dep_users.setdefault(dep, set()).add(f)

    check_new = set(args.check_new)
    unconfirmed: list[str] = []
    if check_new:
        for f in check_new:
            doc = docs.get(f)
            if not isinstance(doc, dict):
                continue
            for dep in extract_junction_deps(doc):
                users = dep_users.get(dep, set())
                if users <= check_new:
                    unconfirmed.append(
                        f"{f}: '{dep}' is not referenced anywhere else in "
                        "this tree — unconfirmed it actually exists upstream"
                    )

    for e in errors:
        print(f"ERROR: {e}")
    for w in warnings:
        print(f"WARNING: {w}")
    for u in unconfirmed:
        print(f"{'ERROR' if args.strict else 'WARNING'}: {u}")

    print(f"\n{len(all_files)} files checked, {len(errors)} errors, "
          f"{len(warnings)} warnings, {len(unconfirmed)} unconfirmed dependencies")

    if errors or (args.strict and unconfirmed):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
