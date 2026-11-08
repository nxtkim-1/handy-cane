"""generate_report: the flow in MASTER.md 14.1."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .prompt import PROMPT_VERSION, build_prompt
from .schemas import ReportOutput
from .template import template_report
from .validator import ValidationResult, validate_output

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 2


@dataclass
class ReportResult:
    output: ReportOutput
    status: str                      # generated | fallback | insufficient_data
    validation: ValidationResult | None
    model: str | None                # None when the template produced the report
    prompt_version: str
    attempts: int = 0


def _fallback(report_input, status, validation, attempts) -> ReportResult:
    return ReportResult(template_report(report_input), status, validation, None, PROMPT_VERSION, attempts)


def generate_report(report_input: dict, client) -> ReportResult:
    """Always returns a usable report. `client` needs `.model` and `.generate(prompt, schema)`."""
    if report_input.get("insufficient_data"):
        return _fallback(report_input, "insufficient_data", None, 0)

    schema = ReportOutput.model_json_schema()
    feedback: list[str] | None = None
    last: ValidationResult | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = client.generate(build_prompt(report_input, feedback), schema)
        except Exception as e:  # timeout / API error (client already retried)
            log.warning("gemini call failed: %s", type(e).__name__)
            return _fallback(report_input, "fallback", last, attempt)
        last = validate_output(raw, report_input)
        if last.ok:
            return ReportResult(last.output, "generated", last, getattr(client, "model", None),
                                PROMPT_VERSION, attempt)
        feedback = last.feedback()
    return _fallback(report_input, "fallback", last, MAX_ATTEMPTS)
