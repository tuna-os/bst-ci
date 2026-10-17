# Incident report: `bst-ci`

Copy this file for an incident affecting a `bst-ci` consumer. Keep the record
free of credentials, tokens, and private log contents; link to restricted
artifacts instead.

## Summary

- **Incident ID:**
- **Start (UTC):**
- **End (UTC):**
- **Status:** Investigating / Mitigated / Resolved
- **Incident commander:**
- **Primary consumer(s):** `tuna-os/tromso` / `tuna-os/xfce-linux` / other
- **Affected image or architecture:**

## Impact

- **First affected published build:**
- **Last known-good published build:**
- **First verified successful publish after mitigation:**
- **User-visible effect:**
- **Was a signed image available?**
- **Was an image published with an incorrect or incomplete cache?**

State the affected image tags and digest, if known. Do not paste secrets or
unredacted runner logs.

## Detection

- **Signal:** freshness alert / consumer run failure / cache symptom / report
- **Alert issue or source run:**
- **Detection time (UTC):**
- **Why this signal represents user impact:**

## Timeline (UTC)

| Time | Event | Evidence or link |
| --- | --- | --- |
|  |  |  |
|  |  |  |
|  |  |  |

## Affected revisions and caches

- **`bst-ci` workflow ref (`uses:`):**
- **`bst_ci_ref` script ref:**
- **Consumer commit:**
- **Last known-good `bst-ci` ref:**
- **Affected cache namespace or chunk(s):**
- **Were chunk names or cache keys changed?**

Remember that `uses:` and `bst_ci_ref` are separate refs. A consumer must pin
both when containing a script and workflow regression.

## Diagnosis

- **Trigger:**
- **Failed phase:** planning / core / dependency chunk / consumer final assembly
- **Root cause evidence:**
- **Contributing conditions:**
- **What was ruled out:**

## Mitigation and rollback

- **Chosen lever:** revert `bst-ci` / pin the consumer / forward fix / other
- **Commands or pull requests:**
- **Why this lever was safe for the affected consumers:**
- **Cache consequences:**
- **Who approved the change:**

Use `runbooks/rollback.md` for the rollback procedure. Treat a missing cache as
a performance problem unless the final consumer build or published artifact is
also affected.

## Verification

- [ ] The consumer's workflow was dispatched or observed after mitigation.
- [ ] Planning produced the expected target, chunk names, and cache keys.
- [ ] Core and chunk cache restores completed or rebuilt as expected.
- [ ] The consumer's final target built successfully.
- [ ] The image was published to the expected registry and tags.
- [ ] The image digest and signature were verified.
- [ ] The freshness alert was updated or closed after a successful publish.

**Evidence:**

## Follow-up actions

| Action | Owner | Due (UTC) | Tracking link | Status |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |
|  |  |  |  |  |

Classify each action as prevention, detection, mitigation, or documentation.
Do not close the incident until the first successful publish and the remaining
user-impact risk are explicit.
