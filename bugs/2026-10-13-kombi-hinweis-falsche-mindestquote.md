# Kombi-Hinweis nennt falsche Mindestquote

**Status:** behoben (Test `test_missing_size_names_the_minimum_odds_of_the_rule_in_use`)
**Gemeldet:** 13.10.2026
**Betrifft:** Kombi-Ansicht der Seite, `src/combo_ticket.py`

## Symptom

Fehlt eine 2er-, 3er- oder 4er-Kombi, erklärt die Seite: „Dafür braucht es …
eine Gesamtquote von mindestens 2,00.“ Die angezeigte Regel („agree“, seit
4. Oktober) verlangt aber mindestens **3,00**. Die Erklärung über der Liste
nennt korrekt 3,00; die beiden Angaben widersprechen sich.

## Ursache

`day_reports()` in `src/combo_ticket.py` (Zeile 318) setzt den Text mit der
Konstanten `MIN_COMBINED_ODDS` (2,0) zusammen statt mit der Mindestquote der
jeweiligen Regel, die die Funktion als Parameter `min_odds` bereits bekommt
(`min_combined("agree")` = 3,0).

## Korrektur

Der Text verwendet jetzt `min_odds`, also die Mindestquote der Regel, die
`combo_report()` übergibt. Test in `tests/test_combo_sizes.py`: Mit
Mindestquote 3,0 nennt jeder Grund „mindestens 3.00“. Vor der Korrektur
schlug er fehl.
