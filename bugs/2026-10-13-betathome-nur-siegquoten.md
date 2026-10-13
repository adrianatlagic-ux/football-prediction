# bet-at-home liefert nur Siegquoten (1X2), keine Zusatzmärkte

**Status:** offen, Ursache nicht gesichert
**Gemeldet:** 13.10.2026 (Champions League); ähnlich schon am 10.10. (Bundesliga)
**Betrifft:** Wett-Tabelle, Kombis, Preistipp, `src/book_odds.py`

## Symptom

Auf der Seite stehen für die Spiele des Tages nur bet-at-home-Quoten für Sieg,
Unentschieden, Niederlage. Handicap, Über/Unter, Doppelte Chance, „beide
treffen“ fehlen. Folgen:

- Kombis bestehen nur noch aus 1X2-Tipps oder kommen nicht zustande.
- Der Preistipp kann nur 1X2 mit Pinnacle vergleichen.
- Am 10.10. meldete der Nutzer zusätzlich „gar keine Wetttipps“ (ohne
  bet-at-home-Preise hat ein Spiel vor seiner letzten Stunde keine Quoten).
  Ob das dieselbe Ursache hat, ist nicht belegt.

Laut Nutzer ist das Apify-Guthaben ausreichend.

## Wie die Quoten geladen werden

Bis eine Stunde vor Anpfiff stammen alle Quoten von bet-at-home, gelesen über
Apify (Oddsportal-Scraper `piotrv1001~oddsportal-scraper`). Zwei Abfragen:

| Abfrage | Funktion | Wann |
|---|---|---|
| Morgens | `book_odds.daily_refresh` | nach dem Odds-API-Snapshot um 06:00 UTC, alle Spiele der nächsten 30 h |
| Letzte Stunde | `book_odds.refresh_if_due` | ca. 75 min vor Anpfiff, einmal je Spiel |

Beide holen den vollen Markt (`scrapeMatchMarkets: true`, 0,023 $ je Spiel)
nur, wenn **beide** Budget-Prüfungen bestehen, sonst nur 1X2 (0,003 $):

1. eigener Zähler der App: `spent_this_month() + Kosten <= MONTHLY_BUDGET`
   (`BOOK_MARKETS_BUDGET_USD`, Standard 7 $ je Kalendermonat, gespeichert in
   `data/book_odds/spend.json` auf dem Fly-Volume)
2. Apify-Konto: `apify_budget.allows()`, verbraucht + Kosten <= Monatslimit des
   Kontos (`maxMonthlyUsageUsd`) − 1 $ Reserve

Das Ergebnis jeder Abfrage („full book“, „1X2 only: Apify budget“,
„failed: …“) steht nur in `book_odds.REFRESH_LOG`, also im Arbeitsspeicher,
sichtbar unter `/jobs/status` → `book_refreshes`. Es wird nirgends
gespeichert und ist nach einem Neustart weg.

## Belege aus dem Repo

Quelle: `data/combo_log.jsonl` und `data/bet_log.jsonl`, vom Server per
GitHub-Workflow übernommen. Zeiten in UTC.

**13.10., Champions League, Kombis nach Zeitpunkt der Aufzeichnung**

| Aufgezeichnet | Märkte der Beine |
|---|---|
| 12.10. 11:02 | Over/Under 3.5, Handicap +0.5 |
| 13.10. 02:03 | Handicap +0.5, Handicap −0.5 |
| **13.10. 06:15** | **nur 1X2** |
| 13.10. 08:15 | nur 1X2 |

Die Morgenabfrage um 06:00 brachte nur 1X2. Die vollen Märkte vom Vortag
gelten danach als veraltet (Snapshot gültig bis zum nächsten 06:00) und
fallen heraus.

**13.10., die beiden Spiele um 16:45, Abfrage in der letzten Stunde**

| Spiel | bet-at-home gelesen | `markets_fetched_at` | bet-at-home-Märkte |
|---|---|---|---|
| RC Lens – Sporting Lisbon | 15:45 | 15:45 | nur 1X2 |
| Sabah FK – Slavia Praha | 15:45 | 15:45 | nur 1X2 |

Auch die Abfrage in der letzten Stunde lieferte also keine Zusatzmärkte. Weil
`markets_fetched_at` gesetzt ist, lief sie entweder als Budget-Fallback
(`refresh_if_due` setzt dann `markets: {}`) oder als volle Abfrage, bei der
der Scraper keine Märkte zurückgab.

**10.10., Bundesliga, Abfragen in der letzten Stunde**

| Anpfiff | Spiel | bet-at-home gelesen | `markets_fetched_at` | Märkte in der Wett-Tabelle |
|---|---|---|---|---|
| 13:30 | Union Berlin – Elversberg | 12:33 | 12:33 | 10 |
| 13:30 | Mainz – Leverkusen | 12:33 | 12:33 | 12 |
| 13:30 | Paderborn – Stuttgart | 12:33 | 12:33 | 12 |
| 13:30 | Hoffenheim – HSV | 12:33 | 12:33 | 14 |
| 13:30 | **Augsburg – Bayern** | 12:33 | 12:33 | **1 (nur 1X2)** |
| 16:30 | **Leipzig – Frankfurt** | 15:39 | **leer** | **keine** |

Am 11.10. hatten Köln – Gladbach (14 Märkte) und Freiburg – Schalke (9) die
vollen Märkte.

## Einordnung der möglichen Ursachen

| Ursache | passt zu | spricht dagegen |
|---|---|---|
| **A. Eigener 7-$-Zähler der App ausgeschöpft** | 13.10. ganzer Tag nur 1X2 | Nachgerechnet mit den echten Spielplänen ergeben die Oktober-Abfragen bis 13.10. morgens nur ca. 3,45 $; der Zähler steigt nur, also hätte er am 11.10. nicht wieder volle Märkte erlaubt, wenn er am 10.10. schon voll gewesen wäre |
| **B. Monatslimit des Apify-Kontos** (`maxMonthlyUsageUsd`, nicht das Guthaben) | 13.10.; am 3.10. war das Konto schon einmal am Limit (`src/apify_budget.py`) | Nutzer sagt, das Guthaben reicht. Das Limit ist aber eine eigene Einstellung im Konto und kann niedriger als das Guthaben sein |
| **C. Scraper liefert für einzelne Spiele oder ganze Läufe keine Märkte** | 10.10.: in derselben Abfrage einzelne Spiele ohne Märkte, andere mit; das kann kein Budget sein, weil das Budget für die ganze Abfrage gilt | – |

Am wahrscheinlichsten ist C, eventuell zusammen mit A oder B. Belegt ist
keine davon, weil das Ergebnis der Abfragen nicht gespeichert wird.

Hinweis zu Leipzig – Frankfurt (10.10.): Ein Eintrag ohne
`markets_fetched_at` entsteht nur durch eine 1X2-Abfrage ohne Markt-Feld
(Morgenabfrage im Budget-Fallback, `daily_refresh`), nicht durch
`refresh_if_due`. Das passt nicht zum Zeitpunkt 15:39 und sollte beim
Beheben mit untersucht werden.

## So lässt sich die Ursache bestätigen

1. `https://football-prediction.fly.dev/jobs/status` → `book_refreshes`
   (Ergebnis je Wettbewerb), `apify` (`used`, `limit`), `book_coverage`.
   Nur gültig, wenn der Server seit der Abfrage nicht neu gestartet ist.
2. Eine volle Abfrage direkt auf dem Server, ohne Budget-Prüfung (ca. 0,28 $):

   ```bash
   fly ssh console -a football-prediction -C "python3 -c \"
   from src import book_odds
   f = book_odds.fetch_league('soccer_uefa_champs_league', 12, full_book=True)
   book_odds.store('soccer_uefa_champs_league', f)
   print('Spiele:', len(f), '| mit allen Maerkten:', sum(bool(x.get('markets')) for x in f))
   \""
   ```

   Alle Spiele mit Märkten → Scraper in Ordnung, Ursache A oder B. Keine
   oder nur einzelne → Ursache C. Abbruch nach ca. 5 Minuten → Zeitlimit
   (`urlopen(timeout=300)`).
3. Der eigene Zähler: `fly ssh console -a football-prediction -C "cat /app/data/book_odds/spend.json"`.

## Vorschlag zur Behebung

1. **Ergebnis jeder Abfrage speichern**: eine Zeile je Abfrage in
   `data/logs/book_refresh_log.jsonl` (Zeit, Wettbewerb, Morgen/letzte
   Stunde, Spiele, davon mit Märkten, Ergebnis, Stand des eigenen Zählers und
   bei Apify). `/logs/book_refresh_log` freigeben und in
   `scripts/pull_server_logs.py` mitnehmen, damit es im Repo landet.
2. **Zweiter Versuch** für Spiele, die in einer vollen Abfrage ohne Märkte
   zurückkommen (Ursache C).
3. **Grund auf der Seite anzeigen**, wenn ein Spiel nur 1X2 hat („bet-at-home
   hat für dieses Spiel gerade nur Siegquoten geliefert“), statt die Märkte
   kommentarlos wegzulassen.
4. **`/jobs/status` um den eigenen Zähler ergänzen** (`spent_this_month()`
   und `MONTHLY_BUDGET`).
5. Je nach Befund: `BOOK_MARKETS_BUDGET_USD` erhöhen (Ursache A),
   Monatslimit bei Apify anheben oder die Kader-Abfragen
   (`src/squad_data.py`, 0,05 $ je Team) seltener laufen lassen (Ursache B).
