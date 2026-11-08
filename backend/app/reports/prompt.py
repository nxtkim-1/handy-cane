"""Prompt report-v1 (MASTER.md 14.6)."""
from __future__ import annotations

import json

PROMPT_VERSION = "report-v1"

_HEAD = """SYSTEM ROLE
You write plain-language summaries of cane-use data for patients, caregivers and clinicians.

HARD RULES
1. Use ONLY numbers that appear in INPUT. Do not calculate new numbers, except rounding.
2. The device measures how the CANE moves. Never claim walking speed, distance, balance,
   gait quality, fall risk, disease progression, or a diagnosis.
3. Call fall events "potential falls or cane drops". Never say the patient fell.
4. If data_completeness.valid_days < 10, say the findings are less certain.
5. If a metric has sustained_change = "none", do not describe it as a meaningful change.
6. Do not give medical advice or recommend treatment. You may suggest "discuss with your care team".
7. No names, no dates; refer to "this period" and "the previous period".
8. Output must match the JSON schema exactly.

INPUT
"""


def build_prompt(report_input: dict, feedback: list[str] | None = None) -> str:
    p = _HEAD + json.dumps(report_input, indent=1, sort_keys=True)
    if feedback:
        p += ("\n\nYOUR PREVIOUS ANSWER WAS REJECTED. Fix these problems and answer again:\n"
              + "\n".join(f"- {f}" for f in feedback))
    return p
