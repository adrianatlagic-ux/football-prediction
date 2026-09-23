# Lernender Auswahlmechanismus — Ergebnis: kein Vorteil

Geprüft wurde der Vorschlag, die Signale zur **Auswahl zwischen den zulässigen
Wetten eines Spiels** einzusetzen, statt Kandidaten nur umzusortieren.

Zwei Punkte des Vorschlags sind ausdrücklich umgesetzt:

- **„Gleicher Tipp" ist nicht „unterstützt diesen Tipp".** Die Merkmale
  `backs_model_fav` und `backs_market_fav` greifen auch, wenn das Modell
  Dänemark favorisiert und der Kandidat Dänemark +1,5 ist. Exakte
  Label-Übereinstimmung hätte diesen Zusammenhang nicht erkannt.
- **Model's Choice, Safest und Value bekommen keine drei Stimmen.** Sie
  entstehen aus denselben Modellzahlen und liefern ein Signal, nicht drei.

## Protokoll, vor dem ersten Ergebnis festgelegt

Entwicklung auf 2021-22 und 2022-23, einmalige Auswertung auf 2023-24 und
2025-26. Keine nachträgliche Saisonauswahl. Ziel ist der realisierte Gewinn
pro Kandidat; gewählt wird je Spiel der höchstbewertete Kandidat, gesetzt nur
bei positiver Vorhersage.

## Ergebnis

Regularisierung über kreuzvalidierten Vorhersagefehler gewählt, Schwelle 0 —
kein Nachjustieren auf ROI.

| Scope | Wetten | ROI Selektor | ROI Baseline | 95%-Intervall |
|---|---:|---:|---:|---|
| 1x2 vor Anpfiff | 119 | −37,0% | −20,4% | −82% bis +18% |
| alle Märkte vor Anpfiff | 123 | −34,1% | −6,4% | −79% bis +21% |
| 1x2 Schlussquote | 135 | −25,7% | −0,1% | −70% bis +27% |
| alle Märkte Schlussquote | 169 | −30,2% | −2,6% | −65% bis +13% |

Vier von vier negativ und durchweg schlechter als die bestehende Auswahl.

## Der entscheidende Test

Kein merkmalsbasiertes Modell schlägt die bloße Mittelwert-Vorhersage:

| Scope | MSE Mittelwert | bestes MSE | gewähltes alpha |
|---|---:|---:|---:|
| 1x2 vor Anpfiff | 2,8423 | 2,8431 | 100000 |
| alle Märkte vor Anpfiff | 1,7429 | 1,7435 | 100000 |
| 1x2 Schlussquote | 2,9411 | 2,9419 | 100000 |
| alle Märkte Schlussquote | 1,7845 | 1,7852 | 100000 |

Die Kreuzvalidierung wählt durchgehend die stärkste angebotene Regularisierung,
schrumpft also alle Gewichte gegen null. Aus Modellwahrscheinlichkeit, Quote,
Markt-Abweichung und Richtungsunterstützung lässt sich nicht vorhersagen, welche
Wette sich auszahlt. Das ist ein Null-Ergebnis, kein Hinweis auf zu schwache
Umsetzung.

## Eigener Fehler im ersten Durchlauf

Zuerst wurden Regularisierung und Schwelle so gewählt, dass die
Entwicklungs-ROI maximal wird. Das ergab +41% bis +60% auf den
Entwicklungsdaten und einen Zusammenbruch im Holdout (+8,6% bei 35 Wetten in
einem Scope, −14% bis −38% in den drei anderen). So entsteht ein
Scheinvorteil. Die Zahlen oben stammen aus der korrigierten Auswahl.

## Was hiermit NICHT geprüft ist

- **KI-Recherche.** Es gibt keine historischen Vorab-Analysen. Heutige
  Erklärungen zu vergangenen Spielen wären kein damaliges Wissen. Dieses
  Signal bleibt ungeprüft und braucht ab jetzt gespeicherte Analysen.
- **Streuung zwischen den Einzelmodellen** des Ensembles wurde nie
  archiviert, konnte also nicht als Merkmal dienen.
- Nur Bundesliga, ein Buchmacher, retrospektiv — dieselben Grenzen wie im
  Vergleich unter `selection_comparison_20260923/`.

## Folgerung

Nach der im Vorschlag selbst gesetzten Maßgabe — findet der Ansatz außerhalb
seiner Entwicklungsdaten keinen Vorteil, wird er nicht als profitable
Empfehlung veröffentlicht — lautet die Antwort: nicht veröffentlichen.

## Reproduzieren

```sh
python3 scripts/learned_bet_selector.py --scope all_markets_preclosing
```
