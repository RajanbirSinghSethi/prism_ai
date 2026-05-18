from sdlc_copilot.agents.registry import DEFAULT_WORKFLOW, get_specs, list_agents
from sdlc_copilot.agents.specs import AGENT_SPECS


def test_all_blueprint_agents_are_registered() -> None:
    assert len(AGENT_SPECS) == 27
    ids = {agent["id"] for agent in list_agents()}
    assert "requirement_extraction" in ids
    assert "compliance" in ids


def test_default_workflow_is_valid_subset() -> None:
    specs = get_specs(DEFAULT_WORKFLOW)
    assert [spec.id for spec in specs] == DEFAULT_WORKFLOW
