# AGENTS.md — agent guide for tuna-os/bst-ci

Shared **reusable GitHub Actions workflows** for the BuildStream desktop-image
repos — currently [`tromso`](https://github.com/tuna-os/tromso) and
[`xfce-linux`](https://github.com/tuna-os/xfce-linux), and open to any other
BuildStream desktop-image repo in or out of the org.

Human docs: [`README.md`](README.md) (usage, inputs, chunking rationale),
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## This repo has no product — its consumers are the product

Nothing here builds an image. It publishes an interface that other repos call:

```yaml
jobs:
  multirunner:
    uses: tuna-os/bst-ci/.github/workflows/multirunner-build.yml@main
    with:
      image_name: your-image
      bst_target: oci/your-image.bst
      num_chunks: '10'      # optional
      core_split: '200'     # optional
```

That makes the `workflow_call` input block in
`.github/workflows/multirunner-build.yml` a **public API**. Renaming an input,
tightening a default, or changing what a step emits breaks tromso and
xfce-linux at their next run, and they pin `@main` — so a breaking change is
live immediately, with no version to hold them back. Treat those two repos as
the compatibility contract and check them before changing the interface.

## Why it exists

The multi-runner chunked-build pipeline — plan → core → parallel dependency
chunks, sharing CAS state via GHCR-hosted zstd tarballs — was identical in
every desktop repo except image name, target and chunk count, and was being
hand-copied. Every CI fix had to be applied twice and it was easy to forget
one. Consolidating it here is the whole point, which is why:

> **Consumers must not carry their own copy of `scripts/ci-build-matrix.py`.**
> `multirunner-build.yml` checks this repo out into `.bst-ci/` alongside the
> caller's checkout and runs it from there. tromso and xfce-linux both used to
> vendor it; both had their copies removed once the workflow stopped needing
> them. Re-adding one silently reintroduces the drift this repo exists to stop.

`ci-build-matrix.py` runs inside the pinned `bst2` container and splits
uncached elements into a core set plus `num_chunks` round-robin chunks with
composite cache keys. It carries no repo-specific assumptions — keep it that
way.

## Checks

```bash
python3 -m pytest tests/pytest -v    # 43 tests, offline, no BuildStream needed
ruff check .                         # config in ruff.toml
```

> **Build output is committed.** Five `__pycache__/*.pyc` files are tracked
> (under `scripts/` and `tests/pytest/`), compiled for `cpython-313` — neither
> CI's Python 3.14 nor a typical local 3.11 will load them, so they are inert
> clutter rather than a hazard, but they are build artifacts in version control
> and belong in `.gitignore`.

> **`ruff` is configured but not enforced.** `ruff.toml` sets the rules, and
> `test.yml` runs *only* pytest — so nothing checks them, and `ruff check .`
> currently reports 4 violations in `tests/pytest/` on `main`. Run it by hand
> until CI does, and expect those findings until they are cleaned up.

`scripts/lint_bst.py` lints BuildStream element files. `test.yml` runs the
suite; `multirunner-build.yml` is the reusable workflow itself and is
exercised by its consumers rather than from here — which is the awkward part
of this repo: **its real integration test is someone else's CI run.** When
changing the workflow, the honest verification is a run in tromso or
xfce-linux, not a green check here.

## Scope

Export, sign and push stay in the **calling** repo — see "Scope" in the README.
This repo owns the build-and-cache half only. Resist absorbing the publish
half; the two consumers sign differently.
