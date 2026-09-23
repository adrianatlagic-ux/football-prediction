# Schlussquoten-Test und nachgeholter Einzelmodell-Test

Zwei Nachträge zum lernenden Auswahlmechanismus. Der erste prüft mit einem
schärferen Maß als ROI, ob überhaupt ein Vorteil existiert. Der zweite holt
ein Merkmal nach, das im ersten Durchlauf fehlte.

## 1. Closing Line Value

ROI ist ein verrauschtes Maß — die Intervalle im Auswahlvergleich reichen von
−82% bis +18% und entscheiden nichts. Der Schlussquoten-Test fragt schärfer:
Die Schlussquote ist die beste Schätzung des Marktes, weil bis dahin alles
Bekannte eingepreist ist. Wer wiederholt bessere Preise erwischt als den
späteren Schluss, findet echte Information.

360 Wetten, Bet365, vier Bundesliga-Saisons:

| | Wert |
|---|---|
| mittlerer CLV | **+0,25%** |
| 95%-Intervall | −0,53% bis +1,04% |
| Anteil besser als Schlussquote | **40,3%** (ohne Vorteil ~50%) |

| Saison | Wetten | CLV | > Schlussquote |
|---|---:|---:|---:|
| 2021-22 | 97 | +0,18% | 38,1% |
| 2022-23 | 81 | +0,13% | 39,5% |
| 2023-24 | 73 | +0,28% | 42,5% |
| 2025-26 | 109 | +0,38% | 41,3% |

**Kein nachweisbarer Vorteil.** Das Intervall schließt null ein. Der Anteil
unter 50% bei leicht positivem Mittelwert bedeutet: meist etwas schlechtere
Preise als der Schluss, gelegentlich deutlich bessere — netto etwa null.

Eine Zahl aus dem Rohlauf ist **kein Befund**: „Modell über Schlussmarkt in
98,3% der Fälle". Die Auswahlregel verlangt positiven Erwartungswert, also
Modell über Markt. Das ist bauartbedingt, nicht gemessen.

## 2. Einzelmodelle — im ersten Durchlauf übersprungen

Der Vorschlag nennt als Merkmal: „Beruht der Vorteil auf ähnlichen
Einschätzungen oder einem einzelnen Ausreißer?" Das war im ersten Test nicht
enthalten, und die Begründung „nie archiviert" war zu bequem: Die gespeicherten
Vorhersagen enthalten nur den Ensemble-Wert, aber das Ensemble ist
RF + XGBoost + CatBoost — dieselben chronologischen Fits lassen sich
wiederholen. `scripts/reconstruct_predictor_spread.py` tut das für alle 1.224
Spiele.

Die Einzelmodelle sind bei **74%** der Spiele über den Favoriten einig, weichen
also oft genug ab, um ein brauchbares Merkmal zu sein. Ergänzt wurden
Standardabweichung und Spannweite der Einzelmodelle für das jeweils gesetzte
Ergebnis sowie ein Einigkeits-Flag — für Handicap- und Torwetten über die
Richtung zugeordnet, entsprechend dem Punkt „unterstützt diesen Tipp".

| Scope | Merkmale | MSE Mittelwert | bestes MSE | Urteil |
|---|---:|---:|---:|---|
| 1x2 vor Anpfiff | 19 | 2,8423 | 2,8432 | helfen nicht |
| alle Märkte vor Anpfiff | 19 | 1,7429 | 1,7436 | helfen nicht |
| 1x2 Schlussquote | 19 | 2,9411 | 2,9420 | helfen nicht |
| alle Märkte Schlussquote | 19 | 1,7845 | 1,7853 | helfen nicht |

Auch mit den Einzelmodellen schlägt kein Modell die bloße Mittelwert-Vorhersage.
Bei ehrlicher Regularisierung sagt der Selektor für jeden Kandidaten den
(negativen) Mittelwert voraus — und setzt damit bei der Schwelle 0 **gar nicht
mehr**. Das ist die konsequente Antwort des Verfahrens: nicht setzen.

## Gesamtbild

Drei unabhängige Zugänge, dasselbe Ergebnis: feste Regeln (Astras Vergleich),
ein lernender Selektor, und der Schlussquoten-Test. Es gibt keinen messbaren
Vorteil gegenüber dem Markt. Die Verluste sind die Buchmachermarge, nicht Pech.

Offen bleibt allein das KI-Signal, für das historische Vorab-Analysen fehlen.
Es kann erst geprüft werden, wenn ab jetzt Analysen vor Anpfiff gespeichert
werden.

## Reproduzieren

```sh
python3 scripts/closing_line_value.py
python3 scripts/reconstruct_predictor_spread.py
python3 scripts/learned_bet_selector_with_spread.py
```

## Grenzen

- Nur Bundesliga, nur Bet365, retrospektiv
- CLV nur für 1X2 — football-data führt keine Schluss-Handicaps oder -Totals
- Als genommener Preis dient die Eröffnungsquote; unser reales Timing war anders
- Die rekonstruierten Einzelmodelle nutzen dieselbe Policy wie die gespeicherten
  Vorhersagen (`verified_only`), nicht die heutige Produktionseinstellung
