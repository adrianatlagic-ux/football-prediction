# Logs

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
