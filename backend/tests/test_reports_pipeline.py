import json

import numpy as np
import pytest

from backend.app.reports.gemini_client import FakeGemini, GoogleGeminiClient, GeminiError
from backend.app.reports.input_builder import build_report_input
from backend.app.reports.pipeline import generate_report
from backend.app.reports.prompt import PROMPT_VERSION
from backend.app.reports.schemas import ReportOutput
from backend.app.reports.template import template_report
from backend.app.reports.validator import truncate_sentences, validate_output
from backend.sim.generate import simulate


def make_input(seed=7, end=56, extra_missing=(), **kw):
    sim = simulate(seed=seed, missing_days=(19, 41, *extra_missing))
    series = {k: sim[k][:end] for k in ("active_min", "bout_median_s")}
    return build_report_input(series, is_simulated=True, events={"potential_fall_cancelled": 2}, **kw)


@pytest.fixture
def inp():
    return make_input()


def texts(out: ReportOutput):
    return json.dumps(out.model_dump())


# ---- input builder ------------------------------------------------------------------------
def test_input_shape_and_privacy(inp):
    assert set(inp) >= {"report_ref", "period_days", "data_completeness", "metrics", "events",
                        "activity_timing", "is_simulated"}
    assert inp["report_ref"].startswith("r-") and not inp["insufficient_data"]
    m = inp["metrics"][0]
    assert {"key", "label", "unit", "current_median", "previous_median", "baseline_median",
            "change_vs_previous_pct", "change_vs_baseline_pct", "trend_slope_per_week", "trend_ci90",
            "sustained_change"} <= set(m)
    assert m["sustained_change"] == "down"  # simulator declines in the last 4 weeks
    assert make_input()["report_ref"] != make_input()["report_ref"]


def test_insufficient_data_flag():
    inp = make_input(extra_missing=tuple(range(44, 52)))
    assert inp["insufficient_data"] and inp["metrics"] == []
    r = generate_report(inp, FakeGemini([FakeGemini.invalid_json()]))
    assert r.status == "insufficient_data" and r.model is None


def test_series_too_short():
    with pytest.raises(ValueError):
        build_report_input({"active_min": np.ones(20)})


# ---- template + validator -----------------------------------------------------------------
def test_template_passes_validator(inp):
    assert validate_output(template_report(inp), inp).ok


def test_good_output_passes_and_is_generated(inp):
    fake = FakeGemini([FakeGemini.good_output(inp)], model="gemini-x")
    r = generate_report(inp, fake)
    assert r.status == "generated" and r.model == "gemini-x" and r.prompt_version == PROMPT_VERSION
    assert r.validation.ok and r.attempts == 1


def test_fake_number_rejected_with_feedback(inp):
    bad = FakeGemini.wrong_numbers(inp)
    v = validate_output(bad, inp)
    assert not v.ok and any(i.code == "number" and "987" in i.detail for i in v.issues)
    fake = FakeGemini([bad, FakeGemini.good_output(inp)])
    r = generate_report(inp, fake)
    assert r.status == "generated" and r.attempts == 2
    assert "987" in fake.prompts[1] and "REJECTED" in fake.prompts[1]


@pytest.mark.parametrize("word", ["fell", "balance", "diagnosed", "gait speed", "Parkinson"])
def test_banned_terms_fall_back(inp, word):
    r = generate_report(inp, FakeGemini([FakeGemini.banned_terms(inp, word)]))
    assert r.status == "fallback" and r.model is None
    assert any(i.code == "banned_term" for i in r.validation.issues)
    body = texts(r.output).replace(r.output.disclaimer_ack, "").lower()  # fixed disclaimer says "diagnosis"
    assert not any(w in body for w in ("fell", "balance", "diagnos", "parkinson"))


def test_also_is_not_banned(inp):
    d = template_report(inp).model_dump()
    d["activity_overview"] += " Also, the cane was used on most days."
    assert validate_output(json.dumps(d), inp).ok


@pytest.mark.parametrize("client", [
    FakeGemini([FakeGemini.invalid_json()]),
    FakeGemini([RuntimeError("boom")]),
    FakeGemini([TimeoutError]),
    FakeGemini(["not json at all"]),
    FakeGemini([""]),
])
def test_failures_end_with_safe_report(inp, client):
    r = generate_report(inp, client)
    assert r.status == "fallback" and r.output.overall_summary and validate_output(r.output, inp).ok


def test_unknown_metric_key(inp):
    v = validate_output(FakeGemini.unknown_metric(inp), inp)
    assert any(i.code == "metric_key" for i in v.issues)


def test_sustained_none_consistency():
    inp = make_input(seed=3, end=28)  # no decline in first 28 days
    m = inp["metrics"][0]
    assert m["sustained_change"] == "none"
    d = template_report(inp).model_dump()
    d["changes_vs_previous"][0]["statement"] = f"{m['label']} showed a clear decrease."
    v = validate_output(json.dumps(d), inp)
    assert any(i.code == "sustained_consistency" for i in v.issues)
    d["changes_vs_previous"][0]["statement"] += " This is within normal variation."
    assert validate_output(json.dumps(d), inp).ok


def test_uncertainty_required_when_few_days():
    inp = make_input(seed=3, end=56, extra_missing=(46, 47, 48, 49))  # 10 valid -> try fewer
    inp["data_completeness"]["valid_days"] = 9
    d = template_report(inp).model_dump()
    d["data_reliability"] = "Data was fine."
    d["overall_summary"] = "Summary."
    assert any(i.code == "uncertainty" for i in validate_output(json.dumps(d), inp).issues)


def test_truncation_at_sentence_boundary(inp):
    d = template_report(inp).model_dump()
    d["overall_summary"] = "First sentence here. " * 100
    v = validate_output(json.dumps(d), inp)
    assert v.ok and "overall_summary" in v.truncated_fields
    s = v.output.overall_summary
    assert len(s) <= 700 and s.endswith(".")
    assert truncate_sentences("short.", 100) == "short."


def test_number_tolerance(inp):
    cur = inp["metrics"][0]["current_median"]
    d = template_report(inp).model_dump()
    d["activity_overview"] = f"About {round(cur)} minutes per day."
    assert validate_output(json.dumps(d), inp).ok


def test_date_rejected(inp):
    d = template_report(inp).model_dump()
    d["activity_overview"] = "On 2026-11-07 the cane was used."
    assert not validate_output(json.dumps(d), inp).ok


# ---- client -------------------------------------------------------------------------------
def test_real_client_needs_no_key_to_import_and_retries():
    calls = []
    c = GoogleGeminiClient(model="m", api_key=None, sleep=lambda s: None)
    c._call = lambda p, s: (calls.append(1), (_ for _ in ()).throw(RuntimeError("x")))[1]
    with pytest.raises(GeminiError):
        c.generate("p", {})
    assert len(calls) == 3  # first try + 2 retries


def test_model_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "custom-model")
    assert GoogleGeminiClient().model == "custom-model"


# ---- 20 synthetic inputs ------------------------------------------------------------------
def _twenty():
    out = []
    for i in range(20):
        end = 28 + (i * 3) % 29
        extra = tuple(range(end - 14 + 1, end - 14 + 1 + (i % 7))) if i % 4 == 0 else ()
        out.append(make_input(seed=i, end=end, extra_missing=extra))
    return out


@pytest.mark.parametrize("inp", _twenty())
@pytest.mark.parametrize("mode", ["good", "bad"])
def test_twenty_synthetic_inputs_always_get_a_report(inp, mode):
    client = FakeGemini([FakeGemini.good_output(inp) if mode == "good" else FakeGemini.wrong_numbers(inp)])
    r = generate_report(inp, client)
    o = r.output
    assert o.overall_summary and o.activity_overview and o.data_reliability and o.patient_friendly_summary
    assert r.status in ("generated", "fallback", "insufficient_data")
    assert validate_output(o, inp).ok
