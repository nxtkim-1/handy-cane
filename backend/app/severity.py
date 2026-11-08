"""Event severity: an explainable heuristic for ordering what a caregiver looks at first.

NOT clinical. It is computed at read time from the stored event and never saved, so the rules can change
retroactively. The reason string is shown to the user.

Rules (first match wins):
  help_request                                  -> high    "The help button was held on the cane."
  potential_fall + escalated                    -> high    "Nobody cancelled the alarm on the cane."
                                                           (cause cane_down_still: says no impact was seen)
  potential_fall + acknowledged_on_cane         -> medium
  potential_fall + cancelled_by_user            -> medium if peak_g >= 3.0 (hard impact), else low
  impact_only                                   -> low
  anything else                                 -> medium  "Unrecognised event; please check."
"""
from __future__ import annotations

HARD_IMPACT_G = 3.0
RANK = {"high": 0, "medium": 1, "low": 2}


def severity_for(event) -> tuple[str, str]:
    """event: any object with kind, outcome, peak_g and (optionally) cause attributes."""
    kind = getattr(event, "kind", None)
    outcome = getattr(event, "outcome", None)
    peak = getattr(event, "peak_g", None)
    cause = getattr(event, "cause", None)
    if kind == "help_request":
        return "high", "The help button was held on the cane."
    if kind == "potential_fall":
        if outcome == "escalated":
            if cause == "cane_down_still":
                return "high", ("Nobody cancelled the alarm on the cane. No impact was seen; "
                                "the cane was lying still.")
            return "high", "Nobody cancelled the alarm on the cane."
        if outcome == "acknowledged_on_cane":
            return "medium", "The alarm sounded and was switched off on the cane."
        if outcome == "cancelled_by_user":
            if peak is not None and peak >= HARD_IMPACT_G:
                return "medium", "Cancelled on the cane after a hard impact."
            return "low", "Cancelled on the cane; no hard impact."
    if kind == "impact_only":
        return "low", "A bump was recorded; the cane stayed upright."
    return "medium", "Unrecognised event; please check."
