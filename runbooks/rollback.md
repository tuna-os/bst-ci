# Runbook: rolling back a bad `bst-ci` change

`bst-ci` is shared release infrastructure. `multirunner-build.yml` runs the
planning, core and chunk phases of every consuming repository's image build,
and `scripts/ci-build-matrix.py` decides the chunk names and GHCR cache tags
those builds resolve against. A regression here degrades every consumer at
once, on their next scheduled run, without any change landing in their repos.

Consumers (see README.md):

| Repository | Caller workflow | Schedule |
| --- | --- | --- |
| `tuna-os/tromso` | `.github/workflows/build-tromso-multirunner.yml` | daily, 00:30 UTC |
| `tuna-os/xfce-linux` | `.github/workflows/build-multirunner.yml` | daily, 23:30 UTC |

Both publish signed OCI images to GHCR from their own `build_final` job, which
this repository does not own.

## What a `main` push actually reaches

The ref in the consumer's `uses:` line selects the workflow definition. During
planning, that workflow checks `scripts/ci-build-matrix.py` out at
`${{ github.workflow_sha }}`, the exact commit from which GitHub loaded the
reusable workflow. The YAML and helper therefore move as one versioned unit.

`bst_ci_ref` remains only for compatibility with callers that already pass it.
When present, it must identify the same ref or commit as `uses:`; a mismatch
fails before the helper checkout. It cannot select another helper revision.

## Symptoms that point at a `bst-ci` regression

- Several consumers fail or misbehave in the same way on the same night, with
  no corresponding change in their own repositories.
- The `planning` job's `matrix.json` shows different chunk names, a different
  chunk count, or different cache keys than the previous successful run.
- Every chunk reports a cache miss and rebuilds from cold after a `bst-ci`
  push, even though no element sources changed.
- `Generate Build Matrix` fails inside `.bst-ci/scripts/ci-build-matrix.py`.

## Step 1 — confirm the blast radius

1. Open the consumer's failing run and note the `bst-ci` commit used. The
   `Checkout bst-ci scripts` step logs the resolved SHA.
2. Compare with the last green run of the same workflow. If the consumer's own
   tree is unchanged between the two and only the `bst-ci` SHA moved, the
   regression is here.
3. Check whether the second consumer is affected too. A fault that reproduces
   in both is in this repository; one that reproduces in only one is more
   likely in that repository's elements or in its `build_final`.

## Step 2 — choose a rollback lever

Two levers exist. They cover different failures, so pick by where the bad
change landed.

### Lever A — revert on `bst-ci` `main` (fixes every consumer at once)

Use when the bad change is in either the workflow or the scripts, and when you
want all consumers restored without touching their repositories.

```sh
git -C bst-ci checkout main && git pull
git revert --no-edit <bad-sha>      # or: git revert -m 1 --no-edit <merge-sha>
git push origin main
```

The next consumer run picks the revert up automatically. Nothing needs to be
re-dispatched for the schedule to recover, but a `workflow_dispatch` run on
each consumer confirms the fix before the next nightly window.

### Lever B — pin the consumer to a known-good ref (contains one consumer)

Use when a forward fix is not ready, when the regression is understood but the
revert is not trivial, or when only one consumer must be protected while the
others keep taking `main`.

In the consumer's caller workflow, pin the `uses:` ref to a known-good
`bst-ci` SHA:

```yaml
jobs:
  multirunner:
    uses: tuna-os/bst-ci/.github/workflows/multirunner-build.yml@<known-good-sha>
    with:
      image_name: tromso
      bst_target: oci/tromso.bst
```

That one pin covers the workflow YAML and `scripts/ci-build-matrix.py`, because
the helper checkout uses the resolved workflow SHA. If the caller already
passes `bst_ci_ref`, set it to the same SHA or remove it; a different value is
rejected before checkout.

Use a known-good revision containing this self-pinning behavior. Older
revisions may still load the helper from `main`; inspect the pinned workflow
before relying on it for a script rollback, and use Lever A when necessary.

Record the pin and its reason in the consumer repository, and unpin once the
fix lands here — a forgotten pin quietly stops that consumer from receiving
later fixes.

## Step 3 — expect a cold cache when chunk naming or cache keys moved

Chunk names and composite cache keys come from `scripts/ci-build-matrix.py`
and are interpolated into the GHCR cache tags
(`ghcr.io/<repo>/cache-<image><arch>-<chunk>:<cache-key>`). Any change that
alters them — renaming chunks, changing the sanitizer, changing how a key is
composed, changing `core_split` or `num_chunks` — makes every existing tag
unreachable rather than wrong.

Consequences to plan for after such a rollback:

- The first run rebuilds from cold: chunks are bounded at 270 minutes each and
  core at `core_budget_minutes` (default 270), inside 360-minute job timeouts.
  Expect one or more runs that do not reach a published image.
- Partial progress is still preserved: core and chunks push their CAS to the
  rolling `:latest` cache tag on every run (`if: always()`), so consecutive
  runs converge. Do not cancel a run that looks stuck at "rebuilding
  everything" — cancelling discards the CAS it was about to push.
- If the consumer sets `soft_chunk_budget: true`, a chunk that exhausts its
  budget stays green so `build_final` still runs; without it, one red chunk
  skips `build_final` and the run publishes nothing.
- The orphaned cache tags from the bad revision stay in GHCR. They are inert —
  no run resolves them — and can be cleaned up later, out of the incident.

## Step 4 — verify the rollback

1. Dispatch the consumer's build workflow manually
   (`gh workflow run <caller-workflow> --repo tuna-os/<consumer>`).
2. Confirm the `planning` job's chunk names and cache keys match the last known
   good run.
3. Confirm the chunk jobs report cache hits, or, on a chunk-naming rollback,
   confirm they are rebuilding and pushing rather than failing.
4. Confirm the consumer's own `build_final` publishes and signs as usual — that
   job lives in the consumer repository and is not affected by this rollback.

## Reducing exposure next time

- Cut a tag for each known-good state of this repository so consumers have a
  stable ref to pin to. Without tags, "pin to a known-good ref" degrades to
  "pin to a SHA someone has to find during an incident".
- Land script and workflow changes that alter chunk naming or cache keys
  deliberately, and say so in the commit message: the cost is not a build
  failure but hours of rebuild across every consumer.
- Pin the reusable workflow's `uses:` ref; its helper follows the same resolved
  commit automatically.
- Consumers that must not break unattended should pin deliberately and update
  the pin on purpose, rather than tracking `main`.
