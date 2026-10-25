# Historischer Test: Meinungswechsel und Modellprüfung

Stand: 25.10.2026. Auswertung gespeicherter Vorab-Tipps, keine neuen KI-Aufrufe.
130 Spiel-Einträge im Produktionslog vom 28.09.–25.10.; 9 ohne eindeutig
zugeordnetes Endergebnis, 12 weitere ohne endgültigen KI-Tipp. 109 KI-Tipps
konnten abgerechnet werden. Davon waren 88 ausdrücklich erneut geprüft.
Einsatz jeweils 1 Einheit, Auszahlung zu den gespeicherten Quoten.

## Hypothese: Meinungswechsel ist ein Warnsignal

| Letzter Check | Tipps | Gewonnen / verloren / erstattet | Trefferquote* | Gewinn | ROI |
|---|---:|---|---:|---:|---:|
| Beibehalten | 62 | 42 / 20 / 0 | 67,7 % | +25,13 | +40,5 % |
| Geändert | 26 | 12 / 13 / 1 | 48,0 % | −3,23 | −12,4 % |

*Erstattungen zählen im Einsatz/ROI mit, aber nicht im Nenner der Trefferquote.
95%-Wilson-Intervalle für die Trefferquote: geändert 30,0–66,5 %,
beibehalten 55,4–78,0 %. Das sind beschreibende Intervalle unter einer
Unabhängigkeitsannahme; Spiele desselben Spieltags können zusammenhängen.
Kein kausaler Nachweis, dass der Wechsel den schlechteren Tipp verursacht.
Schwierigere Spiele können sowohl mehr Wechsel als auch mehr Fehler erzeugen.

Das Muster ist nicht allein ein Liga-Mix:

| Wettbewerb | Geändert: Anzahl / ROI | Beibehalten: Anzahl / ROI |
|---|---|---|
| Nations League | 17 / −7,8 % | 31 / +42,5 % |
| Champions League | 6 / −10,3 % | 24 / +55,5 % |
| Bundesliga | 3 / −42,7 % | 7 / −19,6 % |

Die kleinen Untergruppen rechtfertigen keine neuen markt- oder ligaspezifischen Regeln.

## Auf denselben Spielen: ersten oder geänderten Tipp spielen?

Für 9 Änderungen sind beide konkreten Tipps samt Quote erhalten. Bei 17
weiteren auswertbaren Änderungen fehlt der ursprüngliche Tipp.

| Vorgehen bei diesen 9 Spielen | Treffer | Gewinn | ROI |
|---|---:|---:|---:|
| Ursprünglichen Tipp behalten | 3/9 | −3,66 | −40,7 % |
| Geänderten Tipp spielen | 4/9 | −1,90 | −21,1 % |
| Wegen Wechsel auslassen | keine Einsätze | 0 | nicht definiert |

Der geänderte Tipp war in diesem kleinen Paarvergleich besser als der erste,
aber Auslassen hätte den Verlust verhindert. Daher sind „bei Wechsel nicht
wetten“ und „der erste Tipp war besser“ zwei unterschiedliche Hypothesen.
Original- und Endquote stammen aus unterschiedlichen Auswahlzeitpunkten; es
ist kein Vergleich zweier gleichzeitig verfügbarer Angebote. Ein eigener
Zeitstempel des ersten Tipps fehlt in den alten Logs.

Nur 4 Paare änderten die Wette innerhalb derselben Richtung (1 Treffer),
5 änderten die Richtung (3 Treffer). Zu wenig, um die bestehende Sperre nach
Art des Wechsels aufzuweichen.

## Beide Schranken getrennt auf derselben Basis

Für diesen Vergleich: ausschließlich erneut geprüfte KI-Tipps mit Quote
mindestens 1,30, nicht ausdrücklich veraltet, Modell- und Marktwert vorhanden.
83 Spiele erfüllen dies. Jeder Ansatz setzt höchstens eine Einheit auf den
originalen endgültigen KI-Tipp; eine abgelehnte Wette wird ausgelassen.
Kein Fallback auf eine andere Wette. Das isoliert die Schranken und ist
bewusst keine Rekonstruktion aller Versionen des veröffentlichten Wett-Tipps.

| Vorgehen | Wetten | Treffer | Gewinn | ROI |
|---|---:|---:|---:|---:|
| Alle KI-Tipps dieser Basis | 83 | 51/83 | +21,17 | +25,5 % |
| Nur wenn kein Wechsel | 60 | 40/60 | +24,65 | +41,1 % |
| Nur wenn Modell ≥ Markt | 42 | 28/42 | +19,96 | +47,5 % |
| Beide Schranken | 33 | 24/33 | +21,54 | +65,3 % |

Mehr ROI bedeutet hier nicht automatisch mehr Gesamtgewinn: Die Modellprüfung
allein erhöhte die Rendite je eingesetzter Einheit, reduzierte aber den
Gesamtgewinn. Wettbewerbe, Quoten und Zeiträume sind nicht zufällig verteilt.
Diese bereits gesehenen Daten sind eine Diagnose, kein unabhängiger Test
zukünftiger Profitabilität. Keine Schwellenwerte wurden anhand der Ergebnisse
optimiert. Zeit- und Ligagruppen sind in der JSON-Auswertung enthalten.

Seit 11.10. trafen Modell-bestätigte KI-Tipps 11/20 (55,0 %), bei Widerspruch
12/21 (57,1 %). Der Gewinn der bestätigten Tipps von +9,19 Einheiten hängt stark
an Viking–Bayern: ein gewonnenes Remis zu 8,50 brachte allein +7,50 Einheiten.
Ohne diesen einzelnen Treffer bleiben +1,69 aus 19 Tipps (+8,9 % ROI), gegenüber
+7,7 % ROI bei den 21 Tipps mit Modellwiderspruch. Dies ist eine ausdrücklich
nachträgliche Ausreißerprüfung, kein zulässiger neuer Selektor.

## Hypothese: mehr Modellinformationen verschlechtern den KI-Prompt

Der obige Modellfilter-Test beantwortet diese Frage NICHT. Er ordnet die
bereits erzeugten KI-Tipps nach dem Modellwert; er verändert nicht die
Informationen, die der KI bei der Auswahl vorlagen.

Es existiert ein älteres Experiment (`scripts/llm_bettor_test.py`, gespeicherte
Ergebnisse in `data/model_reports/llm_bettor/results.json`): 455 anonymisierte
historische Spiele, nur 1X2-Zahlen, keine damalige Nachrichtenrecherche.
Beide Prompt-Varianten erhielten Modellinformationen. Der neutrale Analyst
platzierte 379 Wetten mit −8,0 % ROI (gespeichertes 95%-Intervall −27,8 bis
+14,7 %); die stark marktpreisorientierte Persona 224 mit +27,7 %
(−4,8 bis +66,7 %). Ein identischer Prompt ohne Modellinformationen fehlt.
Diese gespeicherten Befunde wurden hier nicht durch neue Modellaufrufe wiederholt.

Auch das ist kein sauberer Mehr-/Weniger-Informationen-Test und kein Nachweis,
dass der aktuelle Rechercheprompt besser oder schlechter wird. Die zwei
isolierten Bundesliga-Vergleiche vom 25.10. änderten gleichzeitig Kandidaten
und Prompt, ebenfalls keine isolierte Prüfung.

Ein belastbarer Vergleich braucht identische Spiele, identische zeitgerechte
Recherche und Quoten, denselben Modellstand und Prompt — einmal mit, einmal
ohne die zusätzlichen Modellinformationen. Historische neue Webrecherche wäre
verfälscht, weil Ergebnisse und spätere Berichte inzwischen bekannt sind.
Für die alten Spiele ist die erforderliche Datengrundlage nicht vollständig
archiviert. Ein künftiger Paralleltest kostet zusätzliche KI-Aufrufe; die
historische Auswertung hier kostet keine.

## Konsequenz

Die Wechsel-Sperre vorerst beibehalten: Die vorhandenen Ergebnisse sprechen
für Vorsicht. Nicht behaupten, Wechsel bewiesen Unsicherheit oder seien
ursächlich schlechter. Die Modellprüfung hat noch keinen stabilen Zusatznutzen
über Wettbewerbe und Zeiträume gezeigt. Mehr Modellinformationen sind ebenfalls
nicht als Verbesserung belegt. Der Test ändert deshalb keine Auswahlregel und
empfiehlt keinen Merge als erwiesene Gewinnverbesserung.

Reproduktion mit gespeicherten Eingabedateien:

```sh
.venv/bin/python scripts/check_ai_hypotheses.py --log /path/to/bet_log.jsonl --results /path/to/results.json --output /tmp/ai-hypotheses.json
```
