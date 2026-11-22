"""Every German text the page shows through tr('German', 'English') has a Bosnian version."""
import json
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "frontend" / "src"


def _literal(quote: str, body: str) -> str:
    return body.replace("\\" + quote, quote).replace("\\\\", "\\")


def test_every_plain_tr_text_has_a_bosnian_version():
    app = (SRC / "App.jsx").read_text(encoding="utf-8")
    bs = json.loads((SRC / "strings_bs.json").read_text(encoding="utf-8"))
    germans = set()
    for quote in ("'", '"'):
        pattern = rf"\btr\(\s*{quote}((?:[^{quote}\\]|\\.)*){quote}\s*,\s*(?:'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")\s*(\)|,)"
        for m in re.finditer(pattern, app):
            if m.group(2) == ")":                       # a third argument gives the Bosnian text itself
                germans.add(_literal(quote, m.group(1)))
    # the step lists are [german, english] pairs read through tr(...step)
    for block in re.findall(r"const (?:ANALYZING|BET)_STEPS = \[(.*?)\n\]", app, re.S):
        germans |= {_literal("'", g) for g in re.findall(r"\[\s*'((?:[^'\\]|\\.)*)'\s*,", block)}
    missing = sorted(g for g in germans if g not in bs)
    assert not missing, f"no Bosnian text for: {missing}"
    assert len(germans) > 150


def test_every_team_has_a_bosnian_name():
    de = json.loads((SRC / "team_names_de.json").read_text(encoding="utf-8"))
    bs = json.loads((SRC / "team_names_bs.json").read_text(encoding="utf-8"))
    assert set(de) <= set(bs)
