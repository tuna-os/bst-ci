# bst-ci ROADMAP

This document tracks strategic goals, pinning contracts, and maintenance schedules for `bst-ci` shared BuildStream CI infrastructure.

## Strategic Overview

`bst-ci` provides reusable BuildStream CI actions and workflows across all Tuna OS desktop image variant repositories.

## Roadmap Milestones

### Q3 2026: Supply-Chain Hardening & Pinning Policies
- [ ] Enforce strict commit SHA / digest pinning for external GitHub actions and containers.
  Actions are locked to commits in `.github/workflows/actions.lock`, verified by `actions-security.yml` (#115), and the actionlint container is pinned by digest (#8). Still open: the default `bst2_image` in `multirunner-build.yml` is a registry tag, not a digest.
- [x] Eliminate implicit fallback checkouts of `main` branch across reusable workflows.
  Helper checkouts use `job.workflow_sha` (#9, #105, #109); `test_workflow_pinning.py` and `test_lint_bst_workflow.py` assert it.
- [x] Add explicit unit and integration test suites for linting and build-matrix helper scripts.
  `tests/pytest/` covers `ci-build-matrix.py` (unit and CLI) and `lint_bst.py` (#1, #3, #109).

### Q4 2026: Multi-Architecture Build Acceleration & Observability
- [ ] Implement caching and artifact retention policies for BuildStream runners.
- [ ] Expand architecture coverage matrix for ARM64 and RISC-V image builds.
- [ ] Provide standardized telemetry for image build durations and failure modes.
