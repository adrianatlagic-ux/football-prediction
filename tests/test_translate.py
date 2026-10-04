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
