"""Output validator (MASTER.md 14.7). Returns structured issues so a retry prompt can include feedback."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from .schemas import ReportOutput

NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
SENT_END = re.compile(r"[.!?](?=\s|$)")

# Case-insensitive regexes. Short words use word boundaries ("als" must not match "also").
BANNED_TERMS = [
    r"diagnos", r"disease progression", r"progression of", r"parkinson", r"\bals\b", r"\bstroke\b",
    r"dementia", r"gait", r"walking speed", r"gait speed", r"walking distance", r"distance walked",
    r"\bbalance", r"\bfell\b", r"\bfallen\b", r"has fallen", r"you have", r"\bprescri", r"fall risk",
    r"risk of fall", r"\bmedication", r"recommend(?:ed|s)? treatment", r"\btreatment\b",
]
# Words implying a real change; forbidden for sustained_change="none" unless "normal variation" is stated.
CHANGE_WORDS = re.compile(r"increas|decreas|declin|improv|worsen|reduc|deteriorat|\bgrew\b|\bgrowth\b", re.I)
NORMAL_RE = re.compile(r"normal variation|within usual|usual variation|day-to-day variation", re.I)
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")

LIMITS = dict(overall_summary=700, activity_overview=900, statement=320, area=240,
              data_reliability=500, patient_friendly_summary=320)


@dataclass
class Issue:
    code: str      # parse | metric_key | number | banned_term | sustained_consistency | uncertainty | date
    field: str
    detail: str    # the offending item

    def feedback(self) -> str:
        return f"[{self.code}] {self.field}: {self.detail}"


@dataclass
class ValidationResult:
    ok: bool
    issues: list[Issue] = field(default_factory=list)
    output: ReportOutput | None = None      # parsed, with over-long text truncated
    truncated_fields: list[str] = field(default_factory=list)

    def feedback(self) -> list[str]:
        return [i.feedback() for i in self.issues]


def truncate_sentences(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    ends = [m.end() for m in SENT_END.finditer(cut)]
    if ends:
        return cut[:ends[-1]].strip()
    cut = cut.rsplit(" ", 1)[0].rstrip(" ,;:")
    return cut + "."


def allowed_numbers(report_input: dict) -> list[float]:
    out: list[float] = []

    def walk(v, key=None):
        if key == "report_ref":
            return
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            out.append(abs(float(v)))
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, str) and key == "most_active_hours_local":
            out.extend(float(n) for n in re.findall(r"\d+", v))

    walk(report_input)
    return out


def number_matches(token: str, allowed: list[float]) -> bool:
    val = abs(float(token))
    decimals = len(token.split(".")[1]) if "." in token else 0
    for a in allowed:
        tol = max(0.5 * 10 ** (-decimals), 0.01 * abs(a))  # rounding, or +-1%
        if abs(val - a) <= tol + 1e-9:
            return True
    return False


def _texts(out: ReportOutput):
    """(field path, text) for every text field."""
    yield "overall_summary", out.overall_summary
    yield "activity_overview", out.activity_overview
    for i, f in enumerate(out.mobility_trends):
        yield f"mobility_trends[{i}]", f.statement
    for i, f in enumerate(out.changes_vs_previous):
        yield f"changes_vs_previous[{i}]", f.statement
    for i, s in enumerate(out.safety_concerns):
        yield f"safety_concerns[{i}]", s.statement
    for i, a in enumerate(out.areas_to_monitor):
        yield f"areas_to_monitor[{i}]", a
    yield "data_reliability", out.data_reliability
    yield "patient_friendly_summary", out.patient_friendly_summary


def _truncate_all(out: ReportOutput) -> tuple[ReportOutput, list[str]]:
    changed: list[str] = []

    def t(path, text, limit):
        new = truncate_sentences(text, limit)
        if new != text:
            changed.append(path)
        return new

    d = out.model_copy(deep=True)
    d.overall_summary = t("overall_summary", d.overall_summary, LIMITS["overall_summary"])
    d.activity_overview = t("activity_overview", d.activity_overview, LIMITS["activity_overview"])
    for name in ("mobility_trends", "changes_vs_previous"):
        for i, f in enumerate(getattr(d, name)):
            f.statement = t(f"{name}[{i}]", f.statement, LIMITS["statement"])
    for i, s in enumerate(d.safety_concerns):
        s.statement = t(f"safety_concerns[{i}]", s.statement, LIMITS["statement"])
    d.areas_to_monitor = [t(f"areas_to_monitor[{i}]", a, LIMITS["area"]) for i, a in enumerate(d.areas_to_monitor)]
    d.data_reliability = t("data_reliability", d.data_reliability, LIMITS["data_reliability"])
    d.patient_friendly_summary = t("patient_friendly_summary", d.patient_friendly_summary,
                                   LIMITS["patient_friendly_summary"])
    return d, changed


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s]


def validate_output(raw: str | dict | ReportOutput, report_input: dict) -> ValidationResult:
    """Run every MASTER 14.7 check. Never raises."""
    # 1. parse
    try:
        if isinstance(raw, ReportOutput):
            out = raw
        elif isinstance(raw, dict):
            out = ReportOutput.model_validate(raw)
        else:
            out = ReportOutput.model_validate_json(raw)
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as e:
        msg = str(e).replace("\n", " ")[:300]
        return ValidationResult(False, [Issue("parse", "output", f"not valid JSON for the schema: {msg}")])

    out, truncated = _truncate_all(out)
    issues: list[Issue] = []
    metrics = {m["key"]: m for m in report_input.get("metrics", [])}

    # 2. metric keys
    for name in ("mobility_trends", "changes_vs_previous"):
        for i, f in enumerate(getattr(out, name)):
            if f.metric_key not in metrics:
                issues.append(Issue("metric_key", f"{name}[{i}]",
                                    f"unknown metric_key '{f.metric_key}'; allowed: {sorted(metrics)}"))

    allowed = allowed_numbers(report_input)
    for path, text in _texts(out):
        # 3. numbers
        bad = [n for n in NUM_RE.findall(text) if not number_matches(n, allowed)]
        if bad:
            issues.append(Issue("number", path, f"numbers not found in INPUT: {', '.join(bad)}"))
        # 4. banned terms
        hits = sorted({m.group(0).lower() for p in BANNED_TERMS for m in re.finditer(p, text, re.I)})
        if hits:
            issues.append(Issue("banned_term", path, f"forbidden wording: {', '.join(hits)}"))
        if DATE_RE.search(text):
            issues.append(Issue("date", path, "dates are not allowed; use 'this period'"))

    # 5. sustained_change = none consistency
    none_metrics = [m for m in metrics.values() if m.get("sustained_change") == "none"]
    for name in ("mobility_trends", "changes_vs_previous"):
        for i, f in enumerate(getattr(out, name)):
            m = metrics.get(f.metric_key)
            if m and m.get("sustained_change") == "none":
                if CHANGE_WORDS.search(f.statement) and not NORMAL_RE.search(f.statement):
                    issues.append(Issue("sustained_consistency", f"{name}[{i}]",
                                        f"'{f.metric_key}' has sustained_change=none; do not describe a change "
                                        "unless you state it is within normal variation"))
                if f.direction in ("up", "down"):
                    issues.append(Issue("sustained_consistency", f"{name}[{i}]",
                                        f"'{f.metric_key}' has sustained_change=none; direction must be "
                                        "stable or unclear"))
    for path, text in _texts(out):
        if path.startswith(("mobility_trends", "changes_vs_previous")):
            continue
        for s in _sentences(text):
            for m in none_metrics:
                if m["label"].lower() in s.lower() and CHANGE_WORDS.search(s) and not NORMAL_RE.search(s):
                    issues.append(Issue("sustained_consistency", path,
                                        f"sentence about '{m['key']}' (sustained_change=none) implies a change: "
                                        f"\"{s[:80]}\""))

    # rule 4: less certain wording
    if (not report_input.get("insufficient_data")
            and report_input["data_completeness"]["valid_days"] < 10
            and "less certain" not in (out.data_reliability + " " + out.overall_summary).lower()):
        issues.append(Issue("uncertainty", "data_reliability",
                            "valid_days < 10: state that the findings are less certain"))

    return ValidationResult(not issues, issues, out, truncated)
