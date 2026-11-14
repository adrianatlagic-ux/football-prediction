# Logs

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

| Spalte | Bedeutung |
|---|---|
| `logged_at` | wann das Ticket geloggt wurde |
| `first_kickoff` | Anpfiff des ersten Spiels im Ticket (ab da ist es nicht mehr platzierbar) |
| `date` | der Spieltag des Tickets |
| `competition` | Wettbewerb |
| `policy` | die Regel, nach der das Ticket gebaut wurde (siehe unten) |
| `leg_count` | Anzahl der Tipps im Ticket (2er, 3er, 4er) |
| `quote_basis` | woher die Quoten kommen. `best_singles_mixed_books` = je Tipp die beste Quote irgendeines Buchmachers, die Gesamtquote ist also nur das Produkt und nicht bei einem Buchmacher als Kombi buchbar. `single_book` = alle Tipps bei demselben Buchmacher, wirklich so buchbar; fehlt in den ältesten Zeilen (dort gilt `single_book`) |
| `combined_odds` | Gesamtquote des Tickets |
| `estimated_probability` | geschätzte Trefferwahrscheinlichkeit (vorsichtig, aus dem Markt) |
| `model_probability` | Trefferwahrscheinlichkeit laut Modell |
| `legs` | die einzelnen Tipps mit Wette, Quote, Buchmacher und Wahrscheinlichkeiten |
| `trigger` | warum geloggt: `ki_check_done` oder `last_resort`; fehlt in alten Zeilen |

Die Regeln (`policy`):

| Regel | Bedeutung |
|---|---|
| `ai_pick` | **die Regel, die die Seite zeigt:** nur die veröffentlichten KI-Picks, Ticket mindestens Quote 3,0, verschiedene Spiele bevorzugt |
| `agree` | **nur zum Vergleich:** wie `ai_pick`, aber mit dem alten Modell-Veto (Tipps, die das Modell klar unter dem Markt sieht, fallen raus); KI-Picks zuerst, Ticket mindestens Quote 3,0. Die Seite zeigt sie nicht, sie wird weiter geloggt |
| `ki` | nur KI-Picks, bei denen das Modell zustimmt und die die KI vor Anpfiff nicht geändert hat (nur alte Zeilen, seit 14. November nicht mehr geloggt) |
| `market` | die Tipps mit der höchsten Markt-Wahrscheinlichkeit, ohne Modell-Filter (nur alte Zeilen, seit 14. November nicht mehr geloggt) |
| `legacy_v3` | die alte Regel vor dem 26. September: niedrigere von Modell und Markt, Modell mindestens 55 %, Quote ab 1,20 (nur alte Zeilen, seit 14. November nicht mehr geloggt) |
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
