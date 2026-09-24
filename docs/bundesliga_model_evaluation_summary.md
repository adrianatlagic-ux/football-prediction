# Zusammenfassung für Astra: Modell-Vergleich & Bundesliga-Rollout

## Ausgangslage

Parallel zum laufenden Modell (V1) wurde über Codex ein zweiter, überarbeiteter
Ansatz (V2) entwickelt - u.a. mit walk-forward-Auswertung, gestapeltem
Ensemble/Kalibrierung und ein paar weiteren Feature-Ideen. Ziel dieser Runde
war eine ehrliche Antwort auf zwei Fragen: Ist V2 wirklich besser als V1? Und
wenn ja - welche einzelnen Bestandteile lohnen sich, und welche nicht?

Zusätzlich sollte die Bundesliga (1. + 2. Liga) als neue Kategorie auf die
Website kommen, mit denselben Qualitätsstandards wie die Champions League.

## Gefundene Probleme vor dem eigentlichen Vergleich

- **Marktwert-Leck (Look-Ahead Bias):** V1 nutzte einen einzigen aktuellen
  Marktwert-Snapshot für alle historischen Spiele - unabhängig vom
  tatsächlichen Spieldatum. Für einen fairen Vergleich (und für echte
  Aussagekraft von Log-Loss-Metriken) mussten datierte,
  saisongenaue Marktwerte her.
- **Fehlende Liga-Historie für Aufsteiger:** Reine Bundesliga-Daten hätten
  aufgestiegene Teams (2./3. Liga-Vergangenheit) praktisch ohne Formkurve
  dastehen lassen. Deshalb wurden 1. UND 2. Bundesliga (2011-2027) komplett
  über die freie OpenLigaDB-API nachgezogen - 12.171 Spiele / 157 Teams statt
  vorher 2.964 / 120.
- Datierte Marktwerte wurden über den bereits vorhandenen Apify-Actor
  (Transfermarkt-Scraper, `season`-Parameter) nachgezogen, um keine neue
  Bezahlquelle zu brauchen (nur Apify hat hinterlegte Zahlungsdaten).

## Methodik

1. **Spieltag-1+2-Vergleich (2026/27, 18 Spiele):** Erster Test von V1 vs V2 -
   Ergebnis zu verrauscht für eine verlässliche Aussage bei so kleiner
   Stichprobe.
2. **Ganze Saison 2025/26 (306 Spiele, walk-forward):** Auf Wunsch aussagekräftigerer
   Test - Modelltraining bleibt vor Saisonbeginn eingefroren, aber alle
   Features (Form/Elo/H2H/Marktwert) werden pro Spiel mit dem tatsächlichen
   Stand bis zu diesem Tag neu berechnet.
3. **Ablationsstudie:** Da V2 mehrere Änderungen gleichzeitig bündelt, wurde
   jede einzeln gegen denselben V1-Baseline getestet (datierte Marktwerte,
   CatBoost, Elo, Goal-Stats-Sortierfix), danach die vielversprechenden
   Kombinationen.

## Ergebnis der Ablation

| Element | Einzeln besser? | In Kombination? |
|---|---|---|
| Datierte Marktwerte | Beste reine Accuracy | ✅ behalten |
| CatBoost im Ensemble | Accuracy neutral, aber klar bessere Kalibrierung (Log-Loss/Brier) | ✅ behalten |
| Elo-Rating | Leicht positiv einzeln | ❌ verschlechtert die Kombination unter V1-Niveau |
| Goal-Stats-Sortierfix | Kein messbarer Effekt | ❌ nicht übernommen |
| Volles V2-Stacking/Kalibrierungs-Pipeline | - | Schlechter als die gezielte Kombination |

Wichtige Korrektur unterwegs: die erste Empfehlung ("nur datierte Marktwerte")
hat reine Trefferquote optimiert, aber die Kalibrierungsverbesserung durch
CatBoost ignoriert - für ein Produkt, das Wahrscheinlichkeiten/Value-Bets
ausspielt, ist Kalibrierung genauso wichtig wie Trefferquote. Empfehlung
wurde entsprechend auf **datierte Marktwerte + CatBoost, ohne Elo**
korrigiert.

## Was tatsächlich live gegangen ist

- Produktionsmodell umgestellt auf: RF + XGBoost + CatBoost (Ensemble,
  gleich gewichtet) + datierte Marktwerte statt statischem Snapshot.
- Kein Elo, kein volles V2-Stacking - laut Datenlage keine echte
  Verbesserung.
- Auf dem vollen aktuellen Datensatz (12.171 Spiele) neu trainiert.

## Bundesliga-Rollout auf der Website

- Neue Kategorie "🇩🇪 Bundesliga" neben Champions League, inkl. Umschalten,
  Wappen/Farben, Vorhersagen für den kommenden Spieltag (4, 18.-20.09.).
- Beim Testen der neuen Kategorie sind drei echte Bugs aufgefallen und
  behoben:
  1. **Quoten/Value-Bets funktionierten für keine Club-Spiele** (auch nicht
     Champions League) - die Odds-Abfrage war noch fest auf die (nicht mehr
     genutzte) WM-Sportart-ID verdrahtet, ein Rest aus der Zeit vor dem
     Umstieg auf Club-Fußball. Jetzt werden Champions-League- und
     Bundesliga-Quoten zusammen abgefragt.
  2. **Farben im Wahrscheinlichkeits-Donut/Formbalken** - einige Vereinsfarben
     kamen fehlerhaft/dupliziert aus der ESPN-Quelle (z.B. vier Teams mit
     demselben Rot, sechs mit Weiß). Eigene Korrekturliste plus automatische
     Kollisionsvermeidung ergänzt, sodass zwei gegnerische Teams nie dieselbe
     Farbe zeigen.
  3. **Schwarze Lücke im Form-Rating-Balken** - Balken zeigen jetzt einen
     durchgehenden Vergleich ohne Lücke in der Mitte.
- Ein scheinbarer vierter "Bug" (eingefrorene Prozentzahlen bei ~0%) stellte
  sich als reines Artefakt des automatisierten Vorschau-Tools heraus (Chrome
  pausiert Animationen in Hintergrund-Tabs) - kein echter Fehler für echte
  Besucher.

## Status

Alles oben Beschriebene ist in diesem Worktree committet: Modell-Architektur,
neue Bundesliga-Daten/Vorhersagen, Website-Integration inkl. der drei
Bugfixes. Lokal getestet und für gut befunden, bevor committet wurde.
