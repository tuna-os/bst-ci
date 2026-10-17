from pathlib import Path

import yaml


WORKFLOW = Path(__file__).parents[2] / ".github/workflows/multirunner-build.yml"


def planning_steps():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return workflow["jobs"]["planning"]["steps"]


def named_step(name):
    return next(step for step in planning_steps() if step.get("name") == name)


def test_helper_checkout_uses_resolved_workflow_sha():
    checkout = named_step("Checkout bst-ci scripts")

    assert checkout["with"]["repository"] == "tuna-os/bst-ci"
    assert checkout["with"]["ref"] == "${{ github.workflow_sha }}"


def test_workflow_revision_is_validated_before_helper_checkout():
    steps = planning_steps()
    validation = named_step("Validate bst-ci workflow revision")
    checkout = named_step("Checkout bst-ci scripts")

    assert steps.index(validation) < steps.index(checkout)
    assert validation["env"]["WORKFLOW_SHA"] == "${{ github.workflow_sha }}"
    assert "github.workflow_sha is missing or is not a full commit SHA" in validation["run"]
    assert "Conflicting bst_ci_ref" in validation["run"]
