# bst-ci

Shared workflows for GitHub Actions that the BuildStream desktop-image repos
of tuna-os call. The callers now are `tuna-os/tromso` and
`tuna-os/xfce-linux`. Any other repo that builds a desktop image with
BuildStream can use them too, in or out of the `tuna-os` org.

## Why

The pipeline for a chunked build on many runners has three stages: plan,
core, and parallel dependency chunks. The stages keep their CAS state in zstd
tarballs on GHCR. This pipeline is the same in each desktop repo, except for
the image name, the build target, and the number of chunks. Maintainers
copied it by hand between `tromso` and `xfce-linux`, and the copies drifted.
Each CI fix had to go in twice, and it was easy to forget one copy.

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

`multirunner-build.yml` runs `scripts/ci-build-matrix.py` (also in this repo)
inside the pinned `bst2` container. The script divides the uncached elements
into a core set and `num_chunks` round-robin chunks, with composite cache
keys. It is a plain script, and it makes no assumptions about the repo that
calls it.

`multirunner-build.yml` checks this repo out into `.bst-ci/` next to the
checkout of the caller, and runs the script from there. Thus **consumers must
not keep their own copy** of this script. tromso and xfce-linux both had a
copy. Both repos removed it when this workflow no longer used it.

### Stop chunks from a rebuild of the same expensive elements

Chunks are **round-robin** slices of the dependency order. Thus chunk *i* holds
elements from all parts of the graph. Some of these elements are near the
end, and their transitive closure is almost everything. A chunk builds each
dependency that is not already in the core CAS that it restored. Thus
different chunks do the same work again.

A measurement on tuna-os/xfce-linux found 2.6× (487 distinct elements, 1281
element builds in one run). On tuna-os/tromso, the factor was 3.4×. In each
run, 4–5 chunks built LLVM, and each LLVM build took about 2 hours.

Three inputs address this, and none of them disturbs the chunk caches that
are already on GHCR:

| Input | Default | What it does |
| --- | --- | --- |
| `extra_core_targets` | `''` | Extra elements built in `build_core` *in addition to* the first `core_split` plan entries. The chunk matrix is still derived from `core_split` alone, so chunk names and cache keys are unchanged. Anything listed here is built once and reaches every chunk through the shared core CAS. |
| `soft_core_budget` | `false` | Lets `build_core` exhaust its budget without failing the job. Core is a cache-warming job whose partial CAS is pushed either way, so when you deliberately give it more work than fits in one job the timeout is a checkpoint, not a fault. Only exit code 124 is softened. |
| `soft_chunk_budget` | `false` | Lets dependency chunks treat exit code 124 as a cache-warming checkpoint instead of failing the run. This allows the caller's `build_final` job to consume the partial CAS and lets later runs resume from the rolling cache. Real build errors still fail. |

An increase of `num_chunks` is *not* a substitute. With round-robin slices,
more chunks copy the duplicated closure onto more runners, and do not divide
the work. Also, the workflow names each chunk from its first element
(`chunk{i}-{label}`). Thus a change to `num_chunks` **or** `core_split` gives
every chunk a new name and discards every warm chunk cache. The maintainers
added `extra_core_targets` for this reason. With it, you can move the shared
spine into core and not pay that cost.

`core_budget_minutes` (default `'270'`) sets the `timeout` around the
`bst build` of core. This timeout must stay inside the 360-minute job timeout.
It must also leave time for the archive and push of the CAS that follow it,
and that step grows with the cache. One chunk took 16 minutes to push a CAS
of a similar size.

`chunk_budget_minutes` (default `'270'`) sets the same timeout for each
dependency chunk. A job-level timeout cancels the job and discards the whole
chunk. A large chunk CAS can take an hour to push. If the chunks of a repo
stop at 6 hours in the "Push Chunk CAS" step, decrease this value.

Enable `soft_chunk_budget` when chunks often reach their budget but still
make useful progress. A chunk that times out publishes only its
`:latest` cache tag, which moves forward with each run. It does not publish
the exact `:<cache_key>` tag, because that tag means that the chunk is
complete. Thus repeated runs converge, and a chunk that is not complete
cannot show as complete.

Keep the input disabled when a timeout must stop the final assembly.
`soft_core_budget` applies the same policy for exit code 124 to the serial
core job. The two inputs are independent.

`runner_label` / `runner_label_aarch64` (default `ubuntu-24.04` /
`ubuntu-24.04-arm`) set `runs-on` for the plan job, core, and the chunks. Only
this lever can make a *single* expensive element build faster. Chunks cannot
divide the build of one `bst` element across runners. A job waits forever in
the queue if the caller repository has no runner with its label. Thus set a
label only if you know that it resolves there.

## Verification without a build

The tests and lint checks here do not need BuildStream, podman, or a real
chunked build:

- `tests/pytest/` contains unit tests for the pure functions in
  `ci-build-matrix.py`. It also contains CLI tests that run the script as a
  subprocess against a synthetic `build-plan.txt`, with no `bst show`.
  To run them on your machine, use `pytest tests/pytest/ -v`.
- `actionlint` and `yamllint` check every workflow file. This includes the
  `.github/workflows/test.yml` file of this repo, so this repo lints itself.
- GitHub does not validate the contract between repos for you. Thus, before
  you change the `inputs:`/`outputs:` contract of `workflow_call`, do these
  steps:
  1. Search both consumers for `with:` keys and `needs.multirunner.outputs.*`
     references.
  2. Make sure that this repo still matches what the consumers expect.
- `scripts/lint_bst.py` is a static lint for `.bst` element files (see below).

### `scripts/lint_bst.py`

This script finds two classes of mistake in new or changed `.bst` files. It
does not need BuildStream, a junction fetch, or a real build. It needs
Python 3 and PyYAML (`python3 -m pip install pyyaml`):

1. **Structure**: invalid YAML and a missing `kind:` are errors. If the
   script does not know a BuildStream plugin kind, it gives a warning, not an
   error. The unknown kind can be a typo, such as `kind: meason`. But the
   list in the script possibly does not include every valid third-party
   plugin.
2. **Cross-reference**: the script finds each junction-qualified dependency
   in a new or changed file. This is a name with a `:` in it, for example
   `freedesktop-sdk.bst:components/foo.bst`. The script then compares each
   of these names with all the `.bst` files that are already in the tree.

   The script flags a dependency if no other file refers to it. The
   dependency possibly does not exist in the junctioned project. The script
   knows only if *this* codebase used that name with success before. It does
   not know if the name is real.

   The script found this type of gap on its first use. A new `cage.bst` for
   tuna-os/xfce-linux#39 referred to
   `freedesktop-sdk.bst:components/wlroots.bst`. No other element in
   `tromso` or `xfce-linux` used that dependency. Thus that PR needed a
   second look before the merge.

```sh
# Lint an entire tree (structural checks only):
python3 scripts/lint_bst.py path/to/elements

# Also flag unconfirmed dependencies introduced by specific new/changed files:
python3 scripts/lint_bst.py path/to/elements --check-new path/to/elements/foo/new-thing.bst

# In CI, pair --check-new with a diff against the PR's base branch to
# scope it to files actually touched by the PR, e.g.:
#   git diff --name-only --diff-filter=AM origin/main... -- '*.bst'
```

The script exits with 0 unless it finds a structural error (invalid YAML,
missing `kind:`). By default, an unknown kind or an unconfirmed dependency
gives only a warning. These findings tell you to look at something, and they
are not always failures. When you trust their false-positive rate, add
`--strict` to make unconfirmed dependencies fatal. Unknown kinds stay
warnings.

## Scope

This repo owns the **plan, core, and parallel dependency chunks**. These are
the parts of the pipeline that are the same in each repo and that change
most frequently. This repo does **not** own these parts:

- **`build_final`** (export, `bootc container lint`, GHCR push, cosign
  signature, Trivy scan). Each consumer repo keeps this job. A keyless cosign
  signature contains the identity of the workflow that *calls* this one, in
  the Fulcio certificate. Assume that this shared workflow made the
  signature. Then the signature of each consumer would show the identity of
  `tuna-os/bst-ci`, not its own. Then the verification instructions in the
  README of each consumer would not work.
- **ISO builds, Containerfiles, dracut modules, install scripts**. These are
  different for each desktop, with different base images and live-session
  setup. They are not good candidates for a shared abstraction.

## Versioning

Consumers can pin the workflow by commit SHA:

```yaml
jobs:
  multirunner:
    uses: tuna-os/bst-ci/.github/workflows/multirunner-build.yml@<sha>
    with:
      image_name: your-image
      bst_target: oci/your-image.bst
```

If you pin to make a rollback possible, know these two caveats:

- **This repository publishes no tags or releases yet**, so a SHA is the only
  ref that resolves. The two consumers now track `main`.
- **A pin freezes only the workflow definition.** The `planning` job checks
  the helper scripts out into `.bst-ci` with `ref: main` hardcoded. Thus a
  pinned consumer still runs the current `scripts/ci-build-matrix.py`. This
  script computes the chunk names, the chunk matrix, and the GHCR cache keys.
  No input can override that ref. If you pass an input that the workflow does
  not declare, the run fails at load time.

`runbooks/rollback.md` tells you what to do when a change here breaks a
consumer. It tells you which of the two levers for a rollback to use for each type of
regression. It also tells you which caches the rollback can affect.

## Consumers

- [tuna-os/tromso](https://github.com/tuna-os/tromso)
- [tuna-os/xfce-linux](https://github.com/tuna-os/xfce-linux)
