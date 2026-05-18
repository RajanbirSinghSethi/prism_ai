from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from sdlc_copilot.llm.providers import build_chat_model
from sdlc_copilot.config import Settings

_AYRA_NAME = "PRISM - AI SDLC Copilot"

_GREETINGS = frozenset({"hi", "hello", "hey", "hiya", "good morning", "good evening"})
_HELP_HINTS = ("help", "what can you", "how do you work", "what do you do")
_RUN_HINTS = (
    "analyze",
    "analysis",
    "run pipeline",
    "start analysis",
    "process this",
    "run agents",
    "sdlc",
    "generate stories",
    "create tasks",
)
_REQUIREMENT_HINTS = (
    "shall",
    "must",
    "user can",
    "system shall",
    "requirement",
    "as a ",
    "acceptance",
    "feature",
    "module",
    "api ",
    "authentication",
)


def handle_message(message: str, *, settings: Settings, has_documents: bool = False) -> dict[str, Any]:
    """Classify user input: conversational reply or start full agent pipeline."""
    text = message.strip()
    if not text and not has_documents:
        return {
            "type": "reply",
            "text": (
                f"Hi, I'm {_AYRA_NAME}. Paste your requirements, upload a document "
                "(PDF, DOCX, TXT, MD, HTML, CSV, JSON), or describe what you want to build."
            ),
        }

    if has_documents and len(text) < 40:
        return {
            "type": "pipeline",
            "requirements": text or "See attached requirement documents.",
            "reply": "I'll analyze your uploaded document through the full SDLC agent workflow.",
        }

    lower = text.lower().strip()
    if lower in _GREETINGS:
        return {
            "type": "reply",
            "text": (
                f"Hello! I'm {_AYRA_NAME}. Tell me what you're building, paste requirements, "
                "or upload a file — I'll run extraction, stories, tasks, tests, API specs, and more."
            ),
        }

    if any(h in lower for h in _HELP_HINTS):
        return {
            "type": "reply",
            "text": (
                "I turn requirements into SDLC artifacts: structured requirements, user stories, "
                "tasks, acceptance criteria, test cases, API & database specs, security review, "
                "sprint plan, and compliance notes. Paste details or upload a supported file, "
                'then say "analyze this" or just send a long requirements block.'
            ),
        }

    if any(h in lower for h in _RUN_HINTS):
        requirements = _strip_run_prefix(text)
        return {
            "type": "pipeline",
            "requirements": requirements,
            "reply": "Understood — starting the agent pipeline. I'll show each step as it completes.",
        }

    if len(text) >= 100 or any(h in lower for h in _REQUIREMENT_HINTS):
        return {
            "type": "pipeline",
            "requirements": text,
            "reply": "Got it. Running the full SDLC analysis on your requirements now.",
        }

    return _llm_conversational_reply(text, settings=settings)


def build_run_summary(outputs: dict[str, Any], errors: dict[str, str]) -> str:
    """Concise human summary after pipeline completes (no extra LLM call)."""
    ok = len(outputs)
    failed = len(errors)
    lines = [f"Analysis complete — **{ok}** agents produced outputs."]
    if failed:
        lines.append(f"**{failed}** steps hit limits or errors; expand JSON below for details.")
    lines.append("Open each agent below to view the full JSON output.")
    return "\n\n".join(lines)


def _strip_run_prefix(text: str) -> str:
    lowered = text.lower()
    for prefix in ("analyze this:", "analyze:", "run pipeline on", "process this:", "start analysis on"):
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


def _llm_conversational_reply(message: str, *, settings: Settings) -> dict[str, Any]:
    try:
        llm = build_chat_model(settings, temperature=0.3)
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        f"You are {_AYRA_NAME}, a friendly SDLC assistant. "
                        "Reply in 2–4 short sentences. Be clear and focused. "
                        "If the user has not given requirements yet, ask them to paste or upload "
                        "requirements (PDF, DOCX, TXT, MD, HTML, CSV, JSON). "
                        "Do not claim you ran agents unless they asked for analysis. "
                        "Plain text only, no markdown code blocks."
                    )
                ),
                HumanMessage(content=message),
            ]
        )
        reply = response.content if isinstance(response.content, str) else str(response.content)
        reply = reply.strip()
        if _looks_like_requirements(reply):
            return {"type": "pipeline", "requirements": message, "reply": "I'll run the SDLC pipeline on that."}
        return {"type": "reply", "text": reply or "How can I help with your requirements today?"}
    except Exception:
        return {
            "type": "reply",
            "text": (
                "I'm here to analyze software requirements. Paste a requirements paragraph "
                "or upload a supported document when you're ready."
            ),
        }


def _looks_like_requirements(text: str) -> bool:
    return len(text) > 200 and any(h in text.lower() for h in _REQUIREMENT_HINTS)
