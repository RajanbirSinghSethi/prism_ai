"""Smoke-test rerun on the 6 worst-offender agents from the previous baseline.

Usage:
    python scripts/smoke_rerun.py

Produces:
    reports/after_run_report.md   — before/after comparison + log excerpt
    .data/logs/{run_id}/*.json    — per-agent debug logs (one per agent)

The script is in-process (no HTTP) so we don't hit the urllib timeout we saw
when calling the FastAPI ``/runs`` endpoint for a long pipeline.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Make ``sdlc_copilot`` importable when the script is launched standalone.
import sys  # noqa: E402
sys.path.insert(0, str(REPO_ROOT))

from sdlc_copilot.agents.validators import validate_cross_agent_ids  # noqa: E402
from sdlc_copilot.config import get_settings  # noqa: E402
from sdlc_copilot.models import PipelineRequest  # noqa: E402
from sdlc_copilot.services.pipeline import SDLCPipelineService  # noqa: E402


SMOKE_AGENTS = [
    "requirement_extraction",
    "requirement_classification",
    "conflict_detection",
    "hallucination_validation",
    "traceability",
    "compliance",
]

DEMO_PATH = REPO_ROOT / "demo.txt"
BEFORE_PATH = REPO_ROOT / "pipeline_result.json"
REPORT_PATH = REPO_ROOT / "reports" / "after_run_report.md"


def _load_before() -> dict:
    if BEFORE_PATH.exists():
        return json.loads(BEFORE_PATH.read_text(encoding="utf-8"))
    return {}


def _content_keys(out: dict | None) -> list[str]:
    if not out:
        return []
    content = out.get("content") if isinstance(out, dict) else {}
    return sorted(content.keys()) if isinstance(content, dict) else []


def _quality_signals(agent_id: str, content: dict) -> list[str]:
    """Return a short list of qualitative observations for the report."""
    signals: list[str] = []
    if agent_id == "requirement_classification":
        classified = content.get("classified") if isinstance(content, dict) else None
        if isinstance(classified, list) and classified:
            has_cat = any(isinstance(x, dict) and "category" in x for x in classified)
            has_pri = any(isinstance(x, dict) and "priority" in x for x in classified)
            signals.append(f"category field present: {has_cat}")
            signals.append(f"priority field present: {has_pri}")
        else:
            signals.append("classified[] missing")
    elif agent_id == "conflict_detection":
        conflicts = content.get("conflicts") if isinstance(content, dict) else None
        findings = content.get("findings") if isinstance(content, dict) else None
        if isinstance(conflicts, list):
            signals.append(f"conflicts[] entries: {len(conflicts)}")
        if isinstance(findings, list):
            signals.append(f"findings[] (legacy) entries: {len(findings)}")
    elif agent_id == "compliance":
        controls = content.get("controls") if isinstance(content, dict) else []
        if isinstance(controls, list):
            regs = {c.get("regulation") for c in controls if isinstance(c, dict)}
            signals.append("regulations: " + ", ".join(sorted(str(r) for r in regs if r)))
            signals.append(f"includes HIPAA: {'HIPAA' in regs}")
    elif agent_id == "hallucination_validation":
        keys = [k for k in ("fabricated_apis", "id_mismatches", "false_claims") if k in (content or {})]
        signals.append(f"new schema keys present: {keys}")
        if "hallucinated_dependencies" in (content or {}):
            signals.append("legacy 'hallucinated_dependencies' still present")
    elif agent_id == "traceability":
        links = content.get("links") if isinstance(content, dict) else []
        if isinstance(links, list) and links:
            sample_ids = [str(link.get("requirement_id")) for link in links[:5] if isinstance(link, dict)]
            signals.append("first 5 requirement_ids: " + ", ".join(sample_ids))
    elif agent_id == "requirement_extraction":
        ids: list[str] = []
        if isinstance(content, dict):
            for items in content.values():
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict) and "id" in item:
                            ids.append(str(item["id"]))
        prefix_sample = sorted({i.split("-")[0] for i in ids[:50] if "-" in i})
        signals.append("id prefixes seen: " + ", ".join(prefix_sample))
    return signals


def main() -> None:
    if not DEMO_PATH.exists():
        raise SystemExit(f"demo.txt not found at {DEMO_PATH}")

    demo_text = DEMO_PATH.read_text(encoding="utf-8")
    before = _load_before()
    before_outputs = before.get("outputs", {}) if isinstance(before, dict) else {}

    settings = get_settings()
    service = SDLCPipelineService(settings)
    request = PipelineRequest(
        project_name="TaskFlow MVP (smoke)",
        raw_text=demo_text,
        selected_agents=SMOKE_AGENTS,
    )

    print(f"Running smoke pipeline ({len(SMOKE_AGENTS)} agents)...")
    start = time.time()
    durations: dict[str, float] = {}
    final_state = None
    last_t = start
    for agent_id, state in service.stream(request):
        now = time.time()
        durations[agent_id] = now - last_t
        last_t = now
        out = state.outputs.get(agent_id)
        conf = out.confidence if out else None
        print(f"  [{now - start:6.1f}s] {agent_id}: confidence={conf}")
        final_state = state
    elapsed = time.time() - start
    print(f"Total time: {elapsed:.1f}s")

    if final_state is None:
        raise SystemExit("Pipeline produced no state.")

    # Cross-agent validator (pipeline already ran it but expose findings here too).
    validation = validate_cross_agent_ids(final_state.outputs)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_dir = settings.log_dir / final_state.run_id
    log_files = sorted(log_dir.glob("*.json")) if log_dir.exists() else []
    sample_log = log_files[0] if log_files else None

    lines: list[str] = []
    lines.append("# SDLC Agents — Smoke Re-run Report")
    lines.append("")
    lines.append(f"- run_id: `{final_state.run_id}`")
    lines.append(f"- total elapsed: {elapsed:.1f}s")
    lines.append(f"- agents run: {', '.join(SMOKE_AGENTS)}")
    lines.append(f"- per-agent debug logs: `{log_dir}` ({len(log_files)} files)")
    lines.append("")

    # ---- Before / after table ----
    lines.append("## Per-agent before / after")
    lines.append("")
    lines.append("| Agent | Confidence (before → after) | Duration (after) | Content keys (after) |")
    lines.append("|---|---|---|---|")
    for agent_id in SMOKE_AGENTS:
        before_conf = before_outputs.get(agent_id, {}).get("confidence")
        after_out = final_state.outputs.get(agent_id)
        after_conf = after_out.confidence if after_out else None
        after_keys = _content_keys(after_out.model_dump(mode="json")) if after_out else []
        dur = durations.get(agent_id, 0.0)
        lines.append(
            f"| `{agent_id}` | "
            f"{before_conf if before_conf is not None else 'n/a'} → "
            f"{after_conf if after_conf is not None else 'FAILED'} | "
            f"{dur:.1f}s | "
            f"{', '.join(after_keys) or '—'} |"
        )
    lines.append("")

    # ---- Quality signals per agent ----
    lines.append("## Quality signals (post-fix)")
    lines.append("")
    for agent_id in SMOKE_AGENTS:
        out = final_state.outputs.get(agent_id)
        if not out:
            lines.append(f"### `{agent_id}` — FAILED")
            lines.append("")
            continue
        content = out.content if isinstance(out.content, dict) else {}
        signals = _quality_signals(agent_id, content)
        lines.append(f"### `{agent_id}`")
        for s in signals:
            lines.append(f"- {s}")
        lines.append("")

    # ---- Cross-agent validator ----
    lines.append("## Cross-agent validator")
    lines.append("")
    if not validation:
        lines.append("All checks passed — no cross-agent ID mismatches detected.")
    else:
        for check, issues in validation.items():
            lines.append(f"### {check}")
            for issue in issues:
                lines.append(f"- {issue}")
            lines.append("")

    # ---- Sample log excerpt ----
    lines.append("")
    lines.append("## Sample per-agent log excerpt")
    lines.append("")
    if sample_log is not None:
        lines.append(f"File: `{sample_log}`")
        lines.append("")
        sample = json.loads(sample_log.read_text(encoding="utf-8"))
        excerpt = {
            "agent_id": sample.get("agent_id"),
            "order": sample.get("order"),
            "attempts": sample.get("attempts"),
            "duration_ms": sample.get("duration_ms"),
            "model": sample.get("model"),
            "provider": sample.get("provider"),
            "parsed_ok": sample.get("parsed_ok"),
            "prompt": {
                "user_payload_keys": sample.get("prompt", {}).get("user_payload_keys"),
                "user_payload_size_chars": sample.get("prompt", {}).get("user_payload_size_chars"),
            },
            "output": sample.get("output"),
            "error": sample.get("error"),
        }
        lines.append("```json")
        lines.append(json.dumps(excerpt, indent=2))
        lines.append("```")
    else:
        lines.append("(no log files found)")
    lines.append("")

    # ---- Errors recorded by the pipeline ----
    if final_state.errors:
        lines.append("## Pipeline-recorded errors")
        lines.append("")
        for key, value in final_state.errors.items():
            lines.append(f"### {key}")
            lines.append("```")
            lines.append(str(value)[:2000])
            lines.append("```")
            lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
