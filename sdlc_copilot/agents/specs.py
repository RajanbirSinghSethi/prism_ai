from dataclasses import dataclass

from sdlc_copilot.models import ArtifactType


@dataclass(frozen=True)
class AgentSpec:
    id: str
    title: str
    purpose: str
    responsibilities: tuple[str, ...]
    edge_cases: tuple[str, ...]
    artifact_type: ArtifactType | str


AGENT_SPECS: tuple[AgentSpec, ...] = (
    AgentSpec("document_ingestion", "Document Ingestion Agent", "Accept requirement inputs into the SDLC system.", ("OCR/PDF parsing guidance", "metadata extraction", "format normalization"), ("corrupted PDFs", "empty files", "scanned images", "unsupported formats", "multi-language docs"), "ingestion"),
    AgentSpec("text_cleaning", "Text Cleaning Agent", "Clean noisy requirement data.", ("deduplicate content", "normalize text", "remove headers and footers"), ("OCR garbage", "HTML artifacts", "broken formatting", "inconsistent bullets"), "cleaning"),
    AgentSpec("chunking_context", "Chunking & Context Agent", "Prepare requirements for LLM processing.", ("semantic chunking", "embedding strategy", "context preservation"), ("token overflow", "duplicate chunks", "broken context", "cross-page references"), "context"),
    AgentSpec("planner_orchestrator", "Planner / Orchestrator Agent", "Route workflow between agents.", ("agent selection", "execution management", "retries", "aggregation"), ("agent failures", "infinite loops", "timeouts", "contradictory outputs"), "orchestration"),
    AgentSpec(
        "requirement_extraction",
        "Requirement Extraction Agent",
        "Convert raw text into structured engineering entities using source-section-aligned IDs.",
        (
            "extract actors", "actions", "modules", "dependencies", "workflows",
            "extract ALL numbered sections (one entry minimum per subsection)",
            "preserve the source section number as ID prefix (e.g. REQ-3.1, REQ-4.1.1)",
            "include authentication, RBAC, integration, and open question requirements",
        ),
        ("ambiguous actors", "nested workflows", "implicit logic", "poorly written requirements", "skipped sections", "untracked open questions"),
        ArtifactType.REQUIREMENTS,
    ),
    AgentSpec(
        "requirement_classification",
        "Requirement Classification Agent",
        "Enrich extracted requirements with category and priority — do not re-emit them.",
        (
            "tag each requirement with category (functional|security|performance|compliance|ux|integration|data)",
            "assign priority P0-P3 based on MVP success criteria",
            "preserve original requirement IDs from requirement_extraction",
            "do NOT duplicate items — enrich them",
        ),
        ("mixed categories", "hidden NFRs", "incorrect classifications", "re-emitting extraction verbatim"),
        ArtifactType.REQUIREMENTS,
    ),
    AgentSpec(
        "ambiguity_detection",
        "Ambiguity Detection Agent",
        "Detect unclear, vague, or unmeasurable requirements.",
        (
            "vague terms", "weak verbs", "missing thresholds",
            "flag every explicit open question in the source",
            "flag undefined acronyms and implicit terms",
        ),
        ("subjective wording", "undefined acronyms", "conflicting interpretations", "missing measurement units"),
        ArtifactType.RISKS,
    ),
    AgentSpec(
        "missing_requirement",
        "Missing Requirement Agent",
        "Identify incomplete requirement details that block implementation.",
        (
            "missing validations", "permissions", "retry logic", "workflows",
            "session invalidation on deactivation",
            "token refresh and rotation",
            "rate-limit error response shape",
            "invite expiry cleanup jobs",
        ),
        ("edge flows", "audit rules", "error handling", "background jobs", "data lifecycle"),
        ArtifactType.RISKS,
    ),
    AgentSpec(
        "conflict_detection",
        "Conflict Detection Agent",
        "Detect contradictions between two or more requirements — NOT missing items.",
        (
            "find pairs of requirements that contradict each other",
            "detect duplicate logic expressed differently",
            "find inconsistent workflows across sections",
            "return an empty list when no real contradictions exist",
        ),
        (
            "semantic conflicts", "version mismatches", "cross-document contradictions",
            "do NOT list missing requirements — that belongs to missing_requirement",
        ),
        ArtifactType.RISKS,
    ),
    AgentSpec(
        "user_story_generation",
        "User Story Generation Agent",
        "Generate one Agile story per distinct actor-action pair.",
        (
            "user stories", "personas", "business value",
            "cover every actor including Super Admin and Viewer",
            "include integration stories (webhooks, GitHub)",
            "add an acceptance_hint field per story",
        ),
        ("missing actors", "multiple personas", "complex user journeys", "missed integration stories"),
        ArtifactType.STORIES,
    ),
    AgentSpec(
        "task_decomposition",
        "Task Decomposition Agent",
        "Generate engineering tasks; every task must declare a type.",
        (
            "frontend tasks", "backend tasks", "API tasks", "DB tasks", "QA tasks", "DevOps tasks",
            "each task must have id, title, type (frontend|backend|api|db|qa|devops), component, depends_on",
            "reference originating story id in depends_on when applicable",
        ),
        ("circular dependencies", "duplicate tasks", "unrealistic decomposition", "missing QA or DevOps tasks"),
        ArtifactType.TASKS,
    ),
    AgentSpec(
        "acceptance_criteria",
        "Acceptance Criteria Agent",
        "Define Gherkin-style validation rules with positive AND negative paths.",
        (
            "business conditions", "success scenarios", "negative scenarios",
            "reference story_id from user_story_generation",
            "use Given/When/Then format in the scenario field",
        ),
        ("missing negative conditions", "incomplete flows", "vague rules", "criteria without story link"),
        ArtifactType.ACCEPTANCE_CRITERIA,
    ),
    AgentSpec(
        "test_case_generation",
        "Test Case Generation Agent",
        "Generate QA artifacts derived from acceptance criteria.",
        (
            "positive tests", "negative tests", "boundary tests", "regression tests", "Gherkin",
            "each test must reference an acceptance criterion id",
        ),
        ("invalid inputs", "permission failures", "concurrency", "timeouts", "tests with no criterion link"),
        ArtifactType.TEST_CASES,
    ),
    AgentSpec(
        "api_specification",
        "API Specification Agent",
        "Generate backend API contracts with full method, schema, and security metadata.",
        (
            "endpoints", "request schemas", "response schemas", "status codes",
            "every path starts with /v1/",
            "declare auth_required and idempotency_key_required per endpoint",
        ),
        ("broken contracts", "missing validation", "wrong HTTP methods", "missing version prefix"),
        ArtifactType.API_SPEC,
    ),
    AgentSpec(
        "database_schema",
        "Database Schema Agent",
        "Generate storage architecture including join, audit, and token tables.",
        (
            "tables", "relationships", "indexes", "constraints",
            "many-to-many join tables (e.g. organization_memberships)",
            "audit_log table for tamper-evident records",
            "refresh_tokens table when JWT refresh is in scope",
        ),
        ("missing FKs", "normalization issues", "scalability bottlenecks", "missing audit/token tables"),
        ArtifactType.DATABASE_SCHEMA,
    ),
    AgentSpec(
        "security_review",
        "Security Review Agent",
        "Detect security risks across auth, data, and integration surfaces.",
        ("auth", "RBAC", "encryption", "uploads", "secrets", "rate limit bypass", "webhook signature validation"),
        ("plain-text passwords", "token leakage", "insecure uploads", "injection risks", "missing HMAC verification"),
        ArtifactType.SECURITY_REVIEW,
    ),
    AgentSpec(
        "scalability_architecture",
        "Scalability & Architecture Agent",
        "Recommend a scalable system design with explicit data flow and scaling notes.",
        ("caching", "queues", "load balancing", "service boundaries", "components diagram (textual)", "data_flow narrative"),
        ("SPOF", "traffic bottlenecks", "missing cache strategy", "scaling assumptions"),
        ArtifactType.ARCHITECTURE,
    ),
    AgentSpec(
        "effort_estimation",
        "Effort Estimation Agent",
        "Estimate engineering effort referencing concrete task IDs.",
        (
            "story points (Fibonacci 1-13)", "timelines in calendar days", "sprint estimates",
            "reference task_id values from task_decomposition",
        ),
        ("unrealistic deadlines", "ignored dependencies", "underestimated infra work", "estimates without task link"),
        ArtifactType.ESTIMATION,
    ),
    AgentSpec(
        "hallucination_validation",
        "Hallucination Validation Agent",
        "Cross-check generated artifacts against the source requirements.",
        (
            "fake APIs", "invalid logic", "impossible architectures",
            "compare api_specification endpoints to requirement modules",
            "verify story and task IDs are defined in their source agent",
        ),
        (
            "fabricated assumptions", "hallucinated dependencies", "inconsistent outputs",
            "do NOT flag legitimate technologies mentioned in the requirements as hallucinations",
        ),
        "validation",
    ),
    AgentSpec(
        "traceability",
        "Traceability Agent",
        "Maintain end-to-end SDLC traceability using the exact requirement IDs from requirement_extraction.",
        (
            "map requirements to stories/tasks/APIs/tests", "coverage gaps",
            "use the EXACT requirement IDs from requirement_extraction (e.g. REQ-3.1)",
            "flag any requirement with no downstream artifact",
        ),
        ("orphan tasks", "missing test coverage", "duplicate mappings", "invented ID schemes"),
        ArtifactType.TRACEABILITY,
    ),
    AgentSpec("feedback_refinement", "Feedback & Refinement Agent", "Support human-in-the-loop governance.", ("edits", "selective regeneration", "approvals", "rollback"), ("conflicting edits", "accidental overwrite", "invalid refinements"), "feedback"),
    AgentSpec(
        "sprint_planning",
        "Sprint Planning Agent",
        "Convert tasks into sprint plans honouring dependencies and capacity.",
        (
            "sprint grouping", "dependency sequencing", "workload balancing",
            "reference task IDs from task_decomposition",
            "cap each sprint at 40 story points (assume 2-week sprints)",
        ),
        ("sprint overload", "blocked tasks", "dependency conflicts", "items without task_id"),
        ArtifactType.SPRINT_PLAN,
    ),
    AgentSpec(
        "team_allocation",
        "Team Allocation & Jira Assignment Agent",
        "Assign tasks across roles using team input when provided.",
        (
            "roles (Developer|QA|DevOps|PM|Designer)", "availability", "workload", "capacity", "effort estimates",
            "task_id must match task_decomposition IDs",
            "use placeholder owner names only when team input is empty",
        ),
        ("resource overload", "unavailable engineers", "skill mismatch", "overlapping schedules", "free-text task ids"),
        ArtifactType.TEAM_ALLOCATION,
    ),
    AgentSpec(
        "export_integration",
        "Export & Integration Agent",
        "Deliver outputs to external systems with concrete payload mappings.",
        (
            "Jira", "GitHub", "CSV", "PDF", "Confluence",
            "map task_decomposition tasks to Jira issue payloads",
            "include webhook payload schema",
            "include org admin data export bundle",
        ),
        ("invalid payloads", "API limits", "schema mismatch", "auth failures"),
        ArtifactType.EXPORT,
    ),
    AgentSpec(
        "dependency_mapping",
        "Dependency Mapping Agent",
        "Map execution dependencies between tasks and components.",
        ("dependency graphs", "blockers", "critical paths", "reference task_ids when mapping task dependencies"),
        ("circular dependencies", "hidden blockers", "invalid ordering"),
        "dependencies",
    ),
    AgentSpec(
        "devops_recommendation",
        "DevOps Recommendation Agent",
        "Suggest CI/CD, containerisation, observability, and rollback strategies.",
        ("CI/CD", "Docker", "monitoring", "deployment recommendations", "rollback strategy"),
        ("missing rollback", "environment mismatch", "deployment failures", "no observability"),
        ArtifactType.DEVOPS,
    ),
    AgentSpec(
        "compliance",
        "Compliance Agent",
        "Validate ONLY the regulations explicitly mentioned in the requirements.",
        (
            "GDPR", "HIPAA", "PCI-DSS", "SOC2", "PII handling",
            "include only regulations cited in the requirements text",
            "every control must cite evidence_from_requirements",
        ),
        (
            "missing encryption", "audit gaps", "improper storage", "compliance violations",
            "do NOT assert regulations not mentioned in the source",
        ),
        ArtifactType.COMPLIANCE,
    ),
)


AGENTS_BY_ID = {agent.id: agent for agent in AGENT_SPECS}
