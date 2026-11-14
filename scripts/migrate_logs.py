"""Move the old single-file logs into the per-competition layout (src/log_store.py).

    python3 scripts/migrate_logs.py

Nothing is lost: every match and combo row is merged into data/logs/tips/ and
data/logs/combos/, and each original file is moved, unchanged, to
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

## tips/<wettbewerb>.jsonl  (bundesliga, champions-league, nations-league, ...)

Eine Zeile pro Spiel, die einmal kurz vor Anpfiff entsteht und danach nur noch ergänzt wird
(z. B. wenn die KI ihren Tipp ändert). Wichtige Felder:

| Feld | Bedeutung |
|---|---|
| `home_team`, `away_team`, `commence_time`, `competition` | das Spiel |
| `bet_tip` | der **Wett-Tipp**: der KI-Pick nach den Regeln. `tip` ist der veröffentlichte Tipp, `withheld` der zurückgehaltene Pick (mit `status` und Grund) |
| `model_favorite` | die **Modell-Wahl**: der vom Modell wahrscheinlichste Ausgang |
| `likely_pick` | die **wahrscheinlichste Wette** (🎯, Markt, Quote 1,30–2,00) |
| `agent_eval` | die KI-Bewertung mit ihrem Pick, Begründung und Eingaben |
| `ai_review_history` | jede Änderung des KI-Tipps vor Anpfiff |
| `price_tip` | der Preistipp (bet-at-home gegen Pinnacle) |
| `bets` | alle bepreisten Wetten des Spiels (Kandidaten) |
| `green_bets` / `red_bets` | dieselben Wetten nach Modell-Wert: **grün** = das Modell sieht einen positiven Erwartungswert, **rot** = negativ |
| `recommendation` | die beste grüne Wette des Modells (Top-Empfehlung) |
| `combined` | Markt-Favorit, Game Pick und Übereinstimmung von Modell und KI |

## combos/<wettbewerb>.jsonl

Eine Zeile pro Kombi-Ticket. Neue Tickets werden **einmal** geloggt, etwa eine Stunde vor dem
ersten Spiel des Tickets, wenn der KI-Check vor Anpfiff dieses Spiels fertig ist
(`trigger: ki_check_done`), spätestens 30 Minuten vorher (`trigger: last_resort`).

| Feld | Bedeutung |
|---|---|
| `policy` | die Regel: `agree`, `ai_pick`, `ki`, `market`, `legacy_v3`, `wett_tipp` |
| `leg_count` | Anzahl der Tipps im Ticket (2er, 3er, 4er) |
| `legs` | die Tipps mit Quote und Wahrscheinlichkeiten |
| `combined_odds`, `estimated_probability` | Gesamtquote und geschätzte Trefferwahrscheinlichkeit |
| `first_kickoff`, `logged_at`, `trigger` | wann das erste Spiel anpfeift, wann geloggt, warum |

Ältere Zeilen (vor dem Umbau) enthalten jede Version eines Tickets ohne `trigger`.

## system/

`alerts.jsonl` – Fehler der Preisquellen. `book_refresh.jsonl` – jeder bet-at-home-Abruf.

## archive/

Die ursprünglichen Einzeldateien (`bet_log_full.jsonl`, `combo_log_full.jsonl`), unverändert.
Sie sind komplett in `tips/` und `combos/` enthalten und dienen nur als Sicherung.

## Auswerten

    python3 scripts/grade_bets.py      # Wett-Tipps und alle anderen Tipps pro Wettbewerb
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
