"""Gemini wrapper behind a small interface. The google-genai SDK is imported lazily, so importing this
module (and running tests) needs neither the SDK nor an API key."""
from __future__ import annotations

import os
import time
from typing import Callable, Protocol

DEFAULT_MODEL = "gemini-3.8-flash"   # MASTER 14.2; override with env GEMINI_MODEL
DEFAULT_TIMEOUT_S = 30.0
MAX_RETRIES = 2


class GeminiError(RuntimeError):
    pass


class GeminiClient(Protocol):
    model: str

    def generate(self, prompt: str, schema: dict) -> str:
        """Return the model's JSON text for `prompt`, constrained to the JSON `schema`."""
        ...


class GoogleGeminiClient:
    """Real client. Retries transient errors up to `max_retries` times with backoff."""

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S, max_retries: int = MAX_RETRIES,
                 sleep: Callable[[float], None] = time.sleep):
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.timeout_s = timeout_s
        self.max_retries = min(max_retries, MAX_RETRIES)
        self._sleep = sleep
        self._client = None

    def _sdk(self):
        if self._client is None:
            try:
                from google import genai  # lazy
                from google.genai import types
            except ImportError as e:  # pragma: no cover
                raise GeminiError("google-genai is not installed") from e
            if not self.api_key:
                raise GeminiError("GEMINI_API_KEY is not set")
            self._client = genai.Client(
                api_key=self.api_key, http_options=types.HttpOptions(timeout=int(self.timeout_s * 1000)))
        return self._client

    def _call(self, prompt: str, schema: dict) -> str:
        client = self._sdk()
        resp = client.models.generate_content(
            model=self.model, contents=prompt,
            config={"response_mime_type": "application/json", "response_json_schema": schema})
        text = getattr(resp, "text", None)
        if not text:
            raise GeminiError("empty response")
        return text

    def generate(self, prompt: str, schema: dict) -> str:
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._call(prompt, schema)
            except Exception as e:  # network, timeout, quota, SDK errors
                last = e
                if attempt < self.max_retries:
                    self._sleep(2.0 ** attempt)
        raise GeminiError(f"Gemini call failed after {self.max_retries + 1} attempts: {last}") from last


class FakeGemini:
    """Test double. `responses` is a list of str (returned) or Exception instances/classes (raised);
    the last item repeats once the list is exhausted. Records every prompt in `.prompts`."""

    def __init__(self, responses: list, model: str = "fake-gemini"):
        self.responses = list(responses)
        self.model = model
        self.prompts: list[str] = []

    def generate(self, prompt: str, schema: dict) -> str:
        self.prompts.append(prompt)
        i = min(len(self.prompts) - 1, len(self.responses) - 1)
        r = self.responses[i]
        if isinstance(r, BaseException) or (isinstance(r, type) and issubclass(r, BaseException)):
            raise r if isinstance(r, BaseException) else r("fake failure")
        return r

    # --- canned responses built from a report_input -------------------------------------------
    @staticmethod
    def good_output(report_input: dict) -> str:
        from .template import template_report
        return template_report(report_input).model_dump_json()

    @staticmethod
    def _mutated(report_input: dict, fn) -> str:
        from .template import template_report
        d = template_report(report_input).model_dump()
        fn(d)
        import json
        return json.dumps(d)

    @classmethod
    def wrong_numbers(cls, report_input: dict) -> str:
        return cls._mutated(report_input, lambda d: d.__setitem__(
            "overall_summary", d["overall_summary"] + " Cane use rose to 987 minutes a day."))

    @classmethod
    def banned_terms(cls, report_input: dict, word: str = "fell") -> str:
        return cls._mutated(report_input, lambda d: d.__setitem__(
            "patient_friendly_summary", f"The patient {word} and balance is getting worse."))

    @staticmethod
    def invalid_json() -> str:
        return '{"overall_summary": "oops", '

    @classmethod
    def unknown_metric(cls, report_input: dict) -> str:
        def f(d):
            d["mobility_trends"] = [dict(metric_key="walking_speed", statement="Something.", direction="up")]
        return cls._mutated(report_input, f)
