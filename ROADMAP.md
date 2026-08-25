# bst-ci Roadmap

**Last updated**: 2026-08-24 | **Maintainer**: tuna-os (hanthor)

---

## Mission

Own the shared reusable BuildStream workflows that build the desktop-image
repos (tromso, xfce-linux, and any other BuildStream-based image repo in or
out of the org) — so image builds are consistent, pinned, and verifiable
across every consumer.

---

## Current Status

- **Role**: shared reusable GitHub Actions for BuildStream desktop images.
- **Distribution**: consumed as reusable workflows; **no tagged releases** of
  the shared CI itself.
- **Health**: 3 open issues — reusable workflow bypasses consumer pinning
  (#9), mutable actionlint container tag (#8), live BuildStream
  planning/dependency coverage (#10).

### Priorities

| Priority | Item | Tracking | Status |
|----------|------|----------|--------|
| P0 | Reusable workflow honors consumer pinning — no silent bypass | #9 | 🟡 Open |
| P1 | Mutable actionlint container tag pinned | #8 | 🟡 Open |
| P1 | Live BuildStream planning/dependency coverage | #10 | 🟡 Open |
| P2 | ROADMAP-coverage entry in org ROADMAP tally | #1295 | ⬜ Not started |

---

## Quarterly Goals

### Current Quarter (2026 Q3)

**Theme**: pin and secure the shared layer

| Goal | Owner | Tracking | Status |
|------|-------|----------|--------|
| Consumer-pinning honored | hanthor | #9 | ⬜ Not started |
| Actionlint tag pinned | hanthor | #8 | ⬜ Not started |

### Next Quarter (2026 Q4)

**Theme**: coverage and cadence

| Goal | Owner | Tracking | Status |
|------|-------|----------|--------|
| Live BuildStream planning coverage | hanthor | #10 | ⬜ Not started |
| Tagged releases of the shared workflows | tuna-os | (new) | ⬜ Not started |

---

*ROADMAP added by strategist agent (ACMM L6 — full mode). Signed-off-by: hanthor-hive-agent[bot] <290068839+hanthor-hive-agent[bot]@users.noreply.github.com>*
