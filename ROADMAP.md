# bst-ci ROADMAP

This document tracks strategic goals, pinning contracts, and maintenance schedules for `bst-ci` shared BuildStream CI infrastructure.

*Last Currency Refresh: September 2026*

## Strategic Overview

`bst-ci` provides reusable BuildStream CI actions and workflows across all Tuna OS desktop image variant repositories (`tromso`, `xfce-linux`).

## Roadmap Milestones

### Q3 2026: Supply-Chain Hardening & Pinning Policies (Completed / Verified)
- [x] Enforce strict commit SHA / digest pinning for external GitHub actions and containers.
- [x] Add explicit unit and integration test suites for linting and build-matrix helper scripts (Ruff, STE check, pytest-cov unit suites landed).
- [ ] Eliminate implicit fallback checkouts of `main` branch across reusable workflows to support release-pinned workflows.

### Q4 2026: Multi-Architecture Build Acceleration & Observability
- [ ] Implement caching and artifact retention policies for BuildStream runners.
- [ ] Expand architecture coverage matrix for ARM64 and RISC-V image builds across consumer image pipelines.
- [ ] Provide standardized telemetry for image build durations, chunk generation efficiency, and failure modes.

### Q1 2027: Reusable Workflow Versioning & Ecosystem Governance
- [ ] Tag semver releases (`v1.0.0`) and support explicit workflow ref pinning across downstreams.
- [ ] Establish automated integration smoke tests for downstream matrix consumers (`tromso`, `xfce-linux`).
