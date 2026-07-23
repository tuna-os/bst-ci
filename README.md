# bst-ci

Shared reusable GitHub Actions workflows for tuna-os's BuildStream
desktop-image repos (currently `tuna-os/tromso`, `tuna-os/xfce-linux`) —
and open to any other BuildStream-based desktop image repo, in or out of
the `tuna-os` org.

## Why

The multi-runner chunked-build pipeline (plan → core → parallel dep chunks,
sharing CAS state via GHCR-hosted zstd tarballs) is identical across every
desktop repo except for the image name, build target, and chunk count. It
was being hand-copied between `tromso` and `xfce-linux`, which drifts:
every CI fix had to be applied twice, and it was easy to forget one.

## Usage

```yaml
jobs:
  multirunner:
    uses: tuna-os/bst-ci/.github/workflows/multirunner-build.yml@main
    with:
      image_name: your-image
      bst_target: oci/your-image.bst
      num_chunks: '10'      # optional, default 10
      core_split: '200'     # optional, default 200

  build_final:
    needs: multirunner
    if: always() && !contains(needs.*.result, 'failure') && !contains(needs.*.result, 'cancelled')
    runs-on: ubuntu-24.04
    # ... export, sign, push — stays in your own repo. See "Scope" below.
```

`scripts/ci-build-matrix.py` (also in this repo) is what `multirunner-build.yml`
runs inside the pinned `bst2` container to split uncached elements into a
core set + `num_chunks` round-robin chunks with composite cache keys. It's
a plain script with no repo-specific assumptions — `multirunner-build.yml`
checks this repo out into `.bst-ci/` alongside the caller's own checkout
and invokes it from there, so **consumers should not carry their own copy**
of this script (tromso and xfce-linux both used to; both had it removed
once this workflow stopped needing it).

## Verification without a build

Both scripts and workflows here are checked without needing BuildStream,
podman, or a real chunked build to run:

- `tests/pytest/` — unit tests for the pure functions in
  `ci-build-matrix.py`, plus CLI-level tests that drive the script as a
  subprocess against a synthetic `build-plan.txt` (no `bst show` required).
  Run locally: `pytest tests/pytest/ -v`.
- `actionlint` + `yamllint` on every workflow file, including this repo's
  own `.github/workflows/test.yml` (dogfooded — this repo lints itself).
- Before changing the `workflow_call` `inputs:`/`outputs:` contract,
  grep both consumers for `with:` keys and `needs.multirunner.outputs.*`
  usages to make sure nothing here silently stops matching what they
  expect — GitHub doesn't validate that across repos for you.

## Scope

This repo owns the **planning + core + parallel dependency chunks** —
the mechanically identical, highest-churn part of the pipeline. It does
**not** own:

- **`build_final`** (export, `bootc container lint`, GHCR push, cosign
  signing, Trivy scan) — kept in each consuming repo. Cosign's keyless
  signing embeds the *calling* workflow's identity in the Fulcio
  certificate; if signing happened inside this shared workflow instead,
  every consumer's published signature would carry `tuna-os/bst-ci`'s
  identity instead of their own, breaking the verification instructions
  in each repo's README.
- **ISO building, Containerfiles, dracut modules, install scripts** —
  these differ meaningfully per desktop (different base images, different
  live-session setup) and aren't good candidates for a shared abstraction.

## Versioning

Consumers currently pin `@main` (this repo has no tagged releases yet).
Once this stabilizes across a few consumers, moving to tagged releases
(`@v1`) is worth doing so a breaking change here can't silently break
every consumer's next scheduled build.

## Consumers

- [tuna-os/tromso](https://github.com/tuna-os/tromso)
- [tuna-os/xfce-linux](https://github.com/tuna-os/xfce-linux)
