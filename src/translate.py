"""English and Bosnian versions of the AI's German texts, made when someone reads them.

The scenario, the AI tip and the KI-Scout research are written once, in
German, for the site's main readers. A visitor who switches to English or
Bosnian gets them translated by a small model (no search) the first time;
every translation is kept on the Fly volume, one file per language, keyed by
the German text, so each text is translated - and paid for - once per language.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Optional

from src.jobs import REPORTS

PATH = REPORTS / "translations_en.json"
LANGUAGES = {"en": "natural British English", "bs": "natural Bosnian (Latin script, ijekavian, as spoken in Bosnia and Herzegovina)"}
# The small model first; gemini-2.5-flash-lite is closed to new accounts.
MODELS = ("gemini-3.5-flash-lite", "gemini-3.8-flash")
MAX_KEPT = 5000
_lock = threading.Lock()


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _path(lang: str):
    return PATH if lang == "en" else REPORTS / f"translations_{lang}.json"


def _load(lang: str = "en") -> dict:
    try:
        return json.loads(_path(lang).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def to_english(texts: list, call=None) -> list:
    return to_language(texts, "en", call)


def to_language(texts: list, lang: str, call=None) -> list:
    """The `lang` version ("en" or "bs") of each German text, in order ("" stays "").

    Texts not yet in the store go to the model in one call; if that fails,
    the German text is returned, so the page always has something to show.
    """
    if lang not in LANGUAGES:
        return list(texts)
    with _lock:
        store = _load(lang)
    wanted = [t for t in dict.fromkeys(t for t in texts if t and _key(t) not in store)]
    if wanted:
        translated = (call or (lambda t: _ask_model(t, lang)))(wanted)
        if translated and len(translated) == len(wanted):
            with _lock:
                store = _load(lang)
                for de, text in zip(wanted, translated):
                    if isinstance(text, str) and text.strip():
                        store[_key(de)] = text.strip()
                if len(store) > MAX_KEPT:
                    store = dict(list(store.items())[-MAX_KEPT:])
                REPORTS.mkdir(parents=True, exist_ok=True)
                _path(lang).write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    return [store.get(_key(t), t) if t else t for t in texts]


def is_translated(text: str, lang: str) -> bool:
    """Whether a translation of this text is kept (an empty text needs none)."""
    return not text or _key(text) in _load(lang)


def _ask_model(texts: list, lang: str = "en") -> Optional[list]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    prompt = (
        f"Translate each German football text in this JSON array into {LANGUAGES[lang]} for "
        "football fans. Keep team and player names, numbers, scores and percentages exactly as they are; "
        "keep any **double asterisks** around the same words in the translation. Respond with ONLY a JSON array "
        "of the same length and order, no code fences.\n" + json.dumps(texts, ensure_ascii=False))
    from google import genai
    client = genai.Client(api_key=api_key)
    for model in MODELS:
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            from src import gemini_usage
            gemini_usage.record("translation", response)
            text = response.text.strip()
            if text.startswith("```"):
                text = text.strip("`").split("\n", 1)[1].rsplit("```", 1)[0]
            out = json.loads(text)
            # An echo of the German is no translation.
            if isinstance(out, list) and len(out) == len(texts) and out != texts:
                return out
        except Exception:
            continue
    return None
