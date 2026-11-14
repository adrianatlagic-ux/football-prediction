# Logs

Eine Datei pro Wettbewerb. Auf dem Server (Fly) und im Repository gilt dieselbe Struktur.
Der Server schreibt sie selbst (`src/scheduler.py`); GitHub kopiert sie zweimal am Tag ins Repo.

## tips/<wettbewerb>.jsonl  (bundesliga, champions-league, nations-league, sonstige)

Die lesbare Ansicht: eine Zeile pro Spiel mit genau den drei Tipps.

| Feld | Bedeutung |
|---|---|
| `home_team`, `away_team`, `commence_time`, `competition`, `logged_at` | das Spiel |
| `wett_tipp` | der **Wett-Tipp** = der KI-Pick nach den Regeln. `tip` ist der veröffentlichte Tipp, `withheld` der zurückgehaltene Pick, `status` der Grund (`ok`, `no_agreement`, `ai_unsure` ...). `change` und `first_pick` zeigen, wenn die KI ihren Tipp vor Anpfiff geändert hat |
| `modell_wahl` | die **Modell-Wahl**: der vom Modell wahrscheinlichste Ausgang |
| `wahrscheinlichste_wette` | die **wahrscheinlichste Wette** (🎯, Markt, Quote 1,30-2,00) |

Jeder Tipp: `market`, `outcome`, `team`, `best_odds`, `bookmaker`, `probability` (Modell, kalibriert),
`model_probability_raw`, `market_probability`.

## details/<wettbewerb>.jsonl

Dieselben Spiele mit allem, was geloggt wird. Daraus rechnen `grade_bets.py` und die Analyse-Skripte.
`tips/` wird bei jedem Schreiben aus `details/` erzeugt.

| Feld | Bedeutung |
|---|---|
| `bet_tip`, `model_favorite`, `likely_pick` | die drei Tipps (Wett-Tipp, Modell-Wahl, wahrscheinlichste Wette) |
| `agent_eval`, `ai_review_history` | die KI-Bewertung mit Pick, Begründung, Eingaben und jede Änderung vor Anpfiff |
| `bets` | alle bepreisten Wetten des Spiels (Kandidaten) |
| `combined` | Markt-Favorit, Game Pick und ob Modell und KI dem Tipp zustimmen |

**Seit dem 14. November nicht mehr geloggt:** `green_bets`/`red_bets`, `recommendation`, `safest_pick`,
`bet_tip_v1` und `price_tip`. In den älteren Spielen stehen sie noch, weil die Seite ihre
Modell-Trefferquote (`/model-track-record`) daraus berechnet. grün = das Modell sah einen positiven
Erwartungswert, rot = negativ.

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
Sie sind komplett in `details/` und `combos/` enthalten und dienen nur als Sicherung.

## Auswerten

    python3 scripts/grade_bets.py      # Wett-Tipp, Modell-Wahl, wahrscheinlichste Wette und KI-Pick pro Wettbewerb
    python3 scripts/grade_combos.py    # Kombis pro Regel und Größe
