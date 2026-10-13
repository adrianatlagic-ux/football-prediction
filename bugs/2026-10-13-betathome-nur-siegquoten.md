# bet-at-home liefert nur Siegquoten (1X2), keine Zusatzmärkte

**Status:** nicht bestätigt
**Gemeldet:** 13.10.2026 (Champions League)
**Betrifft:** Wett-Tabelle, Kombis, Preistipp, `src/book_odds.py`

## Meldung

Am 13.10. schienen für die Spiele des Tages nur bet-at-home-Quoten für Sieg,
Unentschieden, Niederlage geladen zu sein, ohne Handicap, Über/Unter,
Doppelte Chance und „beide treffen“. Später am selben Tag sah der Nutzer
alle Quoten der Spiele. Ob, wann und wie lange Märkte fehlten, ist offen.

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
