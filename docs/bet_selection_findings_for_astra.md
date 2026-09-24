# Bericht an Astra: Warum kein Auswahlkriterium funktioniert

Nachtrag zu `bet_selection_v1.md` und deinem Auswahlvergleich. Dein Vorschlag
wurde vollständig umgesetzt, einschließlich der beiden Punkte, auf die du
ausdrücklich hingewiesen hattest. Das Ergebnis ist negativ, aber der Weg
dorthin hat etwas gezeigt, das die bisherige Arbeit in ein anderes Licht
rückt.

## 1. Dein Vorschlag, umgesetzt

**„Gleicher Tipp" ≠ „unterstützt diesen Tipp"** ist eingebaut. Ein Modell,
das Dänemark favorisiert, stützt auch Dänemark +1,5 — die Merkmale ordnen
Handicap- und Torwetten über die Richtung zu, nicht über Label-Gleichheit.

**Model's Choice, Safest und Value bekommen ein Signal, nicht drei.**

**Einzelne Modelle** hatte ich im ersten Durchlauf übersprungen und mit „nie
archiviert" abgetan. Das war zu bequem: Die gespeicherten Vorhersagen
enthalten nur den Ensemble-Wert, aber das Ensemble *ist* RF + XGBoost +
CatBoost — dieselben chronologischen Fits lassen sich wiederholen
(`scripts/reconstruct_predictor_spread.py`, alle 1.224 Spiele). Die
Einzelmodelle sind bei **26%** der Spiele über den Favoriten uneinig, das
Merkmal hat also Substanz.

**KI-Recherche** bleibt ungeprüft — dazu unten Abschnitt 5.

Protokoll wie von dir gefordert: Entwicklung auf 2021-22 und 2022-23,
einmalige Auswertung auf 2023-24 und 2025-26, keine nachträgliche
Saisonauswahl.

## 2. Ergebnis: kein Merkmal trägt

Auch mit den Einzelmodell-Merkmalen schlägt kein Modell die bloße
Mittelwert-Vorhersage. Die Kreuzvalidierung wählt durchgehend die stärkste
Regularisierung und schrumpft alle Gewichte gegen null.

Ein eigener Fehler, der in den Bericht gehört: Im ersten Durchlauf hatte ich
Regularisierung und Schwelle auf maximale Entwicklungs-ROI optimiert. Das
ergab +41% bis +60% auf den Entwicklungsdaten und einen Zusammenbruch im
Holdout. Genau so entsteht ein Scheinvorteil.

## 3. Der eigentliche Befund: EV ist ein Abweichungsmaß

`EV = Modellwahrscheinlichkeit × Quote − 1` ist vollständig durch den Abstand
zur Marktquote bestimmt. „Hoher EV" heißt wörtlich: **starke Abweichung vom
Markt**. Das ist kein Wertmaß, sondern ein Unstimmigkeitsmaß.

Und diese Abweichung ist anti-prädiktiv. Nach EV-Fünfteln, mittlerer
Closing-Line-Value:

| EV-Bereich | CLV |
|---|---:|
| niedrigstes Fünftel | −0,61% |
| | −0,81% |
| | −0,72% |
| | −0,90% |
| **höchstes Fünftel** | **−1,62%** |

Je überzeugter das Modell, desto stärker bewegt sich der Markt dagegen. Wo
das Modell am meisten widerspricht, irrt es am meisten.

## 4. Jede Regel ist schlechter als Zufall

Die naheliegende Folgerung wäre, ein anderes Kriterium zu nehmen. Das ist
geprüft — Auswahl unter denselben drei 1X2-Kandidaten je Spiel, 1.224 Spiele,
beste Quote am Markt:

| Auswahlregel | CLV | besser als Schlussquote |
|---|---:|---:|
| **Zufall** | **−0,79%** | 44,4% |
| niedrigster EV (umgekehrt) | −0,94% | 39,4% |
| höchster EV (heutige Regel) | −1,16% | 41,8% |
| Marktfavorit | −1,24% | 36,8% |
| höchste Modellwahrscheinlichkeit | −1,41% | 36,3% |

**Zufälliges Auswählen schlägt jede systematische Regel**, auch die
umgekehrte. Damit ist die Frage „anderes Auswahlkriterium?" beantwortet: In
diesen Zahlen steckt keine Rangfolge-Information, gleich wie man sie dreht.
Das Problem liegt nicht in der Formel, sondern darin, dass es nichts zu
sortieren gibt.

Auch der auf CLV statt auf Gewinn trainierte Selektor — das ruhigere Ziel,
das du implizit gefordert hattest — erreicht im Holdout −0,55% gegenüber
−0,50% bei Zufallswahl.

## 5. Zwei Korrekturen an deinem Vergleich

**Die Preisquelle.** Dein Vergleich rechnet durchweg mit Bet365. Unser
Live-System nimmt aber das Maximum über alle Buchmacher (`_best_price` in
`api/app.py`). Dieselben 360 Tipps, neu bepreist:

| Preisquelle | ROI |
|---|---:|
| Bet365 | −4,6% |
| Marktdurchschnitt | −4,6% |
| **beste verfügbare Quote** | **−0,9%** (95%: −15,8% bis +14,1%) |

Der Preisvergleich ist 4,1% wert. Das erzeugt keinen Vorteil, verschiebt die
reale Lage aber von „klar verlierend" auf „ununterscheidbar von null". Dein
Bericht stellt unsere tatsächliche Position um rund 3,7 Punkte zu schlecht
dar.

**Die 2. Bundesliga** war als weicherer Markt plausibel — wir haben dort 4.590
Trainingsspiele. Geprüft mit heruntergeladenen D2-Quoten, gleiches Rezept,
919 Wetten: ROI −0,15% (95%: −10,1% bis +9,7%), aber **CLV −1,22%**
(95%: −1,64% bis −0,80%), also signifikant negativ und schlechter als in der
1. Liga. Die Saison-ROI schwankt von +11,7% bis −12,6% — Varianz, nicht
Können. Der Zweitligamarkt ist für uns nicht weicher.

## 6. Was das für die KI-Recherche heißt

Dein Punkt, erst Analysen vor Anpfiff zu speichern, bleibt richtig. Ich würde
ihn schärfen: **So wie die KI heute antwortet, wäre auch ein vollständiger
historischer Bestand nicht auswertbar.**

Die Ausgabe ist Prosa — `claim`, `mechanism`, `bet_reasoning` als Freitext,
dazu ein Tipp. Ein Tipp ist genau die Art Einschätzung, von der wir in
Abschnitt 4 wissen, dass sie als Rangfolge nichts trägt. Prosa lässt sich
nicht in ein Merkmal überführen, ohne sie erneut durch ein Sprachmodell zu
interpretieren.

Mein Vorschlag ist deshalb, die Rolle der KI umzudrehen: **Sie soll nicht
bewerten, sondern messen.** Statt „Union fehlen wichtige Spieler, das spricht
für Bayern" soll sie Größen liefern, die in die Rechnung eingehen:

| Feld | Warum es rechenbar ist |
|---|---|
| `absent_players` mit Namen | lässt sich gegen den Kader auflösen |
| `absent_squad_value_share` | wir haben Marktwerte — „30% des Kaderwerts fehlt" ist eine Zahl, die direkt in das bestehende Marktwert-Merkmal einfließen kann |
| `lineup_confirmed` | trennt bestätigte von vermuteter Aufstellung |
| `rest_days` je Team | aus dem Spielplan prüfbar, nicht Meinung |
| `is_dead_rubber` | aus Tabellenstand ableitbar |

Der entscheidende Unterschied: Diese Felder verändern **einen Eingabewert des
Modells**, nicht das Ergebnis. Wenn 30% des Kaderwerts fehlt, ist der
Marktwert dieses Teams für dieses Spiel eben ein anderer — das ist keine
zusätzliche Meinung, sondern eine Korrektur einer Zahl, die wir ohnehin
benutzen. Und wie stark sie wirkt, muss aus Daten gelernt werden, nicht
festgelegt.

Ob das trägt, ist offen. Es ist aber der einzige mir bekannte Weg, bei dem
die KI Information beisteuert, die der Markt nicht ohnehin schon eingepreist
hat — und der einzige, der nach Abschnitt 4 überhaupt noch plausibel ist,
weil er neue Information hinzufügt statt vorhandene neu zu sortieren.

Voraussetzung bleibt deine: ab jetzt vor Anpfiff speichern, keine heutigen
Erklärungen zu vergangenen Spielen.

## 7. Empfehlung

Die Auswahlfrage ist aus meiner Sicht abgeschlossen. Drei unabhängige Zugänge
— feste Regeln, ein lernender Selektor, der Schlussquoten-Test — kommen zum
selben Ergebnis, und Zufall schlägt jede Regel. Weitere Umsortierungen
derselben Zahlen würden nur Rechenzeit kosten.

Sinnvoll bleiben zwei Dinge: den Preisvergleich ernst nehmen, weil er 4,1%
wert ist, und das strukturierte KI-Logging aufsetzen, damit in einigen
Monaten überhaupt etwas Neues prüfbar wird.

Die Warnhinweise auf der Website sind nach diesen Zahlen nicht
übervorsichtig, sondern zutreffend.

## Reproduzieren

```sh
python3 scripts/clv_target_selector.py
python3 scripts/evaluate_bundesliga2.py
python3 scripts/closing_line_value.py
python3 scripts/reconstruct_predictor_spread.py
```

## Grenzen

- Nur Bundesliga und 2. Bundesliga, retrospektiv, keine protokollierten Live-Tipps
- CLV nur für 1X2 — football-data führt keine Schluss-Handicaps oder -Totals
- Als genommener Preis dient die Eröffnungsquote; unser reales Timing war anders
- Einzelmodelle rekonstruiert unter `verified_only`, nicht der heutigen Produktionseinstellung
