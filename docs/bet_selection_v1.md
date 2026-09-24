# Tipp-Auswahl: erster lokaler Entwicklungsstand

Weiterentwicklung: `game_pick_v1.md` beschreibt die inzwischen aktive Auswahl
des Game Picks. Der hier beschriebene Marktfavorit ist nun eine Vergleichsstrategie.

Branch: `codex/bet-selection`, erstellt auf `53616fc` unter Mitnahme der
uncommittierten V3-Modell-/Logging-Arbeit. Kein Commit, Push oder Deployment.
Die Änderungen dieses Schritts betreffen die Auswahl und Bewertung der Tipps;
es wurde kein weiteres Modelltraining gestartet und kein bezahlter API-Aufruf
ausgeführt. Die zuvor lokal erstellte Modellvariante bleibt ein Kandidat.

## Einheitliche Bedeutung der Anzeigen

Game Pick ist wieder ein Marktfavorit als Vergleichsbasis, keine Behauptung
eines positiven Erwartungswertes. Gewählt wird die höchste aus vollständigen
1X2-Märkten abgeleitete Markt-Wahrscheinlichkeit: pro Buchmacher die Marge
normalisieren, dann mitteln. Das ist robuster gegen einen einzelnen Ausreißer
als die frühere Regel „kleinste der jeweils besten Quoten“. Model's Choice
bleibt der 1X2-Modellfavorit. Safest Bet bezeichnet nur den höchsten modellierten
positiven Auszahlungsanteil bei Quote <=1,50, keine Garantie.

Value-Kandidaten behalten vorerst die expliziten Filter des Arbeitsbranches:
EV >0 bis 25%, Abweichung vom Markt <=15 Prozentpunkte, kein Widerspruch zu
einem Modellfavoriten über 50%, Quarter-Kelly mindestens 1%. Diese Regeln sind
Hypothesen, keine bewiesenen optimalen Grenzen. Es wird nach ungerundeten
Kelly-Werten gefiltert. Der alte WM-60%-Filter für Totals ist entfernt.

## Preis und Abrechnung

Erwartungswert und Kelly verwenden dieselbe Auszahlung pro Ergebnis wie der
Audit. Draw No Bet berücksichtigt Unentschieden als Rückzahlung. Viertellinien
werden auf benachbarte Halblinien aufgeteilt. Allgemeine Handicaps und Totals
benötigen die vollständige, ungerundete Ergebnismatrix; neue Vorhersagen
enthalten diese. Alte Caches werden nicht aus fünf Top-Ergebnissen ergänzt.
Nicht berechenbare Kandidaten stehen mit Grund in `pricing_exclusions`.

Alle angebotenen Handicap-Linien werden betrachtet, einschließlich -0,5, damit
eine bessere Quote für denselben Sieg nicht verloren geht. Bei vorhandener
Matrix werden auch sämtliche angebotenen Totals berechnet. Modellwahrscheinlichkeit
bezeichnet P(positive Auszahlung); Push und Verlust werden separat gespeichert.
Bei Push-/Viertelmärkten wird keine binäre Markt-Wahrscheinlichkeit vorgetäuscht.

## Abrufrhythmus und Gültigkeit (angepasst am 19. September)

Beim ersten Zugriff wird der Quotenbestand geladen; täglich erfolgt die
planmäßige Gesamtaktualisierung beim ersten Zugriff ab 15:00 UTC (17:00 MESZ,
16:00 MEZ). Ein vor 15 Uhr geladener Bestand verhindert diese Abfrage nicht.
Innerhalb der letzten Stunde vor Anpfiff wird pro Event einmal die richtige
Wettbewerbs-URL aufgerufen (auch Bundesliga). Danach bleibt dieser Finalstand
bis Anpfiff bestehen. Keine automatischen 15-Minuten-Gesamtabfragen.

Aufrufe stoßen die fällige Arbeit an: Der vorhandene GitHub-Logger ruft die
API planmäßig alle 15 Minuten auf, kann aber verspätet starten. Deshalb ist
„etwa 45–60 Minuten vorher“ ein Ziel, kein exakter garantierter Zeitpunkt.
Bei einem fehlgeschlagenen Finalabruf bleibt der frühere Stand ausdrücklich
als solcher markiert; Wiederholung frühestens nach 15 Minuten. Ein Finalstand
wird nicht wieder durch einen späteren Tagesabruf ersetzt. Cache und
Deduplizierung gelten pro Serverprozess; Neustarts oder mehrere Instanzen
können zusätzliche Abrufe auslösen. Persistenz ist vor einem skalierten
Betrieb noch erforderlich.

Die 30-Minuten-Prüfung bezieht sich jetzt auf das Alter des Buchmacher-Updates
BEIM ABRUF, nicht auf die Anzeigezeit eines geplanten Snapshots. Unvollständige
oder nicht komplementäre Märkte werden nicht zum Entfernen der Marge verwendet.
Initial-/Tagesstände gelten bis zum nächsten täglichen Abruftermin oder Anpfiff;
Finalstände bis Anpfiff. Verpasste Updates verlängern diese Grenzen nicht.
Die Website zeigt Abrufzeit, Berechnungszeit und „not live“. Eine Feed-Quote
belegt trotzdem nicht, dass der Anbieter einen Einsatz zu dieser Quote annimmt.

Optionales `ODDS_CACHE_TTL_SECONDS` bleibt standardmäßig 0. Häufigere
Gesamtabfragen wurden nicht eingeschaltet. Die wiederhergestellte Eventabfrage
kostet zusätzliche API-Credits; das tatsächliche Tarifbudget muss vor Deployment
geprüft werden. Es wurde in dieser lokalen Umsetzung kein externer Abruf ausgeführt.

Der Audit weist `initial`, `daily` und `final` separat aus. Für den geplanten
Vergleich unmittelbar vor dem Spiel ist der Final-Teil maßgeblich; ein fehlender
Finalstand darf nicht still durch einen Tagesstand als Finaltest ersetzt werden.

## Vorab definierte Paper-Strategien

Alle Strategien werden im selben Snapshot vor Anpfiff gespeichert, später
werden keine Regeln anhand des Ergebnisses nachträglich ausgewählt.

| Version | Regel |
|---|---|
| market_favorite_v1 | Marktfavorit mit frischer Quote, auch ohne Modell-Edge |
| value_v1 | Bester Kandidat nach den oben genannten Value-Filtern |
| value_model_ai_v1 | Derselbe Value-Tipp nur bei exakter Zustimmung von Model's Choice UND KI |
| market_model_stress_v1 | Nur 1X2: 50% Modell + 50% Markt, dann pauschal 3 Prozentpunkte abziehen; nur bei weiter positivem EV und ohne bestehendes Warnflag |

Die vierte Strategie ist eine feste vorsichtige Vergleichsregel, kein gelerntes
Unsicherheitsintervall. Ein neuer faktenbasierter Wahrscheinlichkeitsaufschlag
ist noch nicht trainiert. Nachrichten verändern daher keine Modellzahl.
Neue Regeln brauchen neue Versionsnamen. Die alten Baseline-Logs werden nicht
nachträglich mit diesen Strategien angereichert.

Der Audit zeigt pro Wettbewerb und Strategie: auswertbare Spiele, Wetten,
Enthaltungen, ungültige/nicht abgerechnete Wetten, Profit, ROI und maximalen
Rückgang des kumulierten Profits am Tagesende. Fester Einsatz: eine Einheit.
Keine Kelly-Kontorendite, keine Intraday-Drawdown-Messung, keine Aussage über
statistische Signifikanz aus einer kleinen Stichprobe.

## KI-Recherche

Der Prompt nennt Vereinsspiel, Wettbewerb und Anpfiff. Die KI erhält alle
berechenbaren Kandidaten mit Markt/Ergebnis/Quote in neutral sortierter Reihenfolge,
aber keine Modellwahrscheinlichkeiten, Edge-Werte oder vorherige Empfehlung.
Frühere Antworten werden nur anschließend auf Änderungen verglichen.

Fakten erfassen Quelle, behaupteten Veröffentlichungszeitpunkt, Status, Team
und Wirkungsmechanismus. Grounding-URLs werden gespeichert. Ein Quellenlink
oder ein von Gemini genannter Zeitstempel bestätigt noch nicht den Inhalt:
`verified` bleibt false. Zukünftige oder fehlende Veröffentlichungszeiten
werden markiert. Die KI bleibt ein zu testendes Forschungssignal; ihre Texte
werden nicht als unabhängiger Profitnachweis gezählt.

## Noch vor einer produktiven Umstellung

- Marktwert-/Modellvarianten unter identischen Datenregeln vergleichen;
  Claudes Produktionsmodell nicht durch einen schlechter geprüften Kandidaten ersetzen.
- Abrufbudget bestimmen und neue, vor Anpfiff gespeicherte Quoten sammeln.
- Fakteninhalt und Verfügbarkeit tatsächlich prüfen, historische Merkmale
  bilden und erst dann einen zusätzlichen Nachrichteneffekt außerhalb des Trainingszeitraums testen.
- Genügend neue Beobachtungen für Unsicherheitsintervalle und regelgebundene
  Auswahl sammeln; ein lernender Selektor wäre jetzt noch nicht belastbar.
