# AGENTS.md — agent guide for tuna-os/bst-ci

Shared **reusable GitHub Actions workflows** for the BuildStream desktop-image
repos — currently [`tromso`](https://github.com/tuna-os/tromso) and
[`brussels`](https://github.com/tuna-os/brussels) (formerly `xfce-linux`) call
`multirunner-build.yml`, and [`athens`](https://github.com/tuna-os/athens)
calls `lint-bst.yml`. Open to any other BuildStream desktop-image repo in or
out of the org.

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

That makes the `workflow_call` input blocks in
`.github/workflows/multirunner-build.yml` and `.github/workflows/lint-bst.yml`
a **public API**. Renaming an input, tightening a default, or changing what a
step emits breaks the callers. They pin a reviewed `main` commit SHA in
`uses:` (tromso and brussels mark it `# main` and Renovate bumps that digest;
athens has no Renovate config, so its pin moves only by hand). A change here
therefore reaches a consumer when its pin moves, not at its next run, and
there is no version number to warn it.
Treat the callers as the compatibility contract and check them before
changing the interface.

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

`scripts/cas_transport.py` owns the GHCR CAS archive transport: the
`cache-<image><arch>-<stage>:<tag>` reference format, the
`application/vnd.buildstream.cas.tar.zst` media type, the archive/restore
exclude list, the streamed restore, the workspace-scoped builder stop and the
push retry policy. `tests/pytest/test_cas_transport.py` covers it offline
with stub `oras`, `podman` and `zstd`. The core and chunk jobs in
`multirunner-build.yml` still carry inline copies of these steps until they
call the script (#59). Until then, a transport change goes in both places.

`scripts/cas_bootstrap.py` is the read-only side for a developer machine: it
downloads those archives with an anonymous pull token, checks the layer
digest, and extracts them into a local BuildStream cache. It imports the
reference format, the media type and the exclude list from
`cas_transport.py`, so a change to those reaches both. It must never get a
push path; `tests/pytest/test_cas_bootstrap.py` asserts that. Consumers fetch
it at a pinned commit with a SHA-256 check (tromso: `just/local-cache.just`),
so its command line is a public interface like the workflow inputs.

## Checks

```bash
python3 -m pytest tests/pytest -v    # offline, no BuildStream needed
ruff check .                         # config in ruff.toml, enforced in CI
```

> **`ruff` is enforced in CI as its own job** (`.github/workflows/test.yml`,
> job `ruff`), alongside separate `yamllint`, `actionlint` and `pytest` jobs —
> `test.yml` runs all four, not only pytest. `ruff check .` is clean on `main`.

Two more workflows gate PRs:

- **`actions-security.yml`**: job `lockfile` runs `gh actions-lock --verify`
  against `.github/workflows/actions.lock`, and job `zizmor` fails on any
  workflow security finding. The lockfile is generated: after adding a
  workflow or changing any `uses:` line, run `gh actions-lock` and commit the
  lockfile in the same PR.
- **`ste.yml`** (Prose, runs when a PR changes Markdown or `.ste-budget`):
  Simplified Technical English lint over `README.md`,
  `CONTRIBUTING.md` and `docs/`, measured against `.ste-budget` (`0`), so any
  new finding fails. Never raise the budget to pass.

`yamllint` in CI uses a relaxed inline config, so a bare `yamllint` reports
errors CI does not. [`CONTRIBUTING.md`](CONTRIBUTING.md) has the CI-equivalent
command and the local commands for both workflows above.

`scripts/lint_bst.py` lints BuildStream element files. `test.yml` runs the
suite; `multirunner-build.yml` is the reusable workflow itself and is
exercised by its consumers rather than from here — which is the awkward part
of this repo: **its real integration test is someone else's CI run.** When
changing the workflow, the honest verification is a run in tromso or
brussels, not a green check here.

## Scope

Export, sign and push stay in the **calling** repo — see "Scope" in the README.
This repo owns the build-and-cache half only. Resist absorbing the publish
half; the two consumers sign differently.
