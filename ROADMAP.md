# bst-ci ROADMAP

**Last updated**: 2026-10-03 | **Status**: shared infrastructure, transitioning from unplanned to planned

---

## Mission

Provide reproducible, secure, and maintainable BuildStream CI workflows for all Tuna OS desktop image variants (tromso, xfce-linux, and future BuildStream-based images). As shared infrastructure, bst-ci's primary contract is **supply-chain integrity**: every consumer must be able to pin bst-ci to an immutable version, and changes must never silently break a pinned consumer.

## Strategic Overview

`bst-ci` provides reusable BuildStream CI actions and workflows consumed by multiple desktop-image repositories. As infrastructure, it has a wide blast radius: **a broken change here breaks every consumer simultaneously**. This roadmap establishes ownership, pinning guarantees, and explicit security/reliability targets.

### Current Status

- **Consumers**: tromso, xfce-linux (2 active; more likely post-v0.1)
- **Owner**: unassigned (strategic gap: #12, #35)
- **Pinning contract**: partially enforced (#9 — reusable workflows can bypass consumer SHA pinning)
- **Release/tagging**: zero releases, zero tags
- **Known supply-chain risks**:
  - Mutable container tags in workflow definitions (#8)
  - Reusable workflow bypass allowing `@main` fallback (#9)
  - Incomplete BuildStream dependency coverage (#10)
  - No test suite for helper scripts
- **Related strategic issues**: #12, #35

### Priorities

| Priority | Item | Tracking | Status |
|----------|------|----------|--------|
| P0 | Document immutable pinning contract for all shared workflow inputs | #35 | 🟡 Proposed |
| P0 | Enforce SHA/digest pinning in all reusable-workflow calls (fix #9 bypass) | #9 | 🔴 Open |
| P1 | Replace mutable container tags with immutable digests | #8 | 🔴 Open |
| P1 | Create test suite for build-matrix and helper scripts | #12 | ⬜ Not started |
| P2 | Document BuildStream dependency coverage and maintenance windows | #10 | 🟡 Proposed |

---

## Roadmap Milestones

### Q3 2026 → Q4 2026: Supply-Chain Hardening (CURRENT FOCUS)

**Theme**: establish pinning guarantees and ownership

**Decision blocker**: What is the immutable consumer-pinning model?
- Option A: consumers pin to git SHA of bst-ci main (e.g., `git@github.com:tuna-os/bst-ci@abc123`)
- Option B: consumers pin to released SemVer tags (e.g., `v0.1.0`)
- Option C: hybrid (released tags for stable workflows, SHA for experimental)

This decision unblocks everything else.

**Execution order**:
1. [ ] **BLOCKER**: Decide pinning model and document contract (#35)
2. [ ] Enforce reusable-workflow SHA pinning (#9) — prevent `@main` fallback
3. [ ] Migrate workflow definitions to digest-pinned containers (#8) — eliminate `latest` tags
4. [ ] Create unit test suite for workflow helper scripts
5. [ ] Tag v0.1.0 release with defined support contract and maintenance window
6. [ ] Remove bst-ci from org "still unplanned" list (#1295)

### Q4 2026: Multi-Architecture & Observability

**Theme**: expand coverage and publish metrics

- [ ] Implement ARM64 (aarch64) build-matrix support
- [ ] Add RISC-V image build support (if needed by variants)
- [ ] Publish standardized telemetry for image build durations and failure modes
- [ ] Document deprecation schedule for `main`-branch consumers (v0.1.0 is last)

---

## Versioning & Support Contract

### v0.1.0 (target: Q4 2026)

- **Status**: first release candidate
- **Support**: active development; breaking changes acceptable with notice
- **Pinning**: consumers should pin to git SHA or named releases only, never `@main`
- **Containers**: all external references use immutable digests (no `latest` tags)
- **Workflows**: reusable workflows enforce caller SHA pinning

### Future (v0.2.0+)

- **Deprecation**: `@main` consumers will be unsupported; migration path documented

---

## Related Issues

- #12 — Strategic gap: bst-ci needs ROADMAP and owner
- #35 — Strategic gap: pinning policy and maintenance schedule
- #9 — Reusable workflow bypass allows `@main` fallback
- #8 — Mutable container tags in workflow definitions
- #10 — Incomplete BuildStream dependency coverage
- tunaos#1295 — Org "still unplanned" repos list (bst-ci is currently on it)
