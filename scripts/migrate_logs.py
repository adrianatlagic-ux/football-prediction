"""Move the old single-file logs into the per-competition layout (src/log_store.py).

    python3 scripts/migrate_logs.py

Nothing is lost: every match is merged into data/logs/tips/, every combo row into data/logs/combos/, and each original file is moved, unchanged, to
data/logs/archive/. Safe to run again - it only acts on old files it finds.
The server runs it on every start (src/scheduler.py), for the files it wrote
before the new layout existed.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src import log_store  # noqa: E402

README = """# Logs

Eine Datei pro Wettbewerb. Auf dem Server (Fly) und im Repository gilt dieselbe Struktur.
Der Server schreibt sie selbst (`src/scheduler.py`); GitHub kopiert sie zweimal am Tag ins Repo.

## tips/<wettbewerb>.jsonl  (bundesliga, champions-league, nations-league, sonstige)

Eine Datei pro Wettbewerb, eine Zeile pro Spiel. Sie entsteht einmal kurz vor Anpfiff und wird
danach nur ergänzt (z. B. wenn die KI ihren Tipp ändert). Spalten in dieser Reihenfolge:

| Spalte | Bedeutung |
|---|---|
| `home_team` | Heimmannschaft |
| `away_team` | Auswärtsmannschaft |
| `commence_time` | Anpfiff (UTC) |
| `competition` | Wettbewerb |
| `logged_at` | wann das Spiel geloggt wurde |
| `bet_tip` | der **Wett-Tipp** = der KI-Pick nach den Regeln. `tip` ist der veröffentlichte Tipp, `withheld` der zurückgehaltene Pick, `status` der Grund (`ok`, `no_agreement`, `ai_unsure` ...); `change` und `first_pick` zeigen eine Änderung der KI vor Anpfiff |
| `model_favorite` | die **Modell-Wahl**: der vom Modell wahrscheinlichste Ausgang |
| `likely_pick` | die **wahrscheinlichste Wette** (🎯, Markt, Quote 1,30-2,00) |
| `combined` | ob Modell und KI dem Tipp zustimmen (`model_agrees`, `agent_agrees`, `agreement_count`), dazu Markt-Favorit und Game Pick |
| `agent_eval` | die KI-Bewertung: Pick, Begründung, Eingaben |
| `ai_review_history` | jede Änderung des KI-Tipps vor Anpfiff |
| `bets` | alle bepreisten Wetten des Spiels (Kandidaten) |

Jeder Tipp hat `market`, `outcome`, `team`, `best_odds`, `bookmaker`, `probability` (Modell),
`model_probability_raw`, `market_probability` und weitere Preisangaben.

**Seit dem 14. November nicht mehr geloggt und auch aus den alten Zeilen entfernt:**
`green_bets`/`red_bets`, `recommendation`, `safest_pick`, `bet_tip_v1`, `price_tip`.
(In `archive/bet_log_full.jsonl` stehen sie weiter.) Ältere Spiele haben kein `bets`.

## combos/<wettbewerb>.jsonl

Eine Zeile pro Kombi-Ticket. Neue Tickets werden **einmal** geloggt, etwa eine Stunde vor dem
ersten Spiel des Tickets, wenn der KI-Check vor Anpfiff dieses Spiels fertig ist
(`trigger: ki_check_done`), spätestens 30 Minuten vorher (`trigger: last_resort`).

| Feld | Bedeutung |
|---|---|
| `policy` | die Regel, nach der das Ticket gebaut wurde (siehe unten) |
| `leg_count` | Anzahl der Tipps im Ticket (2er, 3er, 4er) |
| `legs` | die Tipps mit Quote und Wahrscheinlichkeiten |
| `combined_odds`, `estimated_probability` | Gesamtquote und geschätzte Trefferwahrscheinlichkeit |
| `first_kickoff`, `logged_at`, `trigger` | wann das erste Spiel anpfeift, wann geloggt, warum |

Die Regeln (`policy`):

| Regel | Bedeutung |
|---|---|
| `ai_pick` | **die Regel, die die Seite zeigt:** nur die veröffentlichten KI-Picks, Ticket mindestens Quote 3,0, verschiedene Spiele bevorzugt |
| `agree` | nur Tipps, bei denen das Modell zustimmt; KI-Picks zuerst, Ticket mindestens Quote 3,0 (angezeigt 4.-11. Oktober) |
| `ki` | nur KI-Picks, bei denen das Modell zustimmt und die die KI vor Anpfiff nicht geändert hat (nur geloggt, seit 11. Oktober) |
| `market` | die Tipps mit der höchsten Markt-Wahrscheinlichkeit, ohne Modell-Filter (Regel ab 26. September) |
| `legacy_v3` | die alte Regel vor dem 26. September: niedrigere von Modell und Markt, Modell mindestens 55 %, Quote ab 1,20 (nur zum Vergleich geloggt) |
| `wett_tipp` | **nicht mehr in Gebrauch**; kommt nur in 7 alten Zeilen vor |

Ältere Zeilen (vor dem Umbau) enthalten jede Version eines Tickets ohne `trigger`.

## system/

`alerts.jsonl` - Fehler der Preisquellen. `book_refresh.jsonl` - jeder bet-at-home-Abruf.

## archive/

Die ursprünglichen Einzeldateien (`bet_log_full.jsonl`, `combo_log_full.jsonl`), unverändert.
Sie enthalten alles, auch die entfernten Spalten, und dienen nur als Sicherung.

## Auswerten

    python3 scripts/grade_bets.py      # Wett-Tipp, Modell-Wahl, wahrscheinlichste Wette und KI-Pick pro Wettbewerb
    python3 scripts/grade_combos.py    # Kombis pro Regel und Größe
"""


def _archive(path: Path, logs: Path) -> Path:
    target = log_store.archive_path(path.stem.replace("bet_log", "bet_log_full")
                                    .replace("combo_log", "combo_log_full") + ".jsonl", logs)
    n = 1
    while target.exists():
        n += 1
        target = target.with_name(f"{target.stem.split('__')[0]}__{n}.jsonl")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(target))
    return target


def migrate(logs: Path, bet_files: list, combo_files: list) -> dict:
    import log_bets
    import log_combos
    import pull_server_logs
    logs = Path(logs)
    done = {"matches": 0, "combos": 0, "archived": []}

    # Earlier versions of this layout had a short tips/ and a full details/ (or a
    # full tips/). One file per competition now: the full entries, in tips/.
    folder = log_store._dir("details", logs)
    detail_files = sorted(folder.glob("*.jsonl")) if folder.is_dir() else []
    short = [p for p in log_store.files("tips", logs)
             if any("wett_tipp" in e for e in log_store._read(p)[:1])]
    if detail_files or short:
        merged = []
        pull_server_logs.merge_bets(merged, [e for p in detail_files for e in log_store._read(p)])
        pull_server_logs.merge_bets(merged, [e for p in log_store.files("tips", logs) if p not in short
                                             for e in log_store._read(p)])
        for path in short + detail_files:
            path.unlink()
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
        log_store.write_tips(merged, logs)
        done["matches"] += len(merged)

    for path in bet_files:
        path = Path(path)
        if not path.exists():
            continue
        legacy = log_bets._load_log(path)
        current = log_store.load_tips(logs)
        done["matches"] += pull_server_logs.merge_bets(current, legacy)
        log_store.write_tips(current, logs)
        done["archived"].append(str(_archive(path, logs)))

    for path in combo_files:
        path = Path(path)
        if not path.exists():
            continue
        legacy = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        ident = lambda e: (log_combos._key(e), log_combos.signature(e), e.get("logged_at"))
        have = {ident(e) for e in log_store.load_combos(logs)}
        new = [e for e in legacy if ident(e) not in have]
        log_store.append_combos(new, logs)
        done["combos"] += len(new)
        done["archived"].append(str(_archive(path, logs)))

    # System logs that sat directly in data/logs.
    for old, new in (("alerts.jsonl", "alerts.jsonl"), ("book_refresh_log.jsonl", "book_refresh.jsonl")):
        src, dst = logs / old, log_store.system_path(new, logs)
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

    # The categories that are no longer logged come out of the old lines too.
    entries = log_store.load_tips(logs)
    if any(k in e for e in entries for k in log_store.DROPPED):
        for e in entries:
            for k in log_store.DROPPED:
                e.pop(k, None)
        log_store.write_tips(entries, logs)

    readme = logs / "README.md"
    if not readme.exists() or readme.read_text(encoding="utf-8") != README:
        logs.mkdir(parents=True, exist_ok=True)
        readme.write_text(README, encoding="utf-8")
    return done


def legacy_files(root: Path = ROOT) -> tuple:
    """Where the old logs sat: committed in data/, or written by the server in data/logs/."""
    bets = [root / "data" / "bet_log.jsonl", root / "data" / "logs" / "bet_log.jsonl"]
    combos = [root / "data" / "combo_log.jsonl", root / "data" / "logs" / "combo_log.jsonl"]
    return bets, combos


def main():
    bets, combos = legacy_files()
    result = migrate(log_store.LOGS, bets, combos)
    print(f"{result['matches']} Spiele und {result['combos']} Kombi-Zeilen übernommen.")
    for path in result["archived"]:
        print("  archiviert:", path)
    if not result["archived"]:
        print("  Keine alten Dateien gefunden.")


if __name__ == "__main__":
    main()
