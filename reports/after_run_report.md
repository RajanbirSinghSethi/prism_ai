# SDLC Agents — Smoke Re-run Report

- run_id: `e401977d-262f-4c85-a6c8-3d0280bdf622`
- total elapsed: 141.5s
- agents run: requirement_extraction, requirement_classification, conflict_detection, hallucination_validation, traceability, compliance
- per-agent debug logs: `.data\logs\e401977d-262f-4c85-a6c8-3d0280bdf622` (6 files)

## Per-agent before / after

| Agent | Confidence (before → after) | Duration (after) | Content keys (after) |
|---|---|---|---|
| `requirement_extraction` | 0.9 → 0.9 | 5.5s | actors, functional, modules, non_functional, open_questions |
| `requirement_classification` | 0.85 → 0.95 | 4.5s | classified |
| `conflict_detection` | 0.85 → 0.85 | 47.9s | conflicts |
| `hallucination_validation` | 0.85 → 0.85 | 32.9s | fabricated_apis, false_claims, id_mismatches |
| `traceability` | 0.85 → 0.85 | 10.1s | links |
| `compliance` | 0.75 → 0.85 | 40.7s | controls |

## Quality signals (post-fix)

### `requirement_extraction`
- id prefixes seen: ACT, MOD, OQ, REQ

### `requirement_classification`
- category field present: True
- priority field present: True

### `conflict_detection`
- conflicts[] entries: 2

### `hallucination_validation`
- new schema keys present: ['fabricated_apis', 'id_mismatches', 'false_claims']

### `traceability`
- first 5 requirement_ids: REQ-4.1.1, REQ-4.1.2, REQ-4.1.3, REQ-4.1.4, REQ-4.2.1

### `compliance`
- regulations: GDPR, PCI-DSS, PII handling, SOC2, WCAG 2.1 AA
- includes HIPAA: False

## Cross-agent validator

All checks passed — no cross-agent ID mismatches detected.

## Sample per-agent log excerpt

File: `.data\logs\e401977d-262f-4c85-a6c8-3d0280bdf622\00_requirement_extraction.json`

```json
{
  "agent_id": "requirement_extraction",
  "order": 0,
  "attempts": 1,
  "duration_ms": 2624,
  "model": "llama-3.1-8b-instant",
  "provider": "groq",
  "parsed_ok": true,
  "prompt": {
    "user_payload_keys": [
      "constraints",
      "expected_artifact_type",
      "previous_agent_outputs",
      "project_name",
      "requirements_context",
      "team"
    ],
    "user_payload_size_chars": 5692
  },
  "output": {
    "confidence": 0.9,
    "risks_count": 1,
    "assumptions_count": 1,
    "content_keys": [
      "actors",
      "functional",
      "modules",
      "non_functional",
      "open_questions"
    ]
  },
  "error": null
}
```
