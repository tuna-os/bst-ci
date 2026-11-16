"""Check the caller examples in this repo's Markdown against the workflow inputs.

Consumers copy these examples. GitHub rejects a `workflow_call` that passes an
undeclared input, so an example that names an input the workflow does not
declare, or that leaves out a required one, fails the caller's run before any
job starts (#41).
"""
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github/workflows"
USES = re.compile(r"^tuna-os/bst-ci/\.github/workflows/([^@]+)@\S+$")
FENCE = re.compile(r"^```ya?ml[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)


def markdown_files():
    return sorted(
        p for p in REPO.rglob("*.md")
        if ".git" not in p.relative_to(REPO).parts
    )


def caller_examples():
    """Yield (location, workflow file name, `with:` mapping) per example job."""
    for md in markdown_files():
        text = md.read_text()
        for match in FENCE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            location = f"{md.relative_to(REPO)}:{line}"
            doc = yaml.safe_load(match.group(1))
            if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict):
                continue
            for job in doc["jobs"].values():
                uses = USES.match(str((job or {}).get("uses", "")))
                if uses:
                    yield location, uses.group(1), job.get("with") or {}


def declared_inputs(workflow_file):
    workflow = yaml.safe_load((WORKFLOWS / workflow_file).read_text())
    # PyYAML reads the bare `on:` key as boolean True.
    triggers = workflow.get("on", workflow.get(True))
    return triggers["workflow_call"].get("inputs") or {}


EXAMPLES = list(caller_examples())


def test_every_reusable_workflow_has_a_checked_example():
    reusable = {
        p.name for p in WORKFLOWS.glob("*.yml")
        if "workflow_call" in (yaml.safe_load(p.read_text()).get(True) or {})
    }
    assert reusable, "no reusable workflows found"
    assert reusable <= {name for _, name, _ in EXAMPLES}


@pytest.mark.parametrize(
    "location,workflow_file,with_",
    EXAMPLES,
    ids=[f"{loc}:{name}" for loc, name, _ in EXAMPLES],
)
def test_example_passes_only_declared_inputs(location, workflow_file, with_):
    assert (WORKFLOWS / workflow_file).is_file(), (
        f"{location} calls {workflow_file}, which does not exist"
    )
    inputs = declared_inputs(workflow_file)

    undeclared = sorted(set(with_) - set(inputs))
    assert not undeclared, (
        f"{location} passes inputs {workflow_file} does not declare: {undeclared}"
    )

    required = {name for name, spec in inputs.items() if spec.get("required")}
    missing = sorted(required - set(with_))
    assert not missing, (
        f"{location} omits required inputs of {workflow_file}: {missing}"
    )
