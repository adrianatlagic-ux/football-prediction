from src import translate


def test_each_text_is_translated_once_and_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(translate, "PATH", tmp_path / "t.json")
    monkeypatch.setattr(translate, "REPORTS", tmp_path)
    calls = []
    fake = lambda texts: calls.append(list(texts)) or [t.replace("Sieg", "Win") for t in texts]
    assert translate.to_english(["Sieg Portugal", "", "Sieg Portugal"], call=fake) == ["Win Portugal", "", "Win Portugal"]
    assert translate.to_english(["Sieg Portugal"], call=fake) == ["Win Portugal"]
    assert calls == [["Sieg Portugal"]]            # one call, once


def test_a_failed_translation_falls_back_to_german(tmp_path, monkeypatch):
    monkeypatch.setattr(translate, "PATH", tmp_path / "t.json")
    monkeypatch.setattr(translate, "REPORTS", tmp_path)
    assert translate.to_english(["Keine gute Wette"], call=lambda texts: None) == ["Keine gute Wette"]


def test_bosnian_is_kept_apart_from_english(tmp_path, monkeypatch):
    monkeypatch.setattr(translate, "PATH", tmp_path / "t.json")
    monkeypatch.setattr(translate, "REPORTS", tmp_path)
    en = lambda texts: [t.replace("Sieg", "Win") for t in texts]
    bs = lambda texts: [t.replace("Sieg", "Pobjeda") for t in texts]
    assert translate.to_language(["Sieg Portugal"], "en", call=en) == ["Win Portugal"]
    assert translate.to_language(["Sieg Portugal"], "bs", call=bs) == ["Pobjeda Portugal"]
    assert translate.to_language(["Sieg Portugal"], "en", call=lambda t: None) == ["Win Portugal"]      # kept, per language
    assert (tmp_path / "translations_bs.json").exists()


def test_an_unknown_language_returns_the_german_text(tmp_path, monkeypatch):
    monkeypatch.setattr(translate, "PATH", tmp_path / "t.json")
    monkeypatch.setattr(translate, "REPORTS", tmp_path)
    assert translate.to_language(["Sieg Portugal"], "fr", call=lambda t: ["x"]) == ["Sieg Portugal"]


def test_the_endpoint_translates_every_check_of_the_match_and_reports_gaps(tmp_path, monkeypatch):
    from api import app as api
    monkeypatch.setattr(translate, "PATH", tmp_path / "t.json")
    monkeypatch.setattr(translate, "REPORTS", tmp_path)
    key = api._match_key("Alpha", "Bravo")
    old = {"bet_headline": "Sieg Alpha", "bet_reasoning": "Alt", "change_reason": "", "research": {"form": "Gute Form"}}
    new = {"bet_headline": "Unter 2,5", "bet_reasoning": "Neu", "change_reason": "Neuer Grund", "research": {}}
    monkeypatch.setattr(api, "_agent_picks_cache", {("a", "b", "c", *key): old, ("a", "b", "d", *key): new})
    monkeypatch.setattr(api, "_get_prediction_index", lambda: {key: {"score_prediction": {"betting_markets": {"scenario": "Szenario"}}}})
    monkeypatch.setattr(translate, "_ask_model", lambda texts, lang="en": [f"bs:{t}" for t in texts])
    out = api.ai_texts_en("Alpha", "Bravo", "bs")
    # the page may show either check: both are translated, keyed by the German text
    assert out["texts"]["Alt"] == "bs:Alt" and out["texts"]["Neu"] == "bs:Neu" and out["texts"]["Szenario"] == "bs:Szenario"
    assert out["texts"]["Gute Form"] == "bs:Gute Form" and out["complete"] is True
    # a failed translation is no entry (the page asks again), not an echo of the German
    monkeypatch.setattr(translate, "_ask_model", lambda texts, lang="en": None)
    monkeypatch.setattr(api, "_agent_picks_cache", {("a", "b", "c", *key): {**new, "bet_reasoning": "Ganz neu"}})
    out = api.ai_texts_en("Alpha", "Bravo", "bs")
    assert "Ganz neu" not in out["texts"] and out["complete"] is False
