---
name: python-genai-prompt-engineering
description: >-
  Guides Python code for LLM applications: prompt design, API integration,
  structured outputs, tool-calling, RAG, and evaluation. Use when building GenAI
  features in Python, optimizing prompts, integrating LLM APIs (OpenAI-compatible
  or others), or implementing prompt engineering, agents, or RAG workflows.
---

# Python GenAI & Prompt Engineering

Apply when writing or refactoring Python that calls LLMs, builds prompts, or evaluates model behavior. Prefer project libraries if already present (e.g. LangChain, LiteLLM, instructor); otherwise use clear, minimal patterns below.

## Principles

1. **Separate concerns**: System vs user content; static instructions vs dynamic data. Never concatenate untrusted user text into system prompts without delimiters and intent checks.
2. **Specify format up front**: If the model must return JSON, YAML, or fields, say so explicitly and give a schema or example shape—not vague “return structured data.”
3. **Few-shot when behavior is subtle**: 2–5 short input/output pairs beat long prose for classification, extraction, and tone.
4. **Reduce ambiguity**: Define terms, edge cases, and refusal behavior (“If unsure, say X”).
5. **Token budget**: Shorter prompts with clear structure; avoid repeating the same rules in multiple places.

## Python patterns

### Call shape (OpenAI-compatible)

Use typed parameters, timeouts, and explicit `response_format` when the SDK supports JSON mode:

```python
from openai import OpenAI

client = OpenAI()
completion = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
    temperature=0.2,
    timeout=60,
)
text = completion.choices[0].message.content
```

Load API keys from environment (`os.environ` / `python-dotenv`); never hardcode secrets.

### Structured output

- **Native JSON / schema**: Prefer provider-supported JSON or strict schema when available.
- **Libraries**: Use `instructor`, `langchain` output parsers, or Pydantic models to validate and repair—validate in code, not only in the prompt.

### Prompts as data

Store prompts in modules or template files; version them (git) and name variables clearly (`SYSTEM_RAG_ANSWER`, `USER_EXTRACT_ENTITIES`). For templates, use `str.format` or Jinja2 with explicit allowed variables—avoid f-strings mixing untrusted content without escaping boundaries.

### RAG

- Retrieval: chunk size/overlap and metadata filters matter as much as the LLM prompt.
- Prompt: Instruct the model to use **only** provided context, cite or quote when required, and say when context is insufficient.
- Grounding: Pass retrieved chunks in a clearly delimited block (e.g. `<context>...</context>`).

### Tools / function calling

Define tools with tight JSON schemas; descriptions are part of the prompt—write them for the model. After a tool call, feed results back in a new user or tool message; keep the loop explicit in code.

## Optimization & quality

- **Measure**: Track latency, tokens, and task-specific metrics (exact match, F1, human rubric)—not vibes alone.
- **Iterate**: Change one variable at a time (prompt vs model vs temperature).
- **Regression**: Keep a small golden set of inputs and expected shapes/behaviors; run after prompt edits.

## Safety

- Treat all user-supplied strings as untrusted: delimiter wrapping, allowlists for actions, and no prompt injection into tool names or system text without validation.
- Log prompts/responses carefully: redact PII and secrets; follow org retention rules.

## When to read more

- Deeper templates and checklists: [reference.md](reference.md)
