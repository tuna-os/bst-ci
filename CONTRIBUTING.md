# Contributing to bst-ci

Thank you for your contribution to `bst-ci`! Other repositories can call the shared workflows for GitHub Actions in this repository. The repository also supplies the scripts that make the build matrix for BuildStream desktop images across `tuna-os` (such as `tuna-os/tromso` and `tuna-os/xfce-linux`).

## Development and Local Verification

You can verify all workflows and scripts in this repository on your own machine. You do not need BuildStream, Podman, or a live runner for a chunked build.

### 1. Run the Unit Tests

The unit tests cover the logic that plans the build matrix (`scripts/ci-build-matrix.py`). They also cover the static lint of `.bst` elements (`scripts/lint_bst.py`).

Prerequisites:
- Python 3.10+
- `pytest` and `PyYAML`

```bash
pip install pytest pyyaml
pytest tests/pytest/ -v
```

### 2. Lint the Workflows and the YAML

CI uses `actionlint` and `yamllint` to lint the workflows in `.github/workflows/`. Make sure that each YAML file that you change passes these linters on your machine:

```bash
yamllint .github/workflows/
actionlint
```

### 3. Static Lint of `.bst` Elements

`scripts/lint_bst.py` does structural checks on `.bst` files. It also cross-checks the junction references in them. It does not fetch the external junction repositories:

```bash
# Structural check on an element tree
python3 scripts/lint_bst.py path/to/elements

# Check unconfirmed dependencies on newly added elements
python3 scripts/lint_bst.py path/to/elements --check-new path/to/elements/new-element.bst
```

## Guidelines for Changes

1. **Keep the interface contracts**: Before you change `inputs:` or `outputs:` in `.github/workflows/multirunner-build.yml`, make sure that the consumer repositories (`tuna-os/tromso` and `tuna-os/xfce-linux`) still work with them.
2. **DCO Sign-off**: All commits must include a `Signed-off-by:` line (`git commit -s`).
3. **No Direct Merges**: Open a Pull Request for review.
