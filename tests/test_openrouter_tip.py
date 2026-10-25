import json

from api import app as api
from src import openrouter_tip
from tests.test_ai_tip_research import answer, fixture, prediction


def test_openrouter_research_is_one_bounded_request(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {
                "content": json.dumps(answer()),
                "annotations": [{"type": "url_citation", "url_citation": {
                    "url": "https://example.com/team-news"}},
                    {"type": "url_citation", "url_citation": {
                    "url": "https://example.com/team-news"}}],
            }}], "usage": {"prompt_tokens": 100, "completion_tokens": 200,
                            "server_tool_use": {"web_search_requests": 2}}}

    def post(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr(openrouter_tip.httpx, "post", post)
    monkeypatch.setattr(openrouter_tip, "record", lambda *args: None)
    monkeypatch.setattr(api, "AI_TIP_PROVIDER", "openrouter")
    monkeypatch.setattr(api, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(api, "GEMINI_API_KEY", "")

    vb = fixture()
    result = api._call_gemini_agent_pick(prediction(), vb, "A", "B")

    assert len(calls) == 1
    _, request = calls[0]
    assert request["json"]["model"] == "google/gemini-2.5-flash"
    assert request["json"]["tools"][0]["parameters"]["max_uses"] == 3
    assert request["json"]["max_tool_calls"] == 3
    assert "STEP 1 - RESEARCH (use web search)" in request["json"]["messages"][0]["content"]
    assert result["pick"] == vb["bets"][0]
    assert result["ai_provider"] == "openrouter"
    assert result["evidence"]["grounding_sources"] == ["https://example.com/team-news"]
    assert "use web search" in result["prompt_text"]


def test_openrouter_failure_does_not_trigger_gemini_fallback(monkeypatch):
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(openrouter_tip, "research", fail)
    monkeypatch.setattr(api, "AI_TIP_PROVIDER", "openrouter")
    monkeypatch.setattr(api, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(api, "GEMINI_API_KEY", "gemini-key")

    assert api._call_gemini_agent_pick(prediction(), fixture(), "A", "B") is None
    assert len(calls) == 1


def test_answer_without_search_is_recorded_but_not_used(monkeypatch):
    calls = []
    monkeypatch.setattr(openrouter_tip, "research", lambda *args: {
        "text": json.dumps(answer()), "source_urls": [], "usage": {}, "searched": False})
    monkeypatch.setattr(openrouter_tip, "record", lambda *args: calls.append(args))
    monkeypatch.setattr(api, "AI_TIP_PROVIDER", "openrouter")
    monkeypatch.setattr(api, "OPENROUTER_API_KEY", "test-key")

    assert api._call_gemini_agent_pick(prediction(), fixture(), "A", "B") is None
    assert len(calls) == 1


def test_openrouter_usage_counts_model_and_search_spend(tmp_path, monkeypatch):
    monkeypatch.setattr(openrouter_tip, "REPORTS", tmp_path)
    monkeypatch.setattr(openrouter_tip, "USAGE_PATH", tmp_path / "openrouter_usage.json")
    result = {"usage": {"prompt_tokens": 100, "completion_tokens": 200,
                        "server_tool_use": {"web_search_requests": 2},
                        "cost": 0.018}}
    openrouter_tip.record("agent_pick", result)
    entry = next(iter(openrouter_tip.load().values()))
    assert entry["calls"] == 1
    assert entry["web_search_requests"] == 2
    assert entry["prompt_tokens"] == 100
    assert entry["completion_tokens"] == 200
    assert entry["cost_usd"] == 0.018
