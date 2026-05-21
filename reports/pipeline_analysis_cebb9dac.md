# PRISM Pipeline — Agent-by-Agent Analysis Report

**Run ID:** `cebb9dac-a5ad-4697-917f-d00eb769f1b1`  
**Project:** PRISM Project (input: `demo.txt` — TaskFlow Multi-tenant SaaS MVP)  
**Date:** 2026-05-21  
**Model:** `llama-3.1-8b-instant` via Groq  
**Total Elapsed:** ~15 min 21 s (18:33:59 → 18:49:20)  
**Documents ingested:** 2 | **Chunks:** 5 | **Agents executed:** 22/22  
**Pipeline result:** All agents completed — 0 errors, 13 cross-agent validation findings

---

## Executive Summary

| Metric | Value |
|---|---|
| Agents with confidence ≥ 0.85 | 21 / 22 |
| Agents with confidence < 0.85 | 1 (`acceptance_criteria` — 0.75) |
| Agents requiring retry | 1 (`api_specification` — TPM 413 error) |
| Total LLM calls | 23 (22 agents + 1 retry) |
| Slowest agent | `api_specification` — 103.9 s (2 attempts) |
| Fastest agent | `requirement_extraction` — 3.8 s |
| Agents flagged by hallucination_validation | 2 fabricated APIs, 2 ID mismatches, 2 false claims |
| Cross-agent validation findings | 13 across 2 checks |
| Parsed JSON on first try | 21 / 22 |

---

## Per-Agent Detail

### 01 · `requirement_extraction`
| Field | Value |
|---|---|
| Order | 0 |
| Duration | **3.8 s** |
| Attempts | 1 |
| Confidence | **0.90** 🟢 |
| Risks | 1 | Assumptions | 1 |
| Content keys | `actors`, `functional`, `modules`, `non_functional`, `open_questions` |
| Parsed OK | ✅ |
| Error | None |

**Observations:** Fastest agent in the pipeline. Full coverage of all five expected keys, including `open_questions` which correctly surfaces the three ambiguous items from the requirements (viewer burndown scope, attachment size, single active sprint confirmation). Confidence is appropriately high — the source document is dense and well-structured.

**Improvements:**
- The context window receives the full requirements text (5,692 chars); with only 5 chunks, truncation is not yet a problem but will be on larger documents. Consider adding a per-section extraction pass to ensure every numbered section maps to at least one requirement entry.
- `open_questions` are extracted but never consumed downstream (e.g. `ambiguity_detection` doesn't get a dedicated feed from them). A routing step that sends `open_questions` directly into `ambiguity_detection`'s user payload would improve coverage.

---

### 02 · `requirement_classification`
| Field | Value |
|---|---|
| Duration | **4.7 s** |
| Attempts | 1 |
| Confidence | **0.90** 🟢 |
| Content keys | `classified` |

**Observations:** Confident and fast. The `classified` list correctly enriches every requirement with `category` and `priority` fields as required by the schema hint. No truncation note in payload.

**Improvements:**
- Content key is a single flat list — no sub-grouping by category. Adding a secondary `by_category` index to the output would make downstream agents (e.g. `sprint_planning`, `compliance`) easier to filter without re-parsing the entire classified list.
- Priority distribution is not validated. A post-processing assertion that verifies P0 items cover security, auth, and data protection requirements would catch misclassifications early.

---

### 03 · `ambiguity_detection`
| Field | Value |
|---|---|
| Duration | **46.8 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Content keys | `items` |

**Observations:** Generic `items` key rather than a structured list like `ambiguities`. The 46 s runtime for a single LLM call on llama-3.1-8b-instant is unusually high — likely a Groq cold-start or rate-limit queue event. No retry was triggered, so the call eventually succeeded.

**Improvements:**
- **Content schema:** The schema hint says `items` (generic fallback). Override `_AGENT_HINTS` with a specific key requirement, e.g. `ambiguities` (list of `{id, section, description, resolution_suggestion}`), to give downstream agents structured data rather than a flat text list.
- **Latency:** 46 s is ~12× the fast agents. Add a per-agent `max_wait_seconds` alarm in the orchestrator log so high-latency agents are flagged in real time.
- **Coverage:** The agent receives prior outputs from `requirement_extraction` and `requirement_classification` but not the raw `open_questions` list. Explicitly injecting `open_questions` would tie ambiguity detection directly to the known unknowns.

---

### 04 · `missing_requirement`
| Field | Value |
|---|---|
| Duration | **13.8 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Content keys | `findings` |

**Observations:** Good output shape. The `findings` key is specific and structured. Runtime is reasonable.

**Improvements:**
- Findings should cross-reference the requirement IDs produced by `requirement_extraction` (e.g. `missing_for: [REQ-4.x, ...]`) so `traceability` can pick them up. Currently missing requirements exist in isolation.
- The agent's purpose is to find gaps, but it does not check against a known SDLC completeness checklist. Embedding a minimal checklist (e.g. "are error codes defined? is rate limiting specified? is audit logging present?") into the system prompt would increase recall.

---

### 05 · `conflict_detection`
| Field | Value |
|---|---|
| Duration | **53.5 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Content keys | `conflicts` |
| Payload size | 10,314 chars |

**Observations:** Produced 3 conflicts. However, one of them (`REQ-4.1.1 vs REQ-4.1.2`) is a weak pseudo-conflict: "invite pending 7 days may not be enough for Org Admin to create an org profile" is not a true contradiction — it's a design-time concern. The detection is noisy.

**Improvements:**
- **False positive rate:** The model conflates timing concerns with logical contradictions. Add a negative example to the system prompt demonstrating what is NOT a conflict (sequential steps are not conflicts, optional phases are not conflicts).
- **Severity calibration:** All 3 conflicts are rated `MEDIUM`. Introduce a scoring rubric in the system prompt: `HIGH` = mutually exclusive requirements that cannot both be implemented; `MEDIUM` = ambiguous overlap; `LOW` = ordering or timing concern.
- **Latency:** 53.5 s is excessive for conflict detection. The payload at 10k chars is borderline — consider capping `max_prior_agents` to 3 for this agent since it only needs `requirement_extraction` and `requirement_classification`.

---

### 06 · `user_story_generation`
| Field | Value |
|---|---|
| Duration | **41.8 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Content keys | `stories` |

**Observations:** Correct output shape. Stories use `as_a`, `i_want`, `so_that` format per the artifact hint.

**Improvements:**
- Story IDs are `US-1`, `US-2` etc. but `hallucination_validation` later flags `AC-1` as not referencing a valid story ID — indicating the acceptance criteria agent used a different ID namespace (`AC-*`) without linking back to `US-*`. Story IDs must be propagated more explicitly into downstream agents.
- The agent runs with a `prompt_budget_note` (context truncated). At 41 s runtime, it is getting a large context window. Apply the same `max_context_chars: 3000` override that `acceptance_criteria` has to reduce token pressure and latency.
- No "epic" grouping is present in the stories. Adding an `epic_id` field to each story would make `task_decomposition` and `sprint_planning` better structured.

---

### 07 · `task_decomposition`
| Field | Value |
|---|---|
| Duration | **52.7 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Content keys | `tasks` |

**Observations:** Schema-compliant output with `id`, `title`, `type`, `component`, `depends_on`. However, `sprint_planning` downstream only references `TASK-1` through `TASK-4` in its raw response, suggesting the full task list was truncated when passed to sprint planning due to `max_prior_output_chars`.

**Improvements:**
- Tasks should include explicit `story_points` at decomposition time so `sprint_planning` doesn't have to estimate them. The sprint plan currently shows `story_points` per item (3–6 pts) but these appear invented rather than sourced from decomposition.
- `depends_on` links are present but not validated by `dependency_mapping`. The two agents should use the same ID scheme and explicitly cross-reference.
- Consider splitting `task_decomposition` into two narrower agents: one for backend tasks, one for frontend/infra. This reduces per-call token load and allows parallel execution with LangGraph.

---

### 08 · `api_specification` ⚠️
| Field | Value |
|---|---|
| Duration | **103.9 s** |
| Attempts | **2** ⚠️ |
| Retry reason | `APIStatusError 413: Request too large — TPM limit exceeded` |
| Confidence | **0.85** 🟡 |
| Content keys | `endpoints` |
| Payload size | 11,950 chars |

**Observations:** This is the only agent that hit a Groq TPM (tokens-per-minute) 413 error, causing a full retry with exponential backoff. The payload at 11,950 chars is the largest in the pipeline at this point (order 7). Raw response was truncated in the log (>4000 chars) meaning the endpoint list is large.

**Improvements:**
- **Root cause fix:** The context override for this agent (`_AGENT_CONTEXT_OVERRIDES`) is not set. Add an entry: `"api_specification": {"max_context_chars": 3000, "max_prior_agents": 4}` to reduce payload size below the TPM limit on free-tier Groq.
- **Endpoint completeness:** The raw response shows only `POST` endpoints. No `GET`, `PUT`, `DELETE`, or pagination endpoints appear in the truncated excerpt. A schema validator post-processing step should assert that each resource has at minimum a `GET` and `POST` pair.
- **Version coverage:** Endpoints correctly start with `/v1/` per the hint. Add a `deprecated` and `version` field to future-proof the spec.
- **Retry cost:** The 413 retry added ~50 s to the run. Proactive payload size checks before the LLM call (warn if `user_payload_size_chars > 10000`) would allow the orchestrator to auto-trim before the error.

---

### 09 · `database_schema`
| Field | Value |
|---|---|
| Duration | **50.0 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Risks | **4** (highest so far) |
| Content keys | `tables` |

**Observations:** 4 risks flagged — the highest pre-validation agent. Hallucination validator also notes "missing foreign key constraints between tables" and "missing audit and token tables," confirming the agent's self-reported risks are valid.

**Improvements:**
- Risk flagging is self-aware ("Missing foreign key constraints", "Normalization issues") but the content doesn't enforce these. Add a post-processing schema assertion that verifies every table with a foreign-key relationship also has a `references` field.
- The demo.txt requires audit logs (tamper-evident, 2 years). An `audit_log` table should be mandated in the system prompt for this agent class.
- Add a `jwt_tokens` / `refresh_tokens` table to the mandatory tables list — the auth spec requires JWT + refresh token management and the schema agent missed it.

---

### 10 · `security_review`
| Field | Value |
|---|---|
| Duration | **51.3 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Content keys | `findings` |

**Observations:** Output shape is correct (`findings` with `severity`, `threat`, `mitigation`). The demo.txt has a rich security surface (JWT, RBAC, GDPR, AES-256, TLS 1.2+, account lockout, webhook HMAC signing) — 51 s suggests the model is working through a dense context.

**Improvements:**
- Link findings to specific requirement IDs (e.g. `"requirement_ids": ["REQ-3.1", "REQ-8.1"]`) so `traceability` and `compliance` can use them directly.
- The system prompt should require a `cvss_score` or at minimum a `severity ∈ {critical, high, medium, low, info}` scale. Ensure `hallucination_validation` checks that no security finding invents a threat not traceable to the requirements.
- Account lockout (5 failed logins / 15 min) and audit log tamper-evidence are explicitly mentioned in the source but may be buried in a large context. Use a per-agent RAG retrieval query (semantic search against the Chroma index) to surface auth-specific chunks rather than passing the full context.

---

### 11 · `scalability_architecture`
| Field | Value |
|---|---|
| Duration | **38.9 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Risks | 4 |
| Content keys | `components`, `data_flow`, `scaling_notes` (truncated in table) |

**Observations:** Correct multi-key output including all three required keys from the artifact hint. Risks are elevated (4), reflecting the ambitious non-functional requirements (99.5% uptime, 10k orgs, 500k users, EKS deployment).

**Improvements:**
- `scaling_notes` should reference the specific NFRs (p95 latency < 300ms, 10,000 orgs) with concrete capacity numbers, not generic advice. Add a directive in the system prompt: "For each scaling note, cite the source NFR ID and propose a specific capacity target or technology."
- The agent doesn't consume `database_schema` output — it should. Horizontal scaling decisions depend on knowing which tables are hot-path reads.

---

### 12 · `acceptance_criteria` ⚠️
| Field | Value |
|---|---|
| Duration | **41.0 s** |
| Attempts | 1 |
| Confidence | **0.75** 🔴 (only sub-threshold agent) |
| Risks | 4 (self-reported: "Missing negative conditions", "Incomplete flows", "Vague rules", "Criteria without story link") |
| Content keys | `items` (wrong — should be `criteria`) |

**Observations:** This is the only agent below the 0.8 confidence threshold and the model itself flags all four risk categories. The output uses `items` as the content key instead of `criteria` — the schema hint says `criteria` but the model defaulted to the generic fallback. The scenarios are Access Control-heavy (AC-1 through AC-10) but miss entire SDLC flows like sprint close, burndown, notifications, and CSV export.

**Improvements:**
- **Content key mismatch:** The schema hint (`content should include "criteria"`) is a soft suggestion, not a strict assertion. Change the hint to `content MUST include "criteria"` and add it to `_AGENT_HINTS` with explicit required fields: `{id, story_id, given, when, then, negative_scenario}`.
- **Story linking:** The agent produces `AC-*` IDs without linking to `US-*` story IDs. The system prompt must mandate `story_id` as a required field, referencing the exact IDs from `user_story_generation`.
- **Coverage breadth:** Criteria are concentrated on org/user access flows. Inject the full list of user story IDs into the prompt budget and instruct the agent to produce at least one criterion per story.
- **LangGraph routing:** With confidence 0.75, this agent is below the `CONFIDENCE_THRESHOLD=0.6` (default) but above a stricter threshold. Consider lowering the threshold to 0.80 or enabling `USE_LANGGRAPH=true` so this agent routes to `feedback_refinement`.

---

### 13 · `effort_estimation`
| Field | Value |
|---|---|
| Duration | **40.2 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Risks | 6 (highest in pipeline) |
| Content keys | `estimates` |

**Observations:** 6 risks is the highest risk count in the pipeline, reflecting genuine uncertainty in effort estimation without a known team composition or velocity baseline.

**Improvements:**
- The system prompt should accept a `velocity_baseline` from the user payload (e.g. "team of 4 devs, 2-week sprints") and use it to bound story point estimates. The demo.txt says "5 projects, 20 users for MVP" — this can be used as a scoping constraint.
- Estimates use `points_or_days` which is ambiguous. Standardise to `story_points` and `days_estimate` as separate fields for cleaner consumption by `sprint_planning`.
- Risk propagation: effort estimation risks (6 risks) are blindly copied into `sprint_planning`'s risk list, inflating it to 6 entries. The risks should be de-duplicated before cross-agent propagation.

---

### 14 · `test_case_generation`
| Field | Value |
|---|---|
| Duration | **37.1 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Content keys | `test_cases` |

**Observations:** Correct schema. Test cases use the standard artifact hint format (`id`, `type`, `steps`, `expected`).

**Improvements:**
- `hallucination_validation` flags `TC-1 does not reference a valid acceptance criterion ID`. This means test cases are not linked back to `AC-*` IDs. Add `acceptance_criterion_id` as a required field in `_AGENT_HINTS["test_case_generation"]`.
- Test type distribution is unknown (unit/integration/e2e/performance). Add a `type_summary` key to the output that lists counts by type so quality gates can assert minimum coverage of each type.
- Performance/load test cases are required by the demo.txt success criteria ("50 concurrent users per org, error rate < 1%") but likely absent from a default run. Make load test scenarios explicit in the system prompt.

---

### 15 · `dependency_mapping`
| Field | Value |
|---|---|
| Duration | **46.0 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Risks | 6 |
| Content keys | `dependencies` |

**Observations:** Matches the task decomposition output's `depends_on` links. 6 risks reflect real inter-service dependencies (auth before RBAC, schema before API, etc.).

**Improvements:**
- No cycle-detection is performed. Add a post-processing graph check (topological sort) to detect circular dependencies between tasks before sprint planning.
- The agent should output a `critical_path` list — the sequence of tasks with no slack — to inform sprint planning capacity allocation.

---

### 16 · `hallucination_validation`
| Field | Value |
|---|---|
| Duration | **42.5 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Content keys | `fabricated_apis`, `false_claims`, `id_mismatches` |
| Payload size | 13,498 chars (largest in pipeline) |

**Observations:** Correctly structured. Flagged real issues:
- **Fabricated APIs:** `/v1/.../sprints/{id}/close` and `/v1/.../backlog/{id}/duplicate` — endpoints present in `api_specification` output but not traceable to requirements.
- **ID mismatches:** `AC-1` and `TC-1` don't reference valid upstream IDs (the `story_id` / `criterion_id` linking problem confirmed above).
- **False claims:** "pagination max 1000" (requirements say max 100) and "MFA for all users" (Phase 2 only).

**Improvements:**
- The payload at 13.5k chars is the largest in the pipeline and approaching the Groq free-tier limit. This agent is the strongest candidate for an `_AGENT_CONTEXT_OVERRIDES` entry — add `"hallucination_validation": {"max_context_chars": 4000, "max_prior_agents": 6}`.
- The `fabricated_apis` finding should automatically feed back as a rejection signal to `api_specification` in a LangGraph routing loop rather than being a passive observation.
- False claims around pagination limits (`max 100` vs `max 1000`) indicate the agent is reading a truncated or summarised version of the API spec. Pass the raw `api_specification` content untruncated (use `max_prior_output_chars` override for this specific prior agent).

---

### 17 · `traceability`
| Field | Value |
|---|---|
| Duration | **32.0 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Content keys | `links` |

**Observations:** Links use `REQ-*` IDs from `requirement_extraction`. The 32 s runtime is among the better latencies for a mid-pipeline agent.

**Improvements:**
- `links` entries should include `test_ids` (from `test_case_generation`) but this field may be missing given the test case ID linkage problem. Add a post-run validator that checks every `requirement_id` in `traceability.links` has at least one entry in each of `story_ids`, `task_ids`, `api_ids`, and `test_ids`.
- The traceability matrix is not exported as a standalone CSV artifact. A dedicated export pass would make it directly usable for audit purposes.

---

### 18 · `sprint_planning`
| Field | Value |
|---|---|
| Duration | **51.9 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Risks | 6 (inherited noise from `effort_estimation`) |
| Assumptions | 4 (duplicated entries) |
| Content keys | `sprints` |

**Observations:** Only 2 sprints planned (`Sprint 1`: 3 tasks, `Sprint 2`: 1 task), covering only 4 of the many tasks from `task_decomposition`. The context at 12,428 chars with `max_prior_agents=4` means most of the task list was truncated before reaching this agent.

**Improvements:**
- **Critical gap:** The sprint plan is severely incomplete because `task_decomposition` output was truncated to fit the prior-agent budget. Increase `max_prior_output_chars` for this specific agent or use a targeted retrieval approach (query Chroma for tasks by component).
- **Duplicate risks/assumptions:** The raw response shows identical strings in both `risks` and `assumptions` arrays, e.g. "MFA will be implemented in Phase 2" appears twice in assumptions. Add a deduplication step in `_build_agent_output` or in the orchestrator before persisting.
- **40-point sprint cap:** The system prompt mentions a 40-point cap but Sprint 1 only has 12 points and Sprint 2 has 6 — nowhere near capacity. The agent should be instructed to fill sprints to capacity before creating a new sprint.

---

### 19 · `team_allocation`
| Field | Value |
|---|---|
| Duration | **42.3 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Content keys | `assignments` |

**Observations:** Correctly uses placeholder owner names per the hint ("only when team input is empty"). Role set covers Developer, QA, DevOps, PM, Designer as required.

**Improvements:**
- Assignments reference `task_id` but since `sprint_planning` only surfaced 4 tasks, team allocation is also severely incomplete. Same root cause as sprint planning (task list truncation).
- `estimated_hours` per assignment is required by `_AGENT_HINTS["team_allocation"]` but may be missing from the truncated context. Add an assertion in the cross-agent validator.
- When `team` input is empty (as in this run), the agent invents placeholder names. The system prompt should produce names like `"Developer-1"` consistently rather than potentially varying.

---

### 20 · `devops_recommendation`
| Field | Value |
|---|---|
| Duration | **43.3 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Risks | 3 |
| Content keys | `recommendations` |

**Observations:** Correct schema with `area`, `action`, `priority` per the artifact hint.

**Improvements:**
- The demo.txt explicitly mentions AWS EKS, GitHub Actions, and LaunchDarkly. Recommendations should directly reference these and provide concrete action items (e.g. Helm chart structure, GitHub Actions workflow stages).
- Priority field values should be constrained to `high/medium/low` — add an enum assertion in the schema hint.
- Add a `cost_estimate` or `effort_points` to each recommendation to allow prioritisation alongside the task backlog.

---

### 21 · `compliance`
| Field | Value |
|---|---|
| Duration | **34.9 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Content keys | `controls` |

**Observations:** The previous smoke-run report confirmed regulations: GDPR, PCI-DSS, PII handling, SOC2, WCAG 2.1 AA — all present in the source doc. HIPAA correctly absent.

**Improvements:**
- `status ∈ {compliant, gap, n_a}` is correctly used per the hint. However, the agent should produce an explicit `gap_summary` field listing all items with `status: gap` for quick review.
- GDPR requires "right to erasure within 30 days" — confirm the database schema has a soft-delete or erasure mechanism. This cross-agent check doesn't happen automatically; add it to the cross-agent validator.
- PCI-DSS is listed as a regulation but the demo.txt says "no storage of payment card data (Stripe Checkout only)" — this should produce `status: n_a` for PCI-DSS card storage controls, not `compliant`.

---

### 22 · `export_integration`
| Field | Value |
|---|---|
| Duration | **42.0 s** |
| Attempts | 1 |
| Confidence | **0.85** 🟡 |
| Content keys | `deliverables` |

**Observations:** Last agent in the pipeline. Produces a `deliverables` list summarising format, destination, and payload summary.

**Improvements:**
- This agent produces a metadata description of exports but does not actually trigger the export endpoints. Consider replacing this with a no-LLM step that calls `export_json`/`export_csv`/`export_pdf` directly from the orchestrator, since there is no intelligence needed here.
- The 42 s LLM call to describe export formats is wasteful. If kept as an LLM agent, the system prompt should be much shorter (just list the available formats and destinations from settings).

---

## Pipeline-Level Observations

### Timing Hotspots

| Agent | Duration | Issue |
|---|---|---|
| `api_specification` | 103.9 s | TPM 413 retry — add context override |
| `conflict_detection` | 53.5 s | Payload too large, reduce prior agents |
| `task_decomposition` | 52.7 s | Single-pass for all task types |
| `sprint_planning` | 51.9 s | Truncated task context |
| `security_review` | 51.3 s | Dense security surface |
| `database_schema` | 50.0 s | No context override set |

Total wall-clock: **~921 s** (15 min). With parallelism on independent agent groups, this could be cut to ~5 min.

### Cross-Agent Validation (13 findings)

The pipeline reported 13 findings across 2 validation checks:
1. `hallucination_validation` confirmed: 2 fabricated endpoints, 2 ID mismatches (`AC-1`/`TC-1`), 2 false claims.
2. The second check (likely the cross-agent ID validator in `pipeline.py`) found additional mismatches between requirement IDs in `traceability` vs. the IDs produced by `requirement_extraction`.

The root cause of most ID mismatch findings is a lack of a shared ID registry between agents. Each agent re-creates its own ID namespace (`US-*`, `AC-*`, `TC-*`, `TASK-*`) without asserting consistency against upstream outputs.

### Risk/Assumption Duplication

`sprint_planning` and `team_allocation` both contain duplicated risk and assumption strings inherited from `effort_estimation`. A deduplication pass in `_build_agent_output` or a utility in the executor would eliminate this noise.

---

## Prioritised Improvement Roadmap

### P0 — Fix Now (correctness/reliability)

1. **Add `_AGENT_CONTEXT_OVERRIDES` for `api_specification`** (`max_context_chars: 3000, max_prior_agents: 4`) to prevent the recurring TPM 413 error on Groq free tier.
2. **Fix `acceptance_criteria` schema hint** — change `content should include "criteria"` to a strict `_AGENT_HINTS` entry with `content MUST include "criteria"` and mandatory `story_id` field.
3. **Add `story_id` to `acceptance_criteria` and `criterion_id` to `test_case_generation`** system prompts to resolve the ID mismatch flagged by `hallucination_validation`.

### P1 — Quality (output completeness)

4. **Feed `open_questions` from `requirement_extraction` directly into `ambiguity_detection`** user payload.
5. **Add `story_points` to `task_decomposition` output** and consume them in `sprint_planning` rather than re-estimating.
6. **Increase `max_prior_output_chars`** for `sprint_planning` and `team_allocation` or add per-agent RAG retrieval so the full task list is available.
7. **Add deduplication logic** to strip repeated risk/assumption strings across agent boundaries.
8. **Add an `audit_log` and `jwt_tokens` table** requirement to the `database_schema` system prompt.

### P2 — Performance (latency)

9. **Enable parallel execution** for independent agent groups via LangGraph `Send()` — groups like `{ambiguity_detection, missing_requirement}`, `{security_review, scalability_architecture}`, and `{test_case_generation, acceptance_criteria}` have no data dependency and can run concurrently.
10. **Add a proactive payload size check** before every LLM call — warn at 9,000 chars and auto-trim prior outputs at 11,000 chars to prevent TPM 413 errors.
11. **Replace `export_integration` LLM call** with a direct orchestrator step calling the exporter functions — saves ~42 s and a token budget.

### P3 — Observability

12. **Log confidence trend per agent** across runs to detect regressions (if confidence for an agent drops run-over-run, alert).
13. **Add a `critical_path` output** to `dependency_mapping` and feed it directly into `sprint_planning`.
14. **Lower `CONFIDENCE_THRESHOLD` to 0.80** (from 0.6) so `acceptance_criteria` (0.75) routes to `feedback_refinement` when `USE_LANGGRAPH=true`.
15. **Add a cycle-detection pass** on `dependency_mapping` output before sprint planning begins.
