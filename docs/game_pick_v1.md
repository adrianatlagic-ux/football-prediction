# Aktive Tipp-Auswahl: robust_game_pick_v1

Stand 19. September 2026, lokal auf `codex/bet-selection`. Keine Veröffentlichung,
kein neues Modelltraining, keine externen API-Aufrufe. Das ist eine experimentelle
Entscheidungsregel, kein belegter Renditevorsprung und keine behauptete neue
wissenschaftliche Erfindung.

## Was den angezeigten Tipp jetzt tatsächlich verändert

`combined.consensus_pick`, von der Website als Game Pick angezeigt, kommt jetzt
aus `select_game_pick()`. Er kann der Marktfavorit, eine andere 1X2-Wette, ein
Total/Handicap oder leer sein. `/best-bets`, `/value-bets` und `/all-bets` benutzen
dieselbe Funktion. Die Zustimmungssymbole vergleichen Modell/KI mit dem
tatsächlich ausgewählten Tipp. Der Marktfavorit bleibt als eigene Baseline im
Vergleichsprotokoll erhalten. Es gibt keinen automatischen Favoriten-Fallback.

Die vier bisherigen Paper-Strategien bleiben unverändert zum Vergleich erhalten;
die aktive Auswahl wird als fünfte Strategie mit eigener Version gespeichert.
Jeder Kandidat erhält eine dokumentierte Bewertung oder einen Ausschlussgrund.
Die alten Logs werden nicht rückwirkend ergänzt.

## Vorab festgelegte Regeln

1. Nur gültige Pre-Match-Snapshots und bei Abruf gültige Quoten.
2. Mindestens drei andere Buchmacher mit vollständigen, passenden Märkten.
   Der Anbieter der angebotenen Quote wird aus dem Referenzmarkt ausgeschlossen.
   Drei Anbieter bedeuten nicht drei statistisch unabhängige Informationsquellen.
3. Die Referenzpreise werden je Buchmacher von der Marge bereinigt. Minimum,
   Mittelwert und Maximum dieser Preiswahrscheinlichkeiten gehen in die Prüfung ein.
4. Die modellierte Auszahlungsverteilung wird mit diesen Marktansichten gemischt:
   jeweils 25%, 50% und 75% Modellgewicht. Bei Draw No Bet und Viertellinien wird
   der Preis über effektive Gewinn-/Verlustanteile übersetzt; die bedingte
   Marktzahl wird nicht als P(Gewinn) ausgegeben. Die Form innerhalb positiver/
   negativer Auszahlungen und die Push-Masse bleiben modellabhängig.
5. In jeder Mischung werden drei Prozentpunkte Wahrscheinlichkeitsmasse von den
   höchsten Auszahlungen in einen vollen Verlust verschoben. Das ist ein fester
   Stresstest, KEIN geschätztes Konfidenzintervall und keine 97%-Garantie.
6. Mindestens 1% erwarteter Nettoertrag pro Einheit Einsatz muss in jeder
   geprüften Variante übrig bleiben. Eine Modell-/Marktabweichung von mehr als
   20 Prozentpunkten in effektiver Preiswahrscheinlichkeit wird ausgeschlossen.
   Der alte bloße Widerspruch zum Modellfavoriten ist hier kein Ausschlussgrund.
7. Paper-Einsatz: niedrigster Quarter-Kelly aller Varianten, höchstens 1% des
   hypothetischen Budgets. Auswahl nach dem kleinsten erwarteten logarithmischen
   Budgetzuwachs über die Varianten, berechnet bei genau diesem Einsatz.
   Damit entscheidet nicht einfach der größte rohe Edge oder die niedrigste Quote.

Die Website zeigt den erwarteten Ertrag nach Stress, die Zahl der Referenzanbieter
und die Mindestquote, bei der die 1%-Ertragsbedingung weiterhin erfüllt wäre.
Die Mindestquote gilt nur bei unveränderten Modell-/Referenzannahmen dieses
Snapshots. Originaler Modell-EV und originaler Modell-Kelly bleiben in den
Vergleichszeilen entsprechend gekennzeichnet; sie sind nicht die Paper-Sizing-
Regel des Game Picks. Die Auswertung misst weiterhin Einheitsrendite, keine
tatsächliche Kontorendite der dynamischen Einsätze.

## KI und Unsicherheit

Die KI verändert keine Zahlen und gibt keinen Bonus für Zustimmung. Ihre
Quellen-/Faktenausgabe wird weiter protokolliert. Ohne messbaren Zusatznutzen
wäre eine KI-Gewichtung frei erfunden. Der neue Selektor funktioniert auf den
jeweils gelieferten Modellprognosen; er macht dadurch weder Claudes noch das
lokale V3-Modell automatisch besser.

Die Auswahl berücksichtigt unterschiedliche Marktpreise und explizite
Fehlerannahmen. Nicht erfasst sind bislang eine empirisch geschätzte
Modellfehlerverteilung, vollständige Push-/Scoreline-Unsicherheit, tatsächliche
Ausführbarkeit, Limits, Kosten, Steuern und ein gesamtes Portfolio korrelierter
Wetten. Die 1%-Grenze ist pro Tipp, kein Tages- oder Gesamtrisikolimit.

Die festen Schwellen wurden nicht auf zukünftige Ergebnisse optimiert. Sie
werden jetzt separat protokolliert und müssen anhand neuer Final-Snapshots
gegen die Baselines bestehen. Wenige oder keine Tipps sind ein mögliches
Ergebnis, insbesondere bei geringer Anbieterabdeckung. Die historischen
Modell-Trefferquoten aus V3 belegen keine Verbesserung dieser neuen Auswahl.

## Nachweis der Funktionsänderung

`tests/test_game_pick.py` verwendet ausdrücklich synthetische, nicht reale
Wettangebote. Es prüft u.a.:

- gleicher Modellstand, schlechtere Quote => Tipp fällt weg;
- Alternative besteht die Stressprüfungen besser => Wechsel weg vom Favoriten;
- drei Referenzanbieter fehlen => keine Wette;
- KI stimmt einer negativen Wette zu => weiterhin keine Wette;
- Push-/Viertellinien behalten korrekte Auszahlung und Wahrscheinlichkeitsmasse;
- mehr Referenzmarkt-Streuung verbessert die Auswahlbewertung nicht;
- alle Auswahlgründe sind JSON-protokollierbar, gleiches Input erzeugt gleiche Auswahl.
