# Club-Modell und nachvollziehbare Wett-Rendite

Stand: 18. September 2026. Lokal implementiert und geprüft; nicht deployed.

Nachtrag 19. September: Die weitere Tipp-Auswahl einschließlich korrigierter
EV-/Kelly-Berechnung ist in `bet_selection_v1.md` beschrieben. Die folgenden
Modell-Testresultate bleiben unverändert; der Abschnitt zur damals noch
binären Preisberechnung beschreibt den vorherigen Stand.

Ziel ist eine messbare Rendite bei tatsächlich angebotenen Quoten. Eine höhere
Trefferquote allein genügt dafür nicht. Dieser Durchlauf beweist keinen Gewinn.

## Modellprüfung

Korrigiert wurden die Klassenreihenfolge beim Log-Loss, die chronologische
Auswahl der letzten Torstatistiken und der aus dem WM-Modell übernommene
15-Prozent-Toraufschlag. Club-Poisson benutzt keine FIFA-Korrektur mehr.
Trainingsfeatures berücksichtigen keine Ergebnisse vom selben oder späteren Tag.
Vorhersagen mit einem bereits auf dem Spieltag trainierten Modell werden abgelehnt.

Die 552 Marktwertzeilen haben keinen belegten Veröffentlichungszeitpunkt.
Die produktive V3-Feature-Regel verwendet deshalb aktuell keine dieser Werte;
fehlende Werte werden explizit markiert. Vorjahreswerte wurden separat als
unbestätigte Sensitivitätsanalyse untersucht, nicht zur Auswahl zugelassen.

Verglichen wurden saisonweise eingefrorene Modelle und monatliches Neutraining,
jeweils mit und ohne Temperaturkalibrierung auf zeitlich früheren Daten.
Auswahlkriterium war der mittlere Log-Loss über Bundesliga und Champions League
in 2021/22, 2022/23 und 2023/24. Gewählt wurde `verified_only/monthly/raw`.
Der Vorsprung im Entwicklungstest ist klein: 0,98385 statt 0,98525 beim
eingefrorenen unkalibrierten Modell. Kein Nachweis statistischer Überlegenheit.

| Rückblick 2025/26 | Spiele | Trefferquote 1X2 | Log-Loss | Brier (Summe über 3 Klassen) |
|---|---:|---:|---:|---:|
| Bundesliga | 306 | 53,6 % | 0,9866 | 0,5862 |
| Champions League | 189 | 51,3 % | 0,9778 | 0,5820 |

2025/26 wurde bereits in früheren Experimenten betrachtet und ist kein
unangetasteter Test. CL-Saisons fehlen, unter anderem 2024/25; die Rohdaten
sind zudem noch nicht vollständig auf 90-Minuten-Ergebnisse statt Verlängerung
geprüft. Historische Buchmacherquoten fehlen. Gegenüber alten, anders
aufgebauten Tests lässt sich keine saubere Verbesserung behaupten.

Der lokale Kandidat `club_model_verified.joblib` enthält Training bis
2026-09-13. Die API verwendet diesen neuen Dateinamen. Alte Artefakte werden
nicht still mit den neuen Features weiterverwendet. Monatliche Aktualisierung
wurde getestet, aber kein automatischer Trainingsjob installiert.

## Wettprotokoll

`scripts/log_club_bets.py` speichert geänderte Snapshots innerhalb der letzten
24 Stunden vor Anpfiff append-only mit Quote, Zeit, Wettbewerb und Vorhersage.
Ergebnisbeobachtungen werden separat angehängt. Wiederholungsspiele werden
über Wettbewerb, Teams und Anstoß unterschieden. GitHub Actions ist dafür
angepasst, wird aber erst nach Veröffentlichung dieser Änderungen aktiv.

`scripts/audit_club_bets.py` wählt je Spiel den letzten gültigen Snapshot vor
Anpfiff und bewertet die tatsächlich protokollierten Rollen und Märkte.
Viertel-Handicaps, halbe Gewinne/Verluste und Rückzahlungen werden korrekt
abgerechnet. ROI verwendet einen festen Einsatz von einer Einheit pro Tipp;
auch zurückgezahlte Einsätze zählen zum Umsatz. Das ist keine persönliche
Kontorendite und keine Simulation der Kelly-Einsätze. Nur ausdrücklich als
reguläre Spielzeit bestätigte Resultate werden abgerechnet.

Der Altbestand enthält 14 Einträge: 10 außerhalb der Club-Wettbewerbe und
4 nach Anpfiff. **Null gültige Club-Snapshots, deshalb keine belastbare ROI.**
Die bisherigen Dateien bleiben erhalten. ESPN liefert hier aktuelle Ergebnisse,
keine vollständige historische Nachlieferung; ausgefallene Loggerläufe können
daher Lücken hinterlassen. Es werden keine Quoten rückwirkend erfunden.

Die bestehenden Auswahlregeln und Edge-/Kelly-Anzeigen sind damit noch nicht
als profitabel validiert. Insbesondere die binäre EV-/Kelly-Näherung für Märkte
mit Rückzahlung oder geteiltem Einsatz ist separat zu überarbeiten; die neue
Abrechnung der realisierten Rendite löst diese Auswahlfrage nicht automatisch.
Bis eine vorab festgelegte Auswahlregel an neuen Quoten einen belastbaren
Vorteil zeigt, ist das System eine zu prüfende Prognose, keine bewiesene
Einnahmequelle. Auch „keine Wette“ muss ein mögliches Ergebnis bleiben.

## Reproduzieren

```sh
python3 -m pytest tests -q
python3 scripts/validate_club_retraining.py --out data/model_reports/NEW_RUN --save-model NEW_MODEL.joblib
python3 scripts/log_club_bets.py --api http://localhost:8000
python3 scripts/audit_club_bets.py
```

Ein neuer Berichtspfad ist erforderlich, damit frühere Auswertungen erhalten
bleiben. Vollständige Ergebnisse und Quelldatei-Hashes liegen unter
`data/model_reports/retraining_v3/`; der Audit des Altbestands unter
`data/model_reports/legacy_bet_audit.json`.
