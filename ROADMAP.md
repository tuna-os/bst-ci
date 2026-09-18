# bst-ci ROADMAP

This document tracks strategic goals, pinning contracts, and maintenance schedules for `bst-ci` shared BuildStream CI infrastructure.

## Strategic Overview

`bst-ci` provides reusable BuildStream CI actions and workflows across all Tuna OS desktop image variant repositories.

## Roadmap Milestones

### Q3 2026: Supply-Chain Hardening & Pinning Policies (Completed / Maintained)
- [x] Enforce strict commit SHA / digest pinning for external GitHub actions and containers (e.g. pinned `bst2` container image tags in `multirunner-build.yml`).
- [x] Eliminate implicit fallback checkouts of `main` branch across reusable workflows.
- [x] Add explicit unit and integration test suites for linting and build-matrix helper scripts (`scripts/ci-build-matrix.py`, `scripts/lint_bst.py`).
- [x] Integrate code style enforcement (`ruff`) and Simplified Technical English (`ste.yml`) governance across CI workflows.

### Q4 2026: Multi-Architecture Build Acceleration & Observability
- [ ] Implement caching and artifact retention policies for BuildStream runners and GHCR CAS tarballs.
- [ ] Expand architecture coverage matrix for ARM64 (Asahi Linux) and RISC-V image builds in `multirunner-build.yml`.
- [ ] Provide standardized telemetry and structured JSON outputs for image build durations, chunk budgets, and failure modes.
