# Incident record: shared `bst-ci` workflow

Copy this file for an incident. Keep the completed record with the incident
artifacts; do not edit this template for one event.

## Summary

- **Incident:** <short description>
- **Status:** <investigating | contained | recovered | closed>
- **Coordinator:** <name or handle>
- **Detected at:** <UTC timestamp>
- **Recovered at:** <UTC timestamp or `not recovered`>
- **Severity:** <severity and reason>

## Impact

- **Affected consumers:** <tromso | xfce-linux | other>
- **Affected runs:** <workflow URLs and run IDs>
- **Published artifacts:** <none | image names, tags, and digests>
- **User impact:** <what users could not build, install, or receive>
- **Detection window:** <first bad run through containment>

State explicitly whether the failure stopped before `build_final`. A failure in
this shared workflow can prevent a caller from publishing, while a bad cache or
matrix result can affect later runs without an immediately red workflow.

## Evidence

Record the exact values before changing anything:

- `bst-ci` workflow ref from the caller's `uses:` line:
- `bst_ci_ref` passed to the planning job:
- resolved `bst-ci` commit SHA from `Checkout bst-ci scripts`:
- caller repository commit SHA:
- BuildStream image reference (`bst2_image`):
- planning matrix, chunk names, and cache keys:
- last known-good run and its values:
- first known-bad run and its values:

Attach relevant logs. Do not paste credentials, tokens, or signed URLs.

## Timeline

Use UTC and link each entry to a run, commit, or discussion.

| Time | Event | Evidence / link | Owner |
| --- | --- | --- | --- |
| <time> | <event> | <link> | <owner> |

## Containment

Choose the smallest lever that stops further impact:

- **All consumers affected:** revert the bad change on `bst-ci` `main`.
- **One consumer affected or a revert is not ready:** pin that consumer's
  `uses:` ref and `bst_ci_ref` to the same known-good SHA.
- **Cache-only damage:** leave orphaned cache tags in place during the
  incident; they are inert when no matrix resolves them. Clean them up later.

Follow [`rollback.md`](rollback.md) for the commands and the verification
sequence. Do not publish a new image until the caller's `build_final` job has
been checked separately.

## Recovery proof

Record the result for every affected consumer:

- [ ] planning resolves the expected matrix and cache keys
- [ ] core and chunk jobs restore or rebuild the expected caches
- [ ] no chunk is marked complete from a timed-out build
- [ ] caller `build_final` completes
- [ ] the published image has the expected digest and signature
- [ ] the next scheduled run remains healthy

## Root cause and follow-up

- **Root cause:** <workflow, helper script, caller, cache, runner, or external dependency>
- **Contributing factors:** <missing test, mutable ref, unclear ownership, etc.>
- **What worked:** <controls that limited impact>
- **What failed:** <control or assumption that did not>
- **Actions:** <owner, change, due date, and tracking link for each action>

Close the record only after all affected consumers have passed a scheduled or
manually dispatched run and the follow-up actions have owners.
