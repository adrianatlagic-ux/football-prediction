# bet-at-home liefert nur Siegquoten (1X2), keine Zusatzmärkte

**Status:** behoben (13.10.2026): Monatslimit des eigenen Zählers von 7 $ auf 20 $
angehoben; Zählerstand jetzt in `/jobs/status` → `book_budget`
**Gemeldet:** 13.10.2026 (Champions League)
**Betrifft:** Wett-Tabelle, Kombis, Preistipp, `src/book_odds.py`

## Ursache (nachgetragen 13.10.2026)

Der eigene Zähler der App war voll. Auf dem Server, 13.10. abends:

- `data/book_odds/spend.json`: `"2026-10": 7.003`, also über
  `BOOK_MARKETS_BUDGET_USD` = 7,0 (Standardwert, keine Umgebungsvariable gesetzt)
- `/jobs/status` → `book_refreshes`, Champions League 15:45 UTC:
  `"outcome": "1X2 only: Apify budget"`
- `/jobs/status` → `apify`: 2,87 $ von 25 $ im laufenden Zyklus, das
  Apify-Konto war also nicht der Grund

Damit fällt jede bet-at-home-Abfrage, morgens wie in der letzten Stunde, auf
1X2 zurück. Die Schätzung oben (ca. 3,45 $) unterschätzt den Zähler: Er
rechnet je Abfrage pauschal 2,3 Cent pro Spiel, und vom 1. bis 6.10. liefen
viele doppelte Abfragen der letzten Stunde (am 6.10. neunmal in zwei
Minuten), die erst am 10.10. abgestellt wurden (Commit 0a329ba,
höchstens eine Abfrage je Wettbewerb in 20 Minuten).

## Zweite Ursache (13.10.2026, 20:40)

Nach dem Anheben des Limits lief die Abfrage der letzten Stunde um 18:07 UTC
mit allen Märkten (`scrapeMatchMarkets: true`, 9 Spiele, 0,21 $ bezahlt).
Der Scraper lieferte die Spiele mit 1X2, aber **für kein Spiel einen einzigen
Zusatzmarkt** (`markets: []`); am 12.10. waren es für dieselbe Liga mit
derselben Einstellung über 200 je Spiel. Der Code speicherte die leeren
Märkte als „gelesen“, daher kein zweiter Versuch, und die Tabelle zeigte
fast nur Quoten anderer Buchmacher (mit *).

Korrektur (Commits d69a8f7 und folgende):

- Eine volle Abfrage ohne einen einzigen Zusatzmarkt gilt als
  fehlgeschlagen; die 1X2-Quoten werden gespeichert.
- Kosten begrenzt: in der letzten Stunde **ein** weiterer Versuch je
  Wettbewerb und Tag (nach 20 Minuten), morgens **ein** weiterer Versuch
  (nach 30 Minuten).
- Gute Märkte werden nie durch leere überschrieben; sie bleiben mit ihrer
  Lesezeit in `data/book_odds/latest.json` auf dem Fly-Volume.
- Fehlt ein frischer Abruf, zeigt die Seite die letzten guten
  bet-at-home-Märkte statt der Quoten anderer Buchmacher.
- Jede Abfrage steht dauerhaft in `data/logs/book_refresh_log.jsonl`
  (mit Zählerstand); `/jobs/status` zeigt nach einem Neustart den letzten
  Stand je Wettbewerb.

Tests in `tests/test_apify_budget.py` und `tests/test_book_injection.py`.

## Meldung

Am 13.10. (Champions League) zeigte die Seite morgens für die Spiele des Tages
nur Quoten für Sieg, Unentschieden, Niederlage, ohne Handicap, Über/Unter,
Doppelte Chance und „beide treffen“. Etwa eine Stunde vor Anpfiff waren alle
Quoten da (Beobachtung des Nutzers). Laut Nutzer schon früher so („wieder“).

## Ablauf und was daraus folgt

| Zeit | Quelle der angezeigten Quoten | Gesehen |
|---|---|---|
| ab 06:00 UTC | nur bet-at-home aus der Morgenabfrage (`daily_refresh`); die Spielliste der Odds API enthält keine Preise | nur 1X2 |
| ab ca. 1 h vor Anpfiff | Odds API je Spiel (Pinnacle und viele andere Buchmacher, `h2h,totals,spreads`) plus erneute bet-at-home-Abfrage (`refresh_if_due`) | alle Märkte |

Belegt ist damit: **Die Morgenabfrage bei bet-at-home lieferte keine
Zusatzmärkte.** Bis zur letzten Stunde hängen Wett-Tabelle und Kombis
allein an ihr. Dass eine Stunde vorher alles sichtbar war, beweist nicht,
dass bet-at-home dann Zusatzmärkte hatte: Sie können von den anderen
Buchmachern der Odds API stammen.

Möglich sind zwei Wege, die gleich aussehen:

- **Budget-Fallback**: Die Morgenabfrage holte absichtlich nur 1X2, weil eine
  der Budget-Prüfungen nicht bestand (siehe unten). Die neuen Einträge haben
  dann kein Markt-Feld; die Märkte vom Vortag bleiben gespeichert, gelten
  aber nach dem 06:00-Snapshot als veraltet und werden nicht angezeigt.
- **Scraper ohne Märkte**: Die volle Abfrage lief, der Oddsportal-Scraper gab
  aber keine Märkte zurück (`markets` leer).

Auffällig: Die Kombis für den 13.10., aufgezeichnet am 12.10. um 11:02 UTC,
enthielten Handicap- und Über/Unter-Beine. Am Vortag gab es also einen
erfolgreichen vollen Lauf für diese Spiele, obwohl die Morgenabfrage des
12.10. (Horizont bis 13.10. 12:00 UTC) sie nicht erfasst. Woher dieser Lauf
kam (Neustart, Handlauf), ist zu klären.

## Was die Logs im Repo belegen können und was nicht

Eine erste Auswertung von `data/bet_log.jsonl` und `data/combo_log.jsonl`
schien den Fehler zu bestätigen. Sie war falsch:

- **Das Wett-Log speichert je Markt nur die beste Quote** und deren
  Buchmacher (`best_odds`, `bookmaker`; `bookmaker_offers` ist leer). Zahlt
  ein anderer Buchmacher mehr, taucht die bet-at-home-Quote dieses Markts im
  Log nicht auf. In der letzten Stunde vor Anpfiff liefert die Odds API viele
  Buchmacher; dort steht bet-at-home deshalb oft nur bei 1X2. Das sagt nichts
  darüber, welche Märkte bet-at-home hatte.
- **Kombis aus lauter 1X2-Beinen** (13.10. ab 06:15 UTC) belegen ebenfalls
  nichts: Die Regeln wählen Beine nach Markt-Wahrscheinlichkeit, Quote und
  Zustimmung des Modells und können auch bei vollständigen Märkten nur 1X2
  wählen.

Nicht erklärt ist ein Einzelfall vom 10.10.: Für Leipzig – Frankfurt (Anpfiff
16:30 UTC) hat der Preistipp `book_fetched_at` 15:39, aber kein
`book_markets_fetched_at`. Ein Eintrag ohne Markt-Zeitstempel entsteht nur
durch eine reine 1X2-Abfrage ohne Markt-Feld (`daily_refresh` im
Budget-Fallback), nicht durch die Abfrage der letzten Stunde
(`refresh_if_due`). Das passt nicht zum Zeitpunkt und wäre zu prüfen.

## Warum es sich nicht klären lässt

Ob eine Abfrage alle Märkte holte, nur 1X2 (Budget-Fallback) oder
fehlschlug, steht nur in `book_odds.REFRESH_LOG` im Arbeitsspeicher
(`/jobs/status` → `book_refreshes`). Es wird nicht gespeichert und ist nach
einem Neustart weg. Die Logs im Repo enthalten die bet-at-home-Märkte nur,
wo bet-at-home die beste Quote hat.

## Hintergrund: wann der Server nur 1X2 lädt

Bis eine Stunde vor Anpfiff stammen alle Quoten von bet-at-home, gelesen über
Apify (Oddsportal). Morgens (`daily_refresh`, nach dem Snapshot um 06:00 UTC)
und in der letzten Stunde (`refresh_if_due`) wird der volle Markt nur
geladen, wenn der eigene Zähler der App (`BOOK_MARKETS_BUDGET_USD`, 7 $ je
Kalendermonat) und das Monatslimit des Apify-Kontos (minus 1 $ Reserve) es
erlauben; sonst nur 1X2. Nachgerechnet ergeben die Oktober-Abfragen bis
13.10. morgens ca. 3,45 $; der eigene Zähler sollte also nicht erreicht sein.

## Wenn es wieder auftritt

1. Sofort `https://football-prediction.fly.dev/jobs/status` öffnen und
   `book_refreshes`, `apify`, `book_coverage` sichern.
2. Notieren, welches Spiel, welche Uhrzeit und welche Ansicht (Wett-Tabelle,
   Kombi, Preistipp).

## Vorschlag, damit es nachprüfbar wird

1. Ergebnis jeder bet-at-home-Abfrage in `data/logs/book_refresh_log.jsonl`
   schreiben (Zeit, Wettbewerb, Morgen/letzte Stunde, Spiele, davon mit
   Märkten, Ergebnis, Stand des eigenen Zählers und bei Apify) und mit
   `scripts/pull_server_logs.py` ins Repo holen.
2. Im Wett-Log zusätzlich die bet-at-home-Quote je Markt speichern, auch wenn
   ein anderer Buchmacher mehr zahlt.
3. `/jobs/status` um den eigenen Zähler ergänzen (`spent_this_month()`,
   `MONTHLY_BUDGET`).
