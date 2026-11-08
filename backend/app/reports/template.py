"""Deterministic fallback report (MASTER.md 14.7). Fixed sentences, numbers copied from the input."""
from __future__ import annotations

from .schemas import DISCLAIMER, Finding, ReportOutput, SafetyNote

LESS_CERTAIN_BELOW = 10  # valid days; MASTER 14.6 rule 4
NORMAL = "This is within normal variation."


def fmt(x) -> str:
    if float(x) == int(float(x)):
        return str(int(float(x)))
    return str(round(float(x), 1))


def _unit(m: dict) -> str:
    return f" {m['unit']}" if m.get("unit") else ""


def _insufficient(inp: dict) -> ReportOutput:
    dc = inp["data_completeness"]
    sim = " This report uses simulated data." if inp.get("is_simulated") else ""
    return ReportOutput(
        overall_summary=("There was not enough cane data in this period to describe patterns. "
                         f"Only {dc['valid_days']} of {dc['total_days']} days had enough data."),
        activity_overview="Too few days had enough data to describe cane-active time or walking bouts.",
        mobility_trends=[], changes_vs_previous=[],
        safety_concerns=[SafetyNote(
            statement="Findings are not available because the data was incomplete. "
                      "Check that the cane was switched on and synced.", source="completeness")],
        areas_to_monitor=["Keep the cane charged and synced so the next report has enough data."],
        data_reliability=(f"Only {dc['valid_days']} of {dc['total_days']} days had enough data, "
                          f"so no findings are reported.{sim}"),
        patient_friendly_summary=("There was not enough cane data for a report this time. "
                                  "Please keep the cane charged and synced."),
        disclaimer_ack=DISCLAIMER)


def _direction(m: dict) -> str:
    sc = m.get("sustained_change")
    if m.get("current_median") is None:
        return "unclear"
    return sc if sc in ("up", "down") else "stable"


def template_report(inp: dict) -> ReportOutput:
    """Always succeeds for any report_input produced by input_builder."""
    if inp.get("insufficient_data"):
        return _insufficient(inp)
    dc, ev = inp["data_completeness"], inp["events"]
    metrics = [m for m in inp.get("metrics", []) if m.get("current_median") is not None]

    overview = []
    trends, changes, monitor = [], [], []
    for m in metrics:
        s = f"{m['label']} this period was {fmt(m['current_median'])}{_unit(m)}"
        s += (f", compared with {fmt(m['previous_median'])} in the previous period."
              if m.get("previous_median") is not None else ".")
        overview.append(s)

        d = _direction(m)
        if m.get("trend_slope_per_week") is not None:
            lo, hi = m["trend_ci90"]
            t = (f"{m['label']} has a slope of {fmt(m['trend_slope_per_week'])}{_unit(m)} per week "
                 f"(range {fmt(lo)} to {fmt(hi)}).")
        else:
            t = f"There is not enough data to estimate a weekly trend for {m['label']}."
        if m["sustained_change"] == "none":
            t += " " + NORMAL
        else:
            t += (" A sustained shift was flagged compared with the usual level." )
        trends.append(Finding(metric_key=m["key"], statement=t, direction=d))

        pct = m.get("change_vs_previous_pct")
        if pct is not None:
            word = "lower" if pct < 0 else "higher"
            c = f"{m['label']} was {fmt(abs(pct))} percent {word} than in the previous period."
        else:
            c = f"No comparison with the previous period is available for {m['label']}."
        if m["sustained_change"] == "none":
            c += " " + NORMAL
        changes.append(Finding(metric_key=m["key"], statement=c, direction=d))
        if m["sustained_change"] in ("up", "down"):
            monitor.append(f"{m['label']}: consider discussing this with your care team.")

    if not overview:
        overview = ["No cane-use metrics were available for this period."]
    if not monitor:
        monitor = ["Keep using and syncing the cane so changes can be tracked over time."]

    safety: list[SafetyNote] = []
    if ev["potential_fall_escalated"]:
        safety.append(SafetyNote(
            statement=f"{ev['potential_fall_escalated']} potential fall or cane drop event(s) were escalated "
                      "to the care team this period.", source="events"))
    if ev["potential_fall_cancelled"]:
        safety.append(SafetyNote(
            statement=f"{ev['potential_fall_cancelled']} potential fall or cane drop alert(s) were "
                      "cancelled by the user.", source="events"))
    if ev["help_requests"]:
        safety.append(SafetyNote(statement=f"{ev['help_requests']} help request(s) were made with the cane button.",
                                 source="events"))
    if not safety:
        safety.append(SafetyNote(
            statement="No potential falls, cane drops or help requests were recorded this period.",
            source="events"))

    uncertain = dc["valid_days"] < LESS_CERTAIN_BELOW
    rel = f"{dc['valid_days']} of {dc['total_days']} days had enough data."
    if dc.get("median_coverage_h") is not None:
        rel += f" Typical daily coverage was {fmt(dc['median_coverage_h'])} hours."
    if uncertain:
        rel += " Findings are less certain because of the missing days."
    rel += " A day with no data may simply mean the cane was switched off."
    if inp.get("is_simulated"):
        rel += " This report uses simulated data."

    summary = (f"This report covers {inp['period_days']} days of cane-use data, "
               f"with {dc['valid_days']} of {dc['total_days']} days usable. "
               f"{overview[0]} ")
    summary += ("Findings are less certain because some days are missing. " if uncertain else "")
    summary += "It describes how the cane was used and is not a medical assessment."

    first = metrics[0] if metrics else None
    friendly = ("Your cane was used for about "
                f"{fmt(first['current_median'])} {first['unit'] or 'units'} this period. "
                if first else "Not much cane data was available this period. ")
    friendly += "Ask your care team if you want to talk about this report."

    return ReportOutput(
        overall_summary=summary, activity_overview=" ".join(overview),
        mobility_trends=trends[:8], changes_vs_previous=changes[:8],
        safety_concerns=safety[:5], areas_to_monitor=monitor[:5],
        data_reliability=rel, patient_friendly_summary=friendly, disclaimer_ack=DISCLAIMER)
