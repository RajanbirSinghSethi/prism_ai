import csv
import json
from pathlib import Path

from sdlc_copilot.models import PipelineResponse


def export_json(response: PipelineResponse, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response.model_dump_json(indent=2), encoding="utf-8")
    return path


def export_csv(response: PipelineResponse, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["agent_id", "title", "artifact_type", "content"])
        writer.writeheader()
        for output in response.outputs.values():
            writer.writerow(
                {
                    "agent_id": output.agent_id,
                    "title": output.title,
                    "artifact_type": str(output.artifact_type),
                    "content": json.dumps(output.content, ensure_ascii=False),
                }
            )
    return path


def export_pdf(response: PipelineResponse, path: Path) -> Path:
    """Generate a structured PDF of all agent outputs using fpdf2.

    Layout per agent output page:
    - Title (H1, bold 16pt), metadata row, risks, assumptions, content JSON.

    Unicode safety: content is ASCII-escaped to avoid fpdf2 built-in font
    encoding issues on non-Latin characters.
    """
    from fpdf import FPDF  # fpdf2 — imported lazily

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    line_w = pdf.epw

    for output in response.outputs.values():
        pdf.add_page()

        pdf.set_font("Helvetica", style="B", size=16)
        _safe_cell(pdf, line_w, 10, output.title)

        pdf.set_font("Helvetica", size=10)
        _safe_cell(pdf, line_w, 7, f"Artifact: {output.artifact_type}  |  Confidence: {output.confidence:.0%}")
        pdf.ln(2)

        if output.risks:
            pdf.set_font("Helvetica", style="B", size=11)
            _safe_cell(pdf, line_w, 8, "Risks")
            pdf.set_font("Helvetica", size=10)
            for line in _bullet_lines(output.risks):
                _safe_multi_cell(pdf, line_w, 6, f"  * {line}")

        if output.assumptions:
            pdf.set_font("Helvetica", style="B", size=11)
            _safe_cell(pdf, line_w, 8, "Assumptions")
            pdf.set_font("Helvetica", size=10)
            for line in _bullet_lines(output.assumptions):
                _safe_multi_cell(pdf, line_w, 6, f"  * {line}")

        pdf.set_font("Helvetica", style="B", size=11)
        _safe_cell(pdf, line_w, 8, "Content")
        pdf.set_font("Helvetica", size=8)
        for line in json.dumps(output.content, indent=2, ensure_ascii=True).splitlines():
            _safe_multi_cell(pdf, line_w, 5, line[:180])

    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path


def _safe_str(value: object) -> str:
    return str(value).encode("ascii", errors="replace").decode("ascii")


def _bullet_lines(values: list[object]) -> list[str]:
    """Normalize risks/assumptions to printable lines (fpdf needs breakable width)."""
    lines: list[str] = []
    for value in values:
        if isinstance(value, dict):
            text = json.dumps(value, ensure_ascii=True)
        else:
            text = _safe_str(value)
        if len(text) > 240:
            text = text[:237] + "..."
        lines.append(text)
    return lines


def _safe_cell(pdf, w: float, h: float, txt: str) -> None:
    pdf.cell(w, h, _safe_str(txt), new_x="LMARGIN", new_y="NEXT")


def _safe_multi_cell(pdf, w: float, h: float, txt: str) -> None:
    """fpdf2 requires explicit width — never pass 0 (causes 'not enough horizontal space')."""
    pdf.multi_cell(w, h, _safe_str(txt))
