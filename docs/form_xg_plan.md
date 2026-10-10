# Plan: Die aktuelle Form besser abbilden (xG-Bewertung)

Stand 10. Oktober 2026. Ein Plan, noch nichts davon ist umgesetzt. Gilt für das
Vereinsmodell (Bundesliga, Champions League); Nationalmannschaften siehe
„Grenzen“.

## Die Idee

Die aktuelle Form macht vermutlich mehr aus, als das Modell abbildet. Ein
früherer Versuch, die Form stärker zu gewichten, machte die Vorhersagen
schlechter. Die Vermutung dahinter: Nicht das Gewicht ist falsch, sondern die
Messung. Das Modell kennt pro Spiel nur den Endstand. Wie eine Mannschaft
gespielt hat (Chancen, Schüsse), wer die Tore schießt und wer fehlt, sieht es
nicht oder nur teilweise.

## Ausgangslage

**Wie die Form heute gemessen wird.** `src/club_features_v3.py`: die letzten
10 Spiele je Team, exponentiell gewichtet (Halbwertszeit 5 Spiele), daraus
Punkte, Siege, Unentschieden, Tore, Gegentore, Zu-null-Spiele, Tordifferenz.
Die Rohdaten (`data/club_raw/*.csv`) enthalten nur Datum, Teams und Endstand.
Daneben stehen Elo (`src/club_elo.py`, nur aus Ergebnissen, K = 20) und der
Kader-Marktwert. Ausfälle wirken erst am Spieltag über den Marktwert der
Startelf (`src/lineups.py`).

**Was die Ergebnis-Form heute beiträgt.** `scripts/form_probe.py`, Bundesliga,
gelernt auf 2013-14 bis 2021-22, geprüft auf 1.260 Spielen ab 2022-23, alles
streng zeitlich. Multinomiale logistische Regression, damit sich die Varianten
nur in den Merkmalen unterscheiden. Log-Loss, kleiner ist besser; Klammer =
95-%-Bootstrap-Intervall der Differenz.

| Variante | Log-Loss | Differenz zur Basis |
|---|---:|---:|
| Basis: Elo + Marktwert | 0,9763 | – |
| + Form wie heute (10 Spiele, HWZ 5) | 0,9752 | −0,0010 [−0,0060; +0,0040] |
| + Form stärker gewichtet (HWZ 2) | 0,9757 | −0,0006 [−0,0052; +0,0043] |
| + letzte 3 und 5 Spiele | 0,9759 | −0,0003 [−0,0057; +0,0049] |
| + Form gegen Elo-Erwartung (5/10) | 0,9785 | +0,0023 [−0,0012; +0,0055] |
| nur Form, ohne Elo und Marktwert | 1,0197 | +0,0435 [+0,0263; +0,0602] |

Die Ergebnis-Form enthält Information (letzte Zeile), aber dieselbe, die Elo
schon hat: Elo wird nach jedem Spiel angepasst und ist selbst eine Formkurve.
Kein Zeitfenster und keine Gewichtung bringt zusätzlich etwas. Das erklärt den
früheren Versuch: Stärkere Gewichtung verstärkt bei Ergebnissen vor allem den
Zufall.

**Warum Ergebnisse die Form schlecht messen.** Ein 1:0 nach einem abgefälschten
Schuss und ein 1:0 nach zwanzig Torchancen sind in unseren Daten gleich. Über
drei bis fünf Spiele ist der Endstand zu großen Teilen Glück. Chancenqualität
(Schüsse, Schüsse aufs Tor, xG = erwartete Tore) schwankt über wenige Spiele
deutlich weniger.

**Der Maßstab Markt.** Laut `docs/session_findings_20260925_for_astra.md`
erreicht Pinnacle einen Log-Loss von etwa 0,936, unser Modell etwa 0,98, und
das Modell enthält keine Information, die Pinnacle fehlt. Der Markt nutzt xG,
Aufstellungen und Verletzungen längst. Realistisches Ziel ist, einen Teil
dieses Abstands aufzuholen und bessere Wahrscheinlichkeiten anzuzeigen. Dass
das Modell dadurch den Markt schlägt, ist nicht zu erwarten und wird eigens
geprüft (Schritt 5).

## Entscheidung: Wohin gehören die neuen Daten?

**Elo bleibt unverändert bei den Ergebnissen. Die Chancendaten bekommen eine
eigene, zweite Stärke-Bewertung neben Elo.** Das Modell lernt selbst, wie viel
es welcher Bewertung glaubt.

Verworfen, aber im Test als Gegenprobe enthalten:

- **xG in Elo mischen** (z. B. 60 % xG, 40 % Ergebnis). Das Mischverhältnis
  wäre handgetunt. Für viele Teams gibt es kein xG (2. Bundesliga, viele
  Champions-League-Gegner, Nationalmannschaften); Elo würde dann für einen Teil
  der Teams anders berechnet, und gerade in der Champions League treffen beide
  Gruppen aufeinander. Frühere Auswertungen wären nicht mehr vergleichbar, und
  bei einer Verschlechterung wäre die Ursache nicht zu trennen.
- **xG als einfacher Durchschnitt der letzten Spiele.** Hat denselben Fehler
  wie die heutige Form: Der Gegner zählt nicht. Drei Spiele gegen
  Abstiegskandidaten blähen xG genauso auf wie Punkte.

### Die xG-Bewertung

Wie Elo, aber für Chancen statt Ergebnisse. Jedes Team hat eine
Angriffsstärke `att` und eine Abwehrstärke `def`, beide anfangs 0.

1. Vor dem Spiel, für beide Seiten:
   `erwartete_xG_heim = exp(mu + heimvorteil + att_heim − def_gast)`,
   `erwartete_xG_gast = exp(mu + att_gast − def_heim)`.
   `mu` und `heimvorteil` aus dem Ligadurchschnitt der Trainingsjahre.
2. Nach dem Spiel, mit dem tatsächlichen xG:
   `att_heim += k · (xG_heim − erwartete_xG_heim)`,
   `def_gast −= k · (xG_heim − erwartete_xG_heim)`, für die Gastseite
   entsprechend.
3. `k` bestimmt, wie schnell neue Spiele wirken. Das ist das „letzte Spiele
   zählen mehr“, nur gegnerbereinigt. `k` wird auf den Trainingsjahren
   gewählt, nie auf den Testjahren.
4. Zu Saisonbeginn werden die Werte ein Stück zurück Richtung 0 gezogen
   (Kaderwechsel), Anteil ebenfalls auf den Trainingsjahren gewählt.
5. Merkmale für das Modell: `att`, `def` beider Teams, daraus die erwartete
   xG-Differenz, und `xg_rating_missing`, wo ein Team keine xG-Historie hat.

Fehlt xG für ein Team, bleibt die Bewertung „unbekannt“ und das Modell stützt
sich auf Elo und Marktwert. Als Ersatz, wo es Schüsse aber kein xG gibt, wird
dieselbe Bewertung mit Schüssen aufs Tor statt xG gerechnet (eigene Merkmale,
nicht vermischt).

### Wohin die übrigen Daten gehören

| Daten | Ort | Begründung |
|---|---|---|
| xG, Schüsse aufs Tor | xG-Bewertung | beschreiben die Stärke über die Zeit |
| Ergebnisse | Elo (wie heute) | Grundlage für alle Teams |
| Verletzungen, Sperren | Spieltags-Anpassung (`src/lineups.py`, vorhanden) | betreffen dieses eine Spiel, nicht die Stärke. In Elo oder Form würde ein Team nach der Rückkehr des Stürmers noch als schwach gelten |
| Torschützen | Spieltags-Anpassung, als „Anteil der Saisontore, der heute fehlt“ | direkter als der Marktwert der fehlenden Spieler |
| Torzeitpunkt | vorerst nicht | kaum Vorhersagewert für das nächste Spiel |

## Daten

| Quelle | Inhalt | Abdeckung | Zweck |
|---|---|---|---|
| football-data.co.uk | Schüsse, Schüsse aufs Tor, Ecken je Spiel; Pinnacle-Quoten | Bundesliga über viele Jahre | Schuss-Bewertung, Ersatz für xG |
| Understat | xG je Spiel und je Schuss | Bundesliga etwa ab 2014-15 (die fünf großen Ligen) | xG-Bewertung |
| ESPN (schon genutzt für Ergebnisse, Aufstellungen) | Spielzusammenfassung, vermutlich mit Schüssen und Torereignissen | laufend | tägliche Aktualisierung, noch zu prüfen |

Abdeckung, Nutzungsbedingungen und ob ESPN Schüsse liefert, sind vor dem
Einbau zu bestätigen. Champions-League-Teams aus den großen Ligen bekommen
ihre Bewertung aus den Ligaspielen; die Champions-League-Spiele selbst haben
in diesen Quellen oft kein xG.

Die Cloud-Umgebung sperrt derzeit `understat.com`, `www.football-data.co.uk`,
`site.api.espn.com` und `api.openligadb.de`. Sie müssen unter „Allowed
domains“ freigegeben werden.

## Schritte

1. **Daten holen und ablegen.** Je Quelle ein Skript unter `scripts/`, Ablage
   in `data/club_stats/` (eine CSV je Liga und Saison: Datum, Teams, xG,
   Schüsse, Schüsse aufs Tor). Teamnamen über `scripts/build_club_training_data._canon`
   auf unsere Schreibweise abbilden. Prüfung: jedes Bundesliga-Spiel in
   `data/club_raw` hat genau eine Zeile oder einen dokumentierten Grund, warum
   nicht; die Endstände stimmen überein.
2. **Vergleichstest in `scripts/form_probe.py` erweitern**, gleiche Spiele,
   gleiche Aufteilung, gleiches Modell:
   1. Basis: Elo + Marktwert
   2. + xG-Durchschnitt der letzten Spiele, ohne Gegnerbereinigung
   3. + xG-Bewertung neben Elo
   4. + Schuss-Bewertung neben Elo
   5. Elo ersetzt durch eine Mischung aus Ergebnis und xG (30, 50, 70 % xG)
3. **Vorab festgelegtes Erfolgskriterium.** Eine Variante gilt nur als
   besser, wenn das 95-%-Intervall ihrer Log-Loss-Differenz zur Basis
   vollständig unter 0 liegt. Bei Gleichstand gewinnt die einfachere Variante;
   zwischen 3 und 5 also 3, weil Elo dann für alle Teams gleich bleibt.
   `k`, Rückzug zu Saisonbeginn und Mischanteile werden nur auf den
   Trainingsjahren gewählt.
4. **Im echten Modell nachprüfen.** Die Gewinner-Merkmale in
   `club_features_v3.py` aufnehmen (neue `FEATURE_VERSION`), Ensemble neu
   trainieren, mit `scripts/eval_v1_ablation_season.py` gegen das
   Produktionsmodell auf derselben Saison vergleichen. Das Ensemble kann
   anders reagieren als die Regression.
5. **Gegen den Markt prüfen.** `scripts/does_the_model_add_anything.py` mit
   dem neuen Modell. Senkt eine Beimischung den Log-Loss gegenüber Pinnacle
   allein nicht, bleibt das Ergebnis eine bessere Anzeige, aber keine
   Wettgrundlage. So wird es auch auf der Seite beschriftet.
6. **Einbauen.** Tägliche Aktualisierung der Spieldaten im Job
   (`src/jobs.run_daily`), Ablage auf dem Fly-Volume wie die übrigen Daten.
   Teams ohne Daten bekommen `xg_rating_missing = 1`, nie einen geschätzten
   Wert. Die Vorhersage speichert, welche Bewertungen sie benutzt hat.
7. **Torschützen-Anteil** als zweite, getrennte Stufe in `src/lineups.py`,
   mit eigenem Vorher-nachher-Vergleich wie in Schritt 2 und 3.

## Grenzen

- Für Nationalmannschaften (Nations League, WM) gibt es kaum frei verfügbares
  xG. Dort bleibt die Form über Ergebnisse abgebildet.
- 2. Bundesliga: Abdeckung offen. Aufsteiger haben in der ersten
  Bundesliga-Saison womöglich keine xG-Historie.
- 1.260 Testspiele erkennen Verbesserungen ab etwa 0,005 Log-Loss
  verlässlich. Ein kleinerer, echter Effekt kann unentdeckt bleiben.
- Ein besseres Modell bleibt wahrscheinlich hinter Pinnacle. Der Plan
  verspricht bessere Wahrscheinlichkeiten, keinen Gewinn beim Wetten.
