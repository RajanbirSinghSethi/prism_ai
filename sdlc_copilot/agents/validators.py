"""Post-run cross-agent ID consistency checks.

Pure-Python validators (no LLM calls). They walk the agent outputs after the
pipeline finishes and report ID-level inconsistencies that the model often
introduces despite the sharpened prompts:

- Story IDs referenced from task_decomposition that don't exist in user_story_generation.
- Requirement IDs in traceability that don't exist in requirement_extraction.
- Task IDs in team_allocation that don't exist in task_decomposition.
- Endpoints in api_specification with no matching link in traceability.

Each check returns a list of human-readable issue strings. The orchestrator
records them under ``state.errors["cross_agent_validation"]`` only when at
least one check produces findings, so a clean run leaves errors untouched.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from sdlc_copilot.models import AgentOutput


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_cross_agent_ids(outputs: dict[str, AgentOutput]) -> dict[str, list[str]]:
    """Run every cross-agent check and return ``{check_name: [issues]}``.

    Checks with no findings are omitted from the result, so an empty dict
    means "all clean".
    """
    findings: dict[str, list[str]] = {}

    for check_name, issues in (
        ("story_ids_in_tasks", _check_story_ids_in_tasks(outputs)),
        ("requirement_ids_in_traceability", _check_requirement_ids_in_traceability(outputs)),
        ("task_ids_in_team_allocation", _check_task_ids_in_team_allocation(outputs)),
        ("endpoints_in_traceability", _check_endpoints_in_traceability(outputs)),
    ):
        if issues:
            findings[check_name] = issues
    return findings


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_story_ids_in_tasks(outputs: dict[str, AgentOutput]) -> list[str]:
    stories = _get_content_list(outputs.get("user_story_generation"), "stories")
    tasks = _get_content_list(outputs.get("task_decomposition"), "tasks")
    if not stories or not tasks:
        return []
    story_ids = {str(s.get("id")) for s in stories if isinstance(s, dict) and s.get("id")}
    issues: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for dep in _as_iter(task.get("depends_on")):
            dep_str = str(dep)
            # depends_on can legitimately point at sibling tasks or stories;
            # only flag values that LOOK like story IDs but aren't defined.
            if dep_str.startswith("STORY-") and dep_str not in story_ids:
                issues.append(
                    f"task_decomposition[{task.get('id')}] depends_on '{dep_str}' "
                    f"but no story with that id exists in user_story_generation"
                )
    return issues


def _check_requirement_ids_in_traceability(outputs: dict[str, AgentOutput]) -> list[str]:
    extraction = outputs.get("requirement_extraction")
    traceability = outputs.get("traceability")
    if extraction is None or traceability is None:
        return []
    known_ids = _collect_requirement_ids(extraction)
    links = _get_content_list(traceability, "links")
    if not links:
        return []
    issues: list[str] = []
    for link in links:
        if not isinstance(link, dict):
            continue
        req_id = link.get("requirement_id")
        if req_id is None:
            issues.append(f"traceability link missing 'requirement_id': {link}")
            continue
        if known_ids and str(req_id) not in known_ids:
            issues.append(
                f"traceability references requirement_id '{req_id}' "
                f"but requirement_extraction has no item with that id"
            )
    return issues


def _check_task_ids_in_team_allocation(outputs: dict[str, AgentOutput]) -> list[str]:
    tasks = _get_content_list(outputs.get("task_decomposition"), "tasks")
    assignments = _get_content_list(outputs.get("team_allocation"), "assignments")
    if not tasks or not assignments:
        return []
    known_ids = {str(t.get("id")) for t in tasks if isinstance(t, dict) and t.get("id")}
    issues: list[str] = []
    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        task_id = assignment.get("task_id")
        if task_id is None:
            issues.append(f"team_allocation assignment missing 'task_id': {assignment}")
            continue
        if str(task_id) not in known_ids:
            issues.append(
                f"team_allocation references task_id '{task_id}' "
                f"but task_decomposition has no task with that id"
            )
    return issues


def _check_endpoints_in_traceability(outputs: dict[str, AgentOutput]) -> list[str]:
    endpoints = _get_content_list(outputs.get("api_specification"), "endpoints")
    traceability = outputs.get("traceability")
    if not endpoints or traceability is None:
        return []
    linked: set[str] = set()
    for link in _get_content_list(traceability, "links"):
        if isinstance(link, dict):
            for value in _as_iter(link.get("api_ids")):
                linked.add(str(value))
    if not linked:
        # No api_ids declared in traceability — treat as a single bulk gap.
        return [
            "traceability links contain no api_ids; "
            f"{len(endpoints)} endpoints from api_specification are untraced"
        ]
    issues: list[str] = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        path = endpoint.get("path")
        method = endpoint.get("method", "")
        identifier = f"{method} {path}".strip()
        if path and identifier not in linked and str(path) not in linked:
            issues.append(f"api_specification endpoint '{identifier}' has no traceability link")
    return issues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_content_list(output: AgentOutput | None, key: str) -> list[Any]:
    if output is None or not isinstance(output.content, dict):
        return []
    value = output.content.get(key)
    if isinstance(value, list):
        return value
    return []


def _as_iter(value: Any) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        return value
    return (value,)


def _collect_requirement_ids(extraction: AgentOutput) -> set[str]:
    """Best-effort gather of every ``id`` field inside requirement_extraction.content."""
    if not isinstance(extraction.content, dict):
        return set()
    ids: set[str] = set()
    _walk_for_ids(extraction.content, ids)
    return ids


def _walk_for_ids(node: Any, ids: set[str]) -> None:
    if isinstance(node, dict):
        if "id" in node and isinstance(node["id"], (str, int)):
            ids.add(str(node["id"]))
        for value in node.values():
            _walk_for_ids(value, ids)
    elif isinstance(node, list):
        for item in node:
            _walk_for_ids(item, ids)


def format_findings(findings: dict[str, list[str]]) -> str:
    """Serialize findings as a single string suitable for ``state.errors``."""
    if not findings:
        return ""
    return json.dumps(findings, ensure_ascii=False, indent=2)
