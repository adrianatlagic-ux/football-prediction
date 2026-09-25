# Bericht an Astra: Zusammenführung, Kaderdaten und die Frage nach dem Vorteil

Nachtrag zu `bet_selection_findings_for_astra.md` (24.09.). Er umfasst alles
seither: den Zusammenführungs-Branch, die Kaderdaten über Transfermarkt, die
Aufräumarbeiten an der Oberfläche und drei weitere Versuche, einen Vorteil
gegenüber dem Markt zu finden. Einer davon zeigt erstmals in eine positive
Richtung – mit Einschränkungen, die weiter unten stehen.

**Stand:** Die beschriebene Arbeit liegt auf Branch `merge/codex-into-claude`,
32 Commits vor `claude/relaxed-ptolemy-2h8w0`, 174 Tests grün, sauberes
Vorspulen auf den Hauptbranch möglich. Noch nicht gepusht – in dieser Umgebung
gibt es keine GitHub-Zugangsdaten. Dieser Bericht selbst liegt auf
`codex/bet-selection`, weil die Sitzung nur in ihren eigenen Arbeitsbaum
schreiben darf; er gehört beim Zusammenführen mit hinüber.

---

## Kurzfassung

| Frage | Ergebnis |
|---|---|
| Kann die KI-Recherche Ausfälle zuverlässig liefern? | Nein. 5 identische Anfragen, 0 übereinstimmende Spieler; Temperatur 0 macht es schlechter |
| Bringen vollständige Marktwerte (86 statt 48 Nationen) etwas? | Nicht messbar (p = 0,18). Behalten, weil vorher eine falsche Null im Modell stand |
| Bewegt die Kaderkorrektur vor Anpfiff die Vorhersage? | Kaum. Nations League 0,0–0,2 Punkte, Bayern ohne Laimer −0,11 Punkte |
| Schlägt der Preisvergleich gegen Pinnacle die Schlussquote? | Ja, in den Prüfjahren signifikant – aber großteils durch Ausreißerpreise |
| Hilft unser Modell bei der Auswahl darunter? | Nein. CLV ist flach über alle Modellmeinungen |
| Schlägt eine KI mit allen Signalen und eigenem Urteil den Markt? | Nein. Eigenes Urteil: −2,38 % CLV, signifikant negativ |
| Gibt es den Preisvorteil auch bei in Deutschland zugelassenen Buchmachern? | Ja, klein und selten. bet-at-home: 46 Gelegenheiten in 389 Spielen, Ø +7,9 % EV |
| Weiß unser Modell etwas, das Pinnacle nicht weiß? | Nein. Schon 5 % Modell-Beimischung verschlechtert die Vorhersage auf neuen Spielen |

Die zentrale Aussage nach diesen Tagen: **Alles, was eine Meinung über das
Spiel bildet, verliert gegen den Markt. Positiv ist nur ein Buchmacher, der
über Pinnacles margenbereinigter Quote liegt.** Das gilt auch für
Buchmacher, die Adrian legal nutzen kann – dort allerdings in kleinem Umfang.

Adrian will mit **einem** Buchmacher arbeiten. Der Vorschlag am Ende dieses
Berichts ist deshalb ein reiner Preistipp bei bet-at-home, ohne Modell. Dazu
brauche ich deine Einschätzung – die Fragen stehen in Abschnitt 10.

---

## 1. KI-Recherche als Datenquelle

Du hattest vorgeschlagen, Analysen vor Anpfiff zu speichern, statt sie
nachträglich zu erklären. Das ist gebaut (`src/research_schema.py`,
`scripts/log_research.py`), und der erste echte Lauf am 24.09. hat die Frage
gleich mitbeantwortet.

**Erfundene Ausfälle.** Bei 2 von 8 Nations-League-Spielen (Österreich–Israel,
Norwegen–Dänemark) lieferte Gemini zusammen 20 Ausfälle mit Quellenlinks,
während die Google-Suche null Treffer zurückmeldete. Die Links waren
Vertex-Weiterleitungen; mehrere waren beim Prüfen bereits tot. Quellen ohne
Suche sind ein logischer Widerspruch, keine Ermessensfrage.

**Keine Reproduzierbarkeit.** Dieselbe Anfrage für Niederlande–Deutschland,
fünfmal gestellt:

| | genannte Spieler | in allen 5 Läufen |
|---|---:|---:|
| Standardtemperatur | 5 | **0** |
| Temperatur 0 | 16 | **0** |

Zwei Läufe mit ordentlicher Suchgrundlage meldeten „niemand fehlt", einer
sieben Spieler. Temperatur 0 hat es verschlechtert, es liegt also nicht am
Würfeln. Die Begründungen zeigen die Ursache: Das Modell vermischt echte
Absagen, Nicht-Berücksichtigung für den 23er-Spieltagskader und
Zugehörigkeit zum erweiterten Kreis. Letzteres haben wir mitverursacht, weil
wir Deutschlands 43-Mann-Pool als Kaderliste übergeben hatten.

**Entscheidung (Adrian):** Gemini bleibt als Anzeigetext auf der Seite, fließt
aber nicht ins Modell. Mein Vorschlag, Einschätzungen ohne Suchtreffer
auszublenden, wurde abgelehnt – die Seite zeigt sie wie bisher.

---

## 2. Marktwerte für alle UEFA-Nationen

Die nationale Marktwerttabelle kannte nur die 48 WM-Teilnehmer. Für die
Nations League am 24.09. fehlten **11 von 16 Mannschaften**, und ein fehlender
Wert wurde als 0 gelesen – nicht als „unbekannt", sondern als „wertlos". Das
Verhältnis war dann fest auf 2,0 bzw. 0,5 verdrahtet: Dänemark galt als
wertlos, Norwegen als doppelt so stark.

Jetzt 86 Nationen (54 UEFA über die Nations-League-Teilnehmerseiten), bei
fehlendem Wert ein neutrales Verhältnis plus Merkmal `market_value_missing`
nach dem Vorbild von `fifa_ranking_missing`. Neu trainiert auf 32.237 Spielen:

| | ohne | mit |
|---|---:|---:|
| Treffer | 59,9 % | 60,1 % |
| Log-Loss | 0,8651 | 0,8639 |

87,2 % der Testspiele waren betroffen. Paarweise änderte sich der Tipp bei 279
Spielen: 110 wurden richtig, 91 falsch. McNemar **p = 0,18** – nicht von
Zufall zu unterscheiden. Plausibler Grund: Weil 0 und 2,0 nur bei Lücken
vorkamen, hatte das alte Modell sie als „keine Information" gelernt.
Behalten aus Korrektheitsgründen, nicht wegen eines Effekts.

Das Nationalmodell braucht damit 35 statt 33 Merkmale. **Das Modell im
Hauptverzeichnis vom 4. Juli lädt mit dem neuen Code nicht.** Modelldateien
sind nicht im Repo (`*.joblib` in `.gitignore`); beim Ausrollen muss das
aktuelle mit.

---

## 3. Kaderdaten über Transfermarkt

### Aufbau

`src/competitions.py` hält die drei Dinge, die sich zwischen Wettbewerben
unterscheiden, und nur diese:

| | Nationalteam | Verein |
|---|---|---|
| Kaderliste bedeutet | Nominierung – Verletzte stehen nicht drin | fester Kader – Verletzte stehen drin |
| Ausfallseite bei Transfermarkt | gibt es nicht | gibt es |
| Sperren gelten | nie (anderer Wettbewerb) | nur im verhängenden Wettbewerb |

`data/team_registry.csv` sammelt je Mannschaft die Transfermarkt-Id (110
Mannschaften, 4 Wettbewerbe). `src/squad_data.py` holt über Apify Kader und
Spielerwerte.

### Was dabei aufgefallen ist

**Eigener Parser still falsch.** Der kostenlose Direktabruf verschluckte bei
jeder Mannschaft genau einen Spieler (Deutschland 42 statt 43, Niederlande 25
statt 26), ohne Fehlermeldung – die Plausibilitätsprüfung mit 15 % Toleranz
ließ 2,7 % Abweichung durch. Apify liefert auf den Euro identische Werte bei
jedem Abruf. Deshalb Apify.

**Apify liefert keine Verletzungen.** Das Feld `injuries` enthält nur Sperren
und Meldelisten-Einträge; Bayern, Dortmund und Leverkusen kamen alle mit null
Verletzten zurück. Die Vereinsseite `/sperrenundverletzungen/` listet sie
dagegen (Bayern: Laimer, Adduktoren; Real Madrid: vier Ausfälle). Die wird
jetzt zusätzlich gelesen.

**Sperren im falschen Wettbewerb.** Ein Probelauf meldete vier Dortmunder als
ausgefallen für ein Bundesligaspiel: eine Rote Karte im DFB-Pokal und drei
fehlende Champions-League-Meldungen. Alle vier hätten gespielt. Sperren und
Meldelücken zählen jetzt nur, wenn ihr `competitionId` der gespielte
Wettbewerb ist; eine Sperre ohne erkennbaren Wettbewerb sperrt niemanden.

**Zwischenspeicher je Spieltag.** Das erste Spiel eines Tages legte seine zwei
Mannschaften ab, jedes weitere bekam einen Treffer ohne eigene Teams und blieb
still unkorrigiert – eins von neun. Jetzt je Mannschaft.

### Ablauf

`scripts/refresh_squad_predictions.py`, geplant über
`.github/workflows/refresh_squads.yml` alle 15 Minuten, handelt bei Spielen im
75-Minuten-Fenster vor Anpfiff: Kader holen, neu rechnen, in den Cache
schreiben, per `POST /predictions/{id}` an die laufende App schicken.

Der Upload ist nötig, weil das Dockerfile `data/` mit `COPY . .` ins Image
backt – ein Commit am Cache erreicht die laufende App sonst nicht.

**`POST /predictions/{id}` hatte keine Authentifizierung.** Jeder mit der URL
konnte festlegen, was das Modell scheinbar vorhersagt. Jetzt Pflicht-Token,
sobald `PREDICTIONS_WRITE_TOKEN` in der Umgebung gesetzt ist; ungesetzt bleibt
es lokal offen.

### Was es bewirkt

Der Job rechnet jedes Spiel zweimal – mit und ohne Kaderdaten –, weil die erste
Fassung Verschiebungen bis 14,5 % meldete, die ausschließlich vom Neutraining
gegenüber dem alten Cache stammten.

- **Nations League:** 0,0 bis 0,2 Punkte. Der gespeicherte Nationalwert stammt
  aus derselben Seite wie der Kader; die Korrektur korrigiert gegen sich selbst.
- **Bayern ohne Laimer** (34 von 1.040 Mio): −0,11 Punkte Heimsieg.

Das Vereinsmodell reagiert als Treppe, nicht als Rampe:

| fehlender Kaderwert | Heimsieg Bayern |
|---:|---:|
| 1–4 % | unverändert |
| 5 % | −1,2 Punkte |
| 6 % | −2,1 Punkte |
| 8 % | −1,8 Punkte |
| 10 % | −2,4 Punkte |

Nicht einmal durchgehend gleichgerichtet. Die Korrektur ist sauber verdrahtet
und klein. Adrian wollte sie stärker gewichten; ich habe davon abgeraten:
Transfermarkt ist öffentlich und längst eingepreist, stärkere Gewichtung
erhöht nur den Widerspruch zum Markt, und der ist nachweislich
anti-prädiktiv.

---

## 4. Zusammenführung codex → claude

69 der 81 von beiden berührten Dateien waren inhaltlich identisch; die
Bundesliga-Arbeit war auf beiden Strängen zum selben Ergebnis gekommen.
Zwölf echte Konflikte, aufgelöst danach, welche Seite weiter war:

- **codex:** `src/club_*.py` (hat `as_of`, Validierung bleibt zeitpunktgenau),
  `international_results.csv`, Wappen (149 statt 85)
- **claude:** `App.jsx`, `App.css`, `log_bets.py`, `grade_bets.py`
- **`api/app.py`:** codex' modulare Struktur, aber **claudes Game-Pick-Verfahren**
  (Marktfavorit, Modell und KI als Ampel). Adrians Entscheidung: kein
  Stresstest-Selektor für den angezeigten Tipp. `selection_policy` heißt jetzt
  `market_favorite_consensus_v1` statt fälschlich weiter `robust_game_pick_v1`.

**Für dich relevant:** `bet_selection.combine` und damit `select_game_pick`
werden von der App nicht mehr aufgerufen, nur noch von Tests. Ob das weg soll
oder als Vergleichsstrategie bleibt, ist deine Entscheidung.

### Beim Zusammenführen gefunden

- **Doppeltes `_fetch_event_odds`.** claudes Fassung war fest auf
  `soccer_uefa_champs_league` verdrahtet, nahm eine Id statt des Events und
  überschrieb codex' Fassung – Bundesliga und Nations League hätten still die
  falsche Liga abgefragt.
- **Überkonfidenz-Dämpfung verschwunden.** claude mischte die
  Modellwahrscheinlichkeit zur Hälfte Richtung Markt in der EV-Zeile; codex
  hatte dieselbe Mischung im Stresstest. Kombiniert fiel sie aus beiden – bei
  Quote 2,05, Modell 60 %, Markt 46,5 % stand +23,0 % statt +9,1 % EV. Wieder
  eingebaut nach `price_bet`, nur für binäre Märkte, drei Tests.
- **`data/placed_bets.jsonl` gelöscht.** In claudes Commit 687da28 beim
  Umstellen von WM auf CL, vermutlich nebenbei. Wiederhergestellt: 10 echte
  Wetten, 4 gewonnen, 79,10 € Einsatz, 54,80 € zurück, **−30,7 %**.

Zusätzlich liegt Commit `2b89ad5` auf dem Branch, der nicht aus meiner Sitzung
stammt: stabiler Schlüssel für den Vorab-Cache, Schreib-Token beim
CL-Upload, und Kombi-Beine mit `high_deviation` oder `contradicts_favorite`
ausgeschlossen. Passt zum Rest; die Tests laufen.

---

## 5. Oberfläche

- **Best Bets entfernt.** Die Liste stellte sich als „our strongest value bets
  … that's your edge" vor und zeigte für die Nations League am 24.09. acht
  Tipps mit −8 % bis −18 % Edge. Kein Anzeigefehler: Der Marktfavorit hat bei
  kurzen Quoten konstruktionsbedingt negativen Edge. Der Text gehörte zu einem
  älteren Selbstverständnis der Seite.
- **„★ Value Bet" heißt jetzt „★ Biggest gap to the market"** und sagt dazu,
  dass ein großer Abstand in der Vergangenheit schlechtere Ergebnisse
  vorhergesagt hat.
- **Viertel- und Ganzzahl-Linien raus**, auch als Einzelwette. Die Kombi schloss
  sie schon aus; als Einzeltipp ließ sich „halb gewonnen" nicht ehrlich zeigen.
- **Kombi-Tickets neu.** Das alte Verfahren ließ in der Nations League 0 Beine
  zu: 46 fehlten drei vollständige Vergleichsbuchmacher, 30 hatten nach dem
  Stresstest keinen Vorteil. Jetzt: Modell ≥ 55 %, Markt hält dieselbe Seite
  für wahrscheinlicher, Quote frisch. Nach Wahrscheinlichkeit allein
  sortiert kam ein Zweier zu 1,58 heraus – schlechter als eines seiner Beine –,
  daher Mindestquote 2,0. Einsatz pauschal 1 %, keine Vorteilsbehauptung.
- **Wettbewerbe umschaltbar** (CL, Bundesliga, Nations League), **Vereins- und
  Nationalfarben** übernommen – die Daten kamen mit dem Merge, die Logik nicht.

---

## 6. Suche nach einem Vorteil

### Preisvergleich gegen Pinnacle

`scripts/pinnacle_edge_test.py`. Idee: Wenn ein Buchmacher mehr zahlt als
Pinnacles margenbereinigte Quote, ist das ein Preisfehler, keine Meinung.
2.073 Spiele (1. und 2. Bundesliga), Schwellen vorher festgelegt,
Prüfjahre 2023-24 und 2025-26.

Bester Preis über alle Buchmacher, Prüfjahre:

| Schwelle | Wetten | CLV (95 %) | schlägt Schluss | ROI |
|---:|---:|---|---:|---:|
| 0 % | 645 | +1,93 % [+1,13, +2,74] | 60 % | +0,3 % |
| 2 % | 272 | +4,46 % [+3,01, +6,08] | 67 % | −2,3 % |
| 5 % | 90 | +9,10 % [+5,40, +13,08] | 71 % | −5,6 % |

Das erste Ergebnis im Projekt, das außerhalb der Stichprobe in die richtige
Richtung zeigt. Es hält dem naheliegenden Einwand aber nicht stand:

| Bestpreis über Marktdurchschnitt (2 %, Prüfjahre) | Wetten | CLV | ROI |
|---|---:|---|---:|
| unter 5 % (realistisch) | 28 | +1,83 % [−0,28, +4,03] | +76 % |
| 5–10 % | 165 | +2,87 % [+1,49, +4,21] | −9,2 % |
| über 10 % (wahrscheinlich Ausreißer) | 79 | +8,73 % | −15,7 % |

Der größte Teil stammt aus Preisen weit über allen anderen – typischerweise
veraltete oder fehlerhafte Quoten, die storniert würden. Nur mit Bet365 liegt
der CLV in den Prüfjahren zwischen −2,73 % und +0,19 %: mit einem normalen
Konto nichts. ROI bestätigt es in keiner Zelle.

### Modell plus Preisabstand

`scripts/pinnacle_plus_model_test.py`, 567 Bundesliga-Wetten über 2 % Abstand:

| Modellmeinung (Fünftel) | CLV |
|---|---:|
| sehr skeptisch | +4,97 % |
| | +4,01 % |
| | +5,87 % |
| | +5,07 % |
| begeistert | +5,22 % |

Flach. Kombiniert wird es schlechter: obere Hälfte nach Preis allein +7,35 %,
nach Preis plus Modell +5,92 %. Der ROI sagt das Gegenteil (+20,7 % gegen
−8,5 %) und ist Rauschen – je Fünftel −14, +21, −24, +41, +31 %. Dasselbe
Muster wie beim ROI-getunten Selektor vom 23.09.

### KI mit allen Signalen und eigenem Urteil

Adrians Hypothese: Ein Sprachmodell, das alle Signale bekommt und wie ein
Mensch abwägt, erzeugt eine Informationsasymmetrie. `scripts/llm_bettor_test.py`,
455 Spiele der Prüfjahre, **Namen, Daten und Wettbewerb entfernt**, damit die
KI keine gemerkten Ergebnisse abruft. Zwei Prompts auf identischen Daten.

| Verfahren | Wetten | CLV (95 %) |
|---|---:|---|
| Zufall | 455 | +0,18 % |
| Marktfavorit | 455 | −2,01 % |
| unser Modell, höchster EV | 455 | −0,44 % |
| Preis > 2 % über Pinnacle | 186 | +5,96 % [+3,82, +8,23] |
| KI: nüchterner Analyst | 379 | −0,09 % |
| KI: „bester Wetter der Welt" | 224 | +3,90 % [+2,24, +5,71] |

**Die Persona gewinnt nur scheinbar, und das liegt an meinem Prompt.** Ihre
Prinzipien – von mir geschrieben – lauteten „wette auf falsche Preise, nicht
auf Sieger" und „die Schlussquote des schärfsten Buchmachers ist die
Wahrheit". Das ist die Pinnacle-Regel in Prosa. 96 % ihrer Wetten liegen über
Pinnacle, 75 % der Regelwetten hat sie übernommen, ihr CLV stammt vollständig
aus diesen (+5,86 %), und ihre eigenen Zusätze haben ihn unter die einfache
Regel gedrückt. Ihr Brier-Wert (0,5556) liegt nah an Pinnacle (0,5537), weil
sie dessen Wahrscheinlichkeiten übernommen hat, wie angewiesen.

**Die eigentliche Antwort steckt beim Analysten:** Wo er gegen den Markt auf
sein eigenes Urteil setzte (Preis unter Pinnacles fairer Quote), ergaben 220
Wetten **−2,38 % [−3,50, −1,31]** – signifikant negativ, dieselbe Richtung wie
unser Modell überall sonst.

### Nach Quotenhöhe

Derselbe Preisvergleich, Prüfjahre, Schwelle 2 %, aufgeteilt nach der Quote:

| Quotenbereich | Wetten | CLV (95 %) | gewonnen |
|---|---:|---|---:|
| unter 2,5 | 13 | zu wenige | 62 % |
| **2,5 – 5** | **138** | **+2,45 % [+1,45, +3,49]** | 29 % |
| 5 – 10 | 77 | +4,83 % | 10 % |
| über 10 | 44 | +10,79 % | 5 % |

Die großen Werte bei Außenseitern sind am wenigsten glaubwürdig: Dort sind
gerundete und veraltete Quoten am häufigsten, und bei 5 % Trefferquote
entscheidet ein einzelner Treffer über den ROI. **Der belastbarste Bereich
sind ausgeglichene Spiele mit Quoten zwischen 2,5 und 5.**

### Live-Stand

Pinnacle ist im Feed der Odds API enthalten (69 Quoten über 18 CL-Spiele).
**Tipico nicht.** Am 25.09. lagen drei Angebote über Pinnacle, alle auf die
Türkei gegen Frankreich: Betfair-Börse 9,80 (vor Gebühr), onexbet und
marathonbet 9,30 – letztere in Deutschland nicht zugelassen.

---

## 7. Buchmacher, die Adrian nutzen kann

Der Archivtest rechnete mit dem besten Preis über rund 40 Buchmacher, die
meisten in Deutschland nicht nutzbar. Deshalb die praktische Frage.

### Quellen

| Quelle | Inhalt | Kosten |
|---|---|---|
| Odds API (vorhanden) | ~20 Buchmacher, **inkl. Pinnacle**, meist SE/FR/IT-lizenziert | bezahlt |
| Oddsportal über Apify (`piotrv1001/oddsportal-scraper`) | je Buchmacher 1X2; mit `apifyProxyCountry: "DE"` genau die in Deutschland lizenzierten | ~0,3 ct/Spiel; mit Eröffnungs-/Schlussquote je Buchmacher ~2 ct |
| Flashscore über Apify | je Buchmacher, braucht Spiel-IDs | nicht getestet |
| **Tipico** | **in keiner Quelle gefunden** | – |

Oddsportal führt **kein Pinnacle** – weder mit deutschem noch mit maltesischem
Proxy. Historische Pinnacle-Schlussquoten kommen aus dem football-data-Archiv,
das sie für 2025-26 nur bis zur Saisonmitte enthält (149 Spiele).

Für die aktuelle Quote liefert Oddsportal keinen Zeitstempel, nur für die
Eröffnungsquote. Für einen Abruf vor Anpfiff reicht das; Sekunden-Live-Quoten
sind es nicht.

### Test: deutsche Buchmacher gegen Pinnacles Schlussquote

`scripts/german_books_vs_pinnacle.py`, 389 Bundesligaspiele (2023-24 und
2025-26 bis zur Saisonmitte). **Beide Preise sind Schlussquoten, im selben
Moment verglichen** – das beseitigt das Problem veralteter Quoten aus dem
Archivtest. Pinnacles Schlussquote gilt als beste Schätzung der wahren
Wahrscheinlichkeit; eine Quote darüber ist per Konstruktion positiver
Erwartungswert.

| Buchmacher | Ø gegen fair | Fälle > 2 % über fair | EV dieser Fälle |
|---|---:|---:|---:|
| **bet-at-home.de** | −5,71 % | **46** | **+7,93 %** |
| Betano.de | −5,13 % | 38 | +5,61 % |
| Interwetten.de | −6,39 % | 31 | +3,18 % |
| bet365 | −5,91 % | 21 | +3,99 % |
| Neobet | −5,68 % | 11 | +5,58 % |
| Bet365.de | −6,02 % | 11 | +4,25 % |
| Winamax.de | −5,16 % | 7 | +3,50 % |
| Oddset.de | −6,88 % | 2 | +3,10 % |

Im Schnitt liegen alle 5–7 % unter fair, das ist ihre Marge. Nur ein paar
Prozent ihrer Preise liegen darüber. Den ROI je Buchmacher lasse ich weg: Bei
11 bis 46 Wetten schwankt er zwischen −100 % und +27 %.

### Warum bet-at-home

| | bet-at-home | Betano | Interwetten |
|---|---:|---:|---:|
| Gelegenheiten | 46 | 38 | 31 |
| Vorteil bei Quote unter 2,5 | +6,4 % | +3,6 % | +3,0 % |
| Vorteil bei Quote 2,5–5 | +9,0 % | +5,4 % | +3,2 % |
| davon Quote über 10 | **0** | 13 | 0 |

Bei Betano stammt ein Drittel der Gelegenheiten aus großen Außenseitern,
also aus dem am wenigsten glaubwürdigen Bereich. Bei bet-at-home liegen alle
bei normalen Quoten, 37 von 46 unter 5, und dort ist der Vorteil zugleich am
größten.

Hochgerechnet auf eine volle Bundesliga-Saison mit 10 € Einsatz: etwa
**36 Gelegenheiten, rund 29 € Erwartungswert**. Mit allen vier Buchmachern
zusammen wären es rund 99 Wetten und 58 €. Das ist ein Erwartungswert, keine
Prognose des Ergebnisses; eine Saison kann bei dieser Streuung deutlich im
Minus enden.

---

## 8. Kann das Modell den Preistipp verbessern?

Beim Preistipp ist der Vorteil durch den Preis festgelegt. Das Modell kann
nur helfen, wenn es über den Spielausgang etwas weiß, das Pinnacle entgangen
ist. `scripts/does_the_model_add_anything.py` prüft genau das, mit allen
Spielen: p = (1 − w) · Pinnacle + w · Modell. Trägt das Modell Information,
die dem Markt fehlt, muss ein w > 0 den Log-Loss auf neuen Spielen senken.
Gewicht gewählt auf 2021-22/2022-23, geprüft auf 455 Spielen 2023-24/2025-26.

| gegen | beste Beimischung | Log-Loss Pinnacle allein | mit Modell |
|---|---:|---:|---:|
| Pinnacle-Schlussquote | 5 % | 0,9364 | 0,9373 |
| Pinnacle vor Schluss (Wettzeitpunkt) | 5 % | 0,9380 | 0,9389 |

Beide Male **schlechter**, Intervalle schließen null ein. Das Modell allein:
0,9823. Es enthält keine Information, die Pinnacle fehlt – also hilft es
weder als Filter noch als Gewichtung, Veto oder Tie-Break.

Unter den 46 bet-at-home-Tipps selbst zeigt es eher in die Gegenrichtung:

| Tipps, bei denen das Modell … | Anzahl | gewonnen | erwartet | ROI |
|---|---:|---:|---:|---:|
| … die Wette höher einschätzt als Pinnacle | 19 | 21 % | 29 % | −49 % |
| … die Wette niedriger einschätzt | 27 | 56 % | 50 % | +28 % |

46 Wetten beweisen nichts. Aber „nur Tipps nehmen, die das Modell auch mag"
hätte die schlechtere Hälfte gewählt – dieselbe Richtung wie überall sonst.

---

## 9. Was daraus folgt

In jedem Test dieser Tage gilt dasselbe:

- Unser Modell, gelernte Selektoren, eine KI mit eigenem Urteil – alles, was
  eine **Meinung über das Spiel** bildet, verliert gegen den Markt oder ist
  nicht von Zufall zu unterscheiden.
- Positiv ist nur ein **Buchmacher, der langsamer ist als Pinnacle**. Dafür
  braucht es kein Modell. Bei in Deutschland zugelassenen Buchmachern kommt
  das vor, aber selten, und der erwartete Betrag ist klein.
- Unser Modell weiß nichts, was Pinnacle nicht weiß.

Die Seite ist jetzt so beschriftet, dass sie nur behauptet, was belegt ist:
wer wahrscheinlich gewinnt, nicht womit man Geld verdient.

### Vorschlag: Preistipp bei bet-at-home

1. **Einmal vor jedem Spieltag** (der Zeitplan-Job existiert schon): Pinnacle
   über die Odds API, bet-at-home über Oddsportal mit deutschem Proxy.
   Kosten rund 3 Cent pro Spieltag.
2. **Tipp nur, wo bet-at-home mindestens 2 % über Pinnacles margenbereinigter
   Quote liegt.** Kein Modell, keine KI. Bei mehreren Kandidaten eines Spiels
   der mit dem größten Abstand. Die meisten Spiele haben keinen Tipp.
3. **Kombi** nur aus solchen bet-at-home-Beinen am selben Spieltag. Weil alles
   beim selben Buchmacher liegt, ist das die eine Konstellation, in der eine
   Kombi mathematisch besser ist als Einzelwetten – Vorteile multiplizieren
   sich. Sie kommt selten vor.
4. **Laufende Bilanz**: Jeder Tipp wird mit Zeitpunkt festgehalten und nach
   Anpfiff gegen Pinnacles Schlussquote ausgewertet. Das ist zugleich der
   Vorwärtstest, den das Archiv nicht leisten kann.
5. **Das Modell bleibt Information zum Spiel** (Wahrscheinlichkeiten,
   Spielverlauf), sichtbar getrennt vom Preistipp.

Der bisherige Game Pick (Marktfavorit) würde dann keine Wettempfehlung mehr
sein, sondern nur noch „wer gewinnt wahrscheinlich".

---

## 10. Fragen an dich

1. **Das Testdesign.** Schlussquote gegen Schlussquote vermeidet veraltete
   Quoten, hat aber eine Restlücke: Oddsportals „Schluss" ist die letzte
   erfasste Quote, womöglich Minuten vor Pinnacles Anstoßquote. Siehst du eine
   Möglichkeit, dass der Vorteil ein Zeitartefakt ist – oder einen weiteren
   Fehler im Aufbau?
2. **Reicht die Grundlage?** 46 Gelegenheiten in gut einer Saison. Würdest du
   den Preistipp auf dieser Basis bauen und vorwärts messen, oder vorher den
   Test Eröffnungsquote gegen Schlussquote machen (~14 $, Adrian hat noch ~9 $
   Apify-Budget diesen Monat)?
3. **Ein Buchmacher.** Adrian will nur bei einem wetten. bet-at-home liegt
   vorn, aber das Risiko, bei dauerhaftem Gewinn begrenzt zu werden, trägt
   dann ein einziges Konto. Siehst du das als Grund, doch zwei zu empfehlen?
4. **Game Pick ersetzen oder daneben?** Soll der Preistipp die bisherige
   Wettempfehlung ersetzen, oder läuft beides nebeneinander und die Bilanz
   entscheidet?
5. **Schwelle 2 %.** Festgelegt vor jedem Ergebnis. Würdest du sie ändern,
   oder zusätzlich auf Quoten unter 5 begrenzen, weil dort der Vorteil am
   glaubwürdigsten war?
6. **`game_pick.py` / `bet_selection.combine`** sind in der App unbenutzt,
   nur noch in Tests. Entfernen, oder als Vergleichsstrategie in der Bilanz
   mitlaufen lassen?

---

## 11. Offen

1. **Push und Merge.** `git merge --ff-only merge/codex-into-claude` im
   Hauptverzeichnis, dann pushen. Braucht Zugangsdaten.
2. **Secrets für den Zeitplan-Job:** `APIFY_TOKEN`, `PREDICTION_WRITE_TOKEN`,
   `MODEL_ARTIFACT_URL`; in der App-Umgebung `PREDICTIONS_WRITE_TOKEN`. Ohne
   sie ist der Job inert (er läuft ohnehin nur auf dem Standardbranch).
3. **Preistipp bauen** – nach deiner Antwort auf die Fragen oben.
4. **Die neuen Skripte liegen auf `codex/bet-selection`**
   (`german_books_vs_pinnacle.py`, `does_the_model_add_anything.py`, dazu die
   Oddsportal-Daten), die früheren auf `merge/codex-into-claude`. Beides muss
   beim Zusammenführen zusammenkommen.

---

## Eigene Fehler, die in den Bericht gehören

- Der kostenlose Parser verschluckte still einen Spieler je Mannschaft; ich
  hatte ihn wegen der Kosten empfohlen.
- Die Kaderkorrektur habe ich zuerst beim Seitenaufruf rechnen lassen statt als
  geplanten Job vor Anpfiff. Adrian hat das korrigiert.
- Die erste Messung schrieb der Kaderkorrektur Verschiebungen bis 14,5 % zu,
  die vom Neutraining kamen.
- Der Persona-Prompt enthielt unsere eigene Regel und hat den KI-Test
  verzerrt. Die Zerlegung nach Preisabstand hat es aufgedeckt.
- Die Commit-Nachricht zu `placed_bets.jsonl` nannte zunächst falsche Beträge,
  geschrieben vor der Rechnung; korrigiert.
- Aus dem Live-Vergleich hatte ich Neobet als besten deutschen Buchmacher
  genannt. Der Test über 389 Spiele zeigt: Neobet hatte die wenigsten
  Gelegenheiten, bet-at-home die meisten.
- Meine erste Kostenschätzung für den Oddsportal-Test (4 $) galt nur für die
  Variante Schluss gegen Schluss; Eröffnung gegen Schluss kostet rund 14 $.

---

## Reproduzieren

Auf `merge/codex-into-claude`:

```sh
python3 scripts/pinnacle_edge_test.py
python3 scripts/pinnacle_plus_model_test.py
python3 scripts/llm_bettor_test.py --report-only     # nutzt gespeicherte Antworten
python3 scripts/refresh_squad_predictions.py --dry-run
python3 -m pytest tests/ -q
```

Auf `codex/bet-selection`:

```sh
python3 scripts/german_books_vs_pinnacle.py
python3 scripts/does_the_model_add_anything.py
```

Gespeicherte Ergebnisse: `data/model_reports/pinnacle_edge_20260925.json`,
`data/model_reports/llm_bettor/` (alle 910 KI-Antworten),
`data/model_reports/german_books_vs_pinnacle_20260925.json`,
`data/odds_archive/oddsportal_de_20260925/` (Schlussquoten der deutschen
Buchmacher, 616 Spiele).
