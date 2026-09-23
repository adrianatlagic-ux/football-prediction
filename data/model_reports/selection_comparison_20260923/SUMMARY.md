# Ergebnis des Auswahlvergleichs – 23. September 2026

**Die getesteten Alternativen liefern keinen belastbaren Grund, die bisherige Kelly-Auswahl zu ersetzen.** Auf diesem Testangebot schneidet sie insgesamt besser ab als maximales EV oder die getestete Kombination aus EV und Trefferchance. Profitabilität ist damit nicht belegt.

## Welche Daten tatsächlich verwendet wurden

- 1.224 Bundesliga-Spiele aus 2021/22, 2022/23, 2023/24 und 2025/26. Alle Zuordnungen stimmen bei Datum, Heim-/Auswärtsteam und Endergebnis überein.
- Bereits gespeicherte H/D/A-Vorhersagen des lokalen Modells `verified_only/monthly/raw`. Für jedes Spiel liegt das Trainingsende vor dem Vorhersagezeitpunkt. Kein neues ML-Training und keine Veränderung der Modellwahrscheinlichkeiten.
- Kostenlose historische Bet365-Quoten von [Football-Data](https://www.football-data.co.uk/germanym.php), inklusive [Spaltenerklärung](https://www.football-data.co.uk/notes.txt). Primär vor Schließung erhobene Quoten, separat Schlussquoten als Sensitivitätsprüfung. Keine fiktiven Quoten, keine kostenpflichtigen Abrufe.
- Der reine 1X2-Vergleich benutzt die gespeicherten Prognosen. Für den zusätzlichen Vergleich über mehrere Märkte wurde die aktuelle Poisson-Berechnung mit ausschließlich früheren Ergebnissen und den gespeicherten H/D/A-Wahrscheinlichkeiten rekonstruiert. Dies sind **nachträgliche historische Simulationen, keine damals gespeicherten Live-Tipps**.
- Angebot: 1X2, Over/Under 2,5 und die jeweils angebotene asiatische Handicap-Hauptlinie bei einem Buchmacher. Andere Linien, Wettbewerbe und KI-Analysen wurden nicht erfunden.

## Vergleich auf dem rekonstruierten Mehrmarkt-Angebot

Alle Regeln schließen auffällige Tipps aus, verwenden dieselben Kandidaten und dieselben bekannten Value-Filter. Pro ausgewähltem Tipp wird eine Einheit eingesetzt; höchstens ein Tipp pro Spiel. Spiele ohne zulässigen Kandidaten werden ausgelassen. Sortierung und Einsatzhöhe sind getrennt: Kelly sortiert, die Testeinsätze bleiben konstant.

| Auswahlregel | Wetten | Profit in Einheiten | Rendite auf Einsätze |
|---|---:|---:|---:|
| Bisherige Kelly-Regel, auf das Testangebot angewendet | 965 | −29,16 | −3,0 % |
| Größter EV | 965 | −43,88 | −4,5 % |
| Höchste Trefferchance unter Tipps mit mindestens 80 % des besten EV | 965 | −52,53 | −5,4 % |
| Kelly-Tipp nur bei exakter Zustimmung von Model’s Choice | 30 | −3,09 | −10,3 % |
| Kelly-Tipp nur bei exakter Zustimmung des 1X2-Marktfavoriten | 24 | +0,11 | +0,5 % |

Die 80-%-Regel wurde vor der Ergebnisberechnung festgelegt und nicht nachträglich optimiert. Sie ist eine getestete Hypothese, keine Empfehlung. Die Zustimmungsvarianten lassen den ursprünglichen Kelly-Tipp nur durch oder enthalten sich; sie suchen keinen anderen zustimmenden Tipp. Da Model’s Choice und Marktfavorit 1X2-Tipps sind, schließt exakte Marktidentität viele Handicap- und Torwetten aus. Deshalb fallen die Fallzahlen stark ab. Die 24 Wetten der letzten Zeile sind kein Profitnachweis.

Bei maximiertem EV ändert sich die Entscheidung in 227 Spielen. Die Kelly-Baseline wählt 655 Handicaps, 236 Torwetten und 74 1X2-Tipps; maximales EV wählt 463 Handicaps, 248 Torwetten und 254 1X2-Tipps. Das ist ein beobachteter Unterschied in diesem Datensatz, keine Empfehlung für eine Wettart.

## Stabilität und Unsicherheit

- Mit Schlussquoten statt früher erhobenen Quoten: Kelly **−3,2 %**, maximales EV **−8,5 %**, Trefferchance nahe dem besten EV **−6,2 %**. Es werden jeweils alle Regeln neu mit demselben Schlussquotenangebot bewertet, nicht früh ausgewählte Tipps zu späteren Preisen abgerechnet.
- Im späteren Abschnitt 2025/26 mit früheren Quoten: Kelly **−20,5 %**, maximales EV **−21,6 %**, Trefferchance-Regel **−22,6 %**. Alle drei verlieren deutlich. Die Saison war bereits Gegenstand früherer Modellversuche und ist kein unangetasteter Test.
- Das beschreibende 95-%-Intervall der gesamten Kelly-Rendite reicht bei wochenweisem Bootstrap von ungefähr **−9,3 % bis +3,4 %**. Das gepaarte Intervall des Profitunterschieds EV gegenüber Kelly umfasst ebenfalls null. Der beobachtete Vorsprung ist kein gesicherter zukünftiger Vorteil.
- Der isolierte Vergleich mit ausschließlich gespeicherten 1X2-Prognosen ergibt Kelly **−4,6 %**, maximales EV **−4,2 %**, Trefferchance-Regel **−3,3 %**, jeweils 360 Wetten. EV und Kelly unterscheiden sich dort nur in fünf Entscheidungen. Die Rangfolge hängt also auch vom angebotenen Wettmarkt ab.
- Rückzahlungen zählen zum Umsatz. Halbe Gewinne/Verluste werden anteilig abgerechnet. Drawdown wird am Tagesende gemessen; alle Detailwerte stehen in `results.json`.

## Was wir daraus ableiten können

1. **Einfach nach höchstem EV umsortieren ist durch diesen Vergleich nicht gerechtfertigt.** Es beseitigt die Verluste nicht und schneidet im rekonstruierten Mehrmarkt-Test schlechter ab.
2. **Eine Pflicht zur Signalübereinstimmung ist kein belegter Ausweg.** Die Stichproben schrumpfen drastisch; eine marginal positive Zeile wäre Rosinenpickerei.
3. **Es gibt noch keinen nachgewiesenen besseren Selektor.** Die bestehende Auswahl bleibt die Vergleichsbasis. Dieser Bericht rechtfertigt keine automatische Umstellung der Website.
4. **Nations-League-Tipps und historische KI-Zustimmung sind damit nicht bewertet.** Nationalmannschaften nutzen ein anderes Modell. Ein besseres Bundesliga-Ergebnis wäre nicht automatisch übertragbar.

## Datenlücken und Reproduzierbarkeit

Die aktuellen Worktree-Logs enthalten zehn ältere einfache WM-Einträge ohne vollständige Alternativen. Im Hauptcheckout liegen vier umfangreiche Club-Snapshots, die erst nach Anpfiff gespeichert wurden. Das zusätzliche WM-Archiv enthält 14 vollständiger bestückte Vorab-Snapshots, davon nur zwei mit KI-Auswahl; ihre Ergebnisse ließen sich nicht exakt mit dem lokalen internationalen Ergebnisbestand verbinden. Diese Dateien wurden nicht als belastbarer Auswahltest ausgegeben. Die neuen Dateien `club_bet_snapshots.jsonl` und `club_results.jsonl` fehlen lokal. Zudem nimmt der derzeitige Club-Audit Nations-League-Spiele nicht an. Diese Lücken wurden hier nicht durch erfundene Zeitstempel, Ergebnisse oder KI-Antworten geschlossen.

Historische Bet365-Quoten enthalten keine Updatezeit je Angebot. Deshalb werden weder unsere 30-Minuten-Frischeprüfung noch der Abruf exakt eine Stunde vor Anpfiff behauptet. Auch die Marktvergleichswahrscheinlichkeit stammt hier vom vollständigen Einzelanbieter-Markt und nicht aus dem aktuellen Mehranbieter-Feed. Die Drei-Anbieter-Stresstest-Strategie ist deshalb nicht Teil dieser Renditetabelle.

Die Originaldateien und ihre Hashes liegen unter `data/odds_archive/football_data_20260923/`. Die Daten wurden in einen separaten Forschungsordner übernommen, nicht in den Trainingsdatenbestand. `protocol.json` dokumentiert vor der Auswertung festgelegte Regeln und Quell-/Codehashes. `decisions.jsonl` enthält jede Entscheidung und jeden Kandidaten. `README.md` enthält alle Saison- und Quotenvarianten.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/compare_bet_selection.py \
  --odds-dir data/odds_archive/football_data_20260923 \
  --out /tmp/football-selection-comparison-new-run
```

Validierung: 26 gezielte Tests bestanden; zusätzlich alle 8.611 ausgewählten Einzelabrechnungen über sämtliche Varianten unabhängig gegen die Ergebnis-/Handicap-Regeln geprüft. Website, Modellartefakte und aktive Auswahl wurden für diesen Vergleich nicht geändert. Kein Commit oder Deployment.
