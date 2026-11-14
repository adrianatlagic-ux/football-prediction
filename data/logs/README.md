# Logs

Eine Datei pro Wettbewerb. Auf dem Server (Fly) und im Repository gilt dieselbe Struktur.
Der Server schreibt sie selbst (`src/scheduler.py`); GitHub kopiert sie zweimal am Tag ins Repo.

## tips/<wettbewerb>.jsonl  (bundesliga, champions-league, nations-league, sonstige)

Eine Datei pro Wettbewerb, eine Zeile pro Spiel. Sie entsteht einmal kurz vor Anpfiff und wird
danach nur ergänzt (z. B. wenn die KI ihren Tipp ändert). Spalten in dieser Reihenfolge:

| Spalte | Bedeutung |
|---|---|
| `home_team`, `away_team`, `commence_time`, `competition`, `logged_at` | das Spiel |
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
| `policy` | die Regel: `agree`, `ai_pick`, `ki`, `market`, `legacy_v3`, `wett_tipp` |
| `leg_count` | Anzahl der Tipps im Ticket (2er, 3er, 4er) |
| `legs` | die Tipps mit Quote und Wahrscheinlichkeiten |
| `combined_odds`, `estimated_probability` | Gesamtquote und geschätzte Trefferwahrscheinlichkeit |
| `first_kickoff`, `logged_at`, `trigger` | wann das erste Spiel anpfeift, wann geloggt, warum |

Ältere Zeilen (vor dem Umbau) enthalten jede Version eines Tickets ohne `trigger`.

## system/

`alerts.jsonl` - Fehler der Preisquellen. `book_refresh.jsonl` - jeder bet-at-home-Abruf.

## archive/

Die ursprünglichen Einzeldateien (`bet_log_full.jsonl`, `combo_log_full.jsonl`), unverändert.
Sie enthalten alles, auch die entfernten Spalten, und dienen nur als Sicherung.

## Auswerten

    python3 scripts/grade_bets.py      # Wett-Tipp, Modell-Wahl, wahrscheinlichste Wette und KI-Pick pro Wettbewerb
    python3 scripts/grade_combos.py    # Kombis pro Regel und Größe
