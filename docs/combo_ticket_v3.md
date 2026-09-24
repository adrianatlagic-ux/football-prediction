# Kombi-Tickets v3 — lokaler Entwicklungsstand

Claudes separate Ticket-Ansicht bleibt erhalten, mit Tagesgruppen und einer
Vergleichskombi beim selben Anbieter. Die Auswahl wurde korrigiert:

- Quoten, Abrechnung und Marktvergleich werden für jeden Anbieter separat
  berechnet. Dessen eigene Quote wird aus dem Referenzmarkt ausgeschlossen.
  Eine Kombi enthält genau einen Anbieter und einen lokalen Spieltag
  (Europe/Berlin). Die multiplizierten Einzelquoten sind keine bestätigte
  Kombiquote des Anbieters.
- Jede Einzelwette muss `game_pick.assess` bestehen: insbesondere echte
  Referenzdaten von mindestens drei anderen Anbietern und positiver Vorteil
  unter den festgelegten Stressannahmen. Zusätzlich mindestens 55 Prozent
  Modellwahrscheinlichkeit. Die Regeln sind experimentell.
- Pro Spiel und Anbieter wird die höchste Stresswahrscheinlichkeit gewählt.
  Daraus werden die sieben stärksten Spiele je Anbieter/Tag berücksichtigt
  und Kombinationen von zwei bis vier Spielen geprüft. Das ist eine begrenzte
  Suche, kein Beweis für die global optimale Kombi. Duplikate und mehrfach
  beteiligte Teams werden abgewiesen.
- Binäre Abrechnung: 1X2 und Halbtorlinien werden unterstützt. DNB, Ganzzahl-
  und Viertellinien bleiben ausgeschlossen, bis die komplette Verteilung
  möglicher Rückzahlungen und Teilgewinne für Kombis implementiert ist.
- Gewinnwahrscheinlichkeiten werden nur unter ausdrücklich genannter
  Unabhängigkeitsannahme multipliziert. Unterschiedliche Spiele können
  gemeinsame Modellfehler haben; diese Abhängigkeit ist noch nicht geschätzt.
- Die Stresswahrscheinlichkeit je Auswahl stammt aus derselben Modell/Markt-
  Szenariorechnung wie beim Game Pick und wird maximal auf den Modellwert
  begrenzt. Einsatz und Rangfolge verwenden diese Stresswerte: Viertel-Kelly,
  maximal ein Prozent rechnerischer Einsatz pro Ticket, Rang nach erwarteter
  logarithmischer Vermögensänderung. Keine gemeinsame Portfoliooptimierung.
- Die Differenz zwischen Modell und Markt heißt `model_market_gap`.
  Sie ist keine gemessene Buchmachermarge.

## Noch offen

Separate, vor Anpfiff unveränderlich gespeicherte Ticket-Logs mit kompletter
Zusammensetzung, Anbieter, Quote, Zeit und Regelversion; anschließend tatsächliche
Abrechnung und Vergleich mit denselben Tipps als Einzelwetten. Der bestehende
Einzelwetten-Audit allein weist keine historische Ticket-Rendite nach.

Auch tatsächliche Kombiverfügbarkeit, Einsatzlimits, Quotenänderungen,
Abhängigkeiten und Gesamtbudget über überlappende Tickets sind nicht modelliert.
Diese Umsetzung liefert daher noch keinen Nachweis eines profitablen Systems.

## Prüfung

Regressionstests prüfen insbesondere gemeinsame Anbieterquoten einschließlich
API-Neuberechnung, Ausschluss der jeweiligen Anbieterquote aus der Referenz,
Duplikate, Tagesgrenzen, fehlende Referenzdaten, Teilabrechnungs-Ausschlüsse und
Stress-Einsatzberechnung. Reale Modell-/Wettperformance wird damit nicht gemessen.
