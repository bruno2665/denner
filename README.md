# denner

Liest die Wochenaktionen von [denner.ch](https://www.denner.ch/de/aktionen/aktuelle-aktionen) aus, ohne KI, und listet sie nach Kategorien als CSV auf. Die Preise werden also exakt übernommen und nicht abgeschrieben.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Verwendung

```bash
# Alle Wochenaktionen, nach Kategorie gruppiert, als denner_aktionen.csv
python denner_aktionen.py

# Nur Aktionen mit mindestens 30 % Rabatt, eigene CSV-Datei
python denner_aktionen.py --min-rabatt 30 --csv top_aktionen.csv

# Nur eine Kategorie, Aktionen der nächsten Woche
python denner_aktionen.py --kategorie Wein --woche naechste
```

| Option | Bedeutung |
|---|---|
| `--csv DATEI` | CSV-Datei (Standard `denner_aktionen.csv`, Trennzeichen `;`, öffnet direkt in Excel) |
| `--min-rabatt N` | nur Aktionen mit mindestens N % Rabatt (`0` = alle) |
| `--kategorie TEXT` | nur Kategorien, deren Name den Text enthält |
| `--woche` | `aktuell` (Standard) oder `naechste` (Vorschau auf die kommende Woche) |
| `--sprache` | `de` (Standard), `fr` oder `it` |
| `--pause S` | Sekunden zwischen Abfragen (Standard 1, damit denner.ch nicht blockiert) |
| `--debug` | jede Antwort von denner.ch als `debug_antwort_N.json` speichern |

## CSV

Eine Zeile pro Aktion, sortiert nach Kategorie und innerhalb der Kategorie nach Rabatt:

| Spalte | Inhalt |
|---|---|
| `kategorie` | Denner-Kategorie, z. B. «Fleisch/Wurst/Fisch» oder «Wein/Champagner» |
| `name` | Produktname bzw. Beschreibung der Sortimentsaktion («20% auf alle Red Band-Produkte») |
| `preis` | Aktionspreis in CHF |
| `vergleich` | Normalpreis in CHF |
| `rabatt` | Rabatt in % (von Denner angegeben oder aus den Preisen berechnet) |
| `menge` | Packungsgrösse und Zusatzangaben, z. B. «6 x 75 cl» |
| `hinweis` | weitere Angaben, z. B. «½ PREIS», «20% ab 2 Stück», Weintyp und Land, Flaschenpreis, «Nur in der deutschen Schweiz erhältlich», «Wochenend-Highlight» |
| `gueltig_von`, `gueltig_bis` | Aktionszeitraum |
| `url` | Link zum Produkt |

## So funktioniert es

Die Aktionsseite von denner.ch enthält im HTML nur die ersten 24 Aktionen, die übrigen lädt sie beim Blättern nach. Das Skript fragt deshalb direkt die JSON-Schnittstelle ab, die auch die Webseite verwendet (`POST /nuxt-api/promotions`). Ein Token braucht es nicht.

1. Lädt alle Aktionen der Woche in Paketen zu 100 (`promoFlag` = `promo_current_week` bzw. `promo_next_week`).
2. Übernimmt aus der ersten Antwort zusätzlich die Wochenstart- und Wochenend-Highlights. Sie stehen nicht in der normalen Liste und werden im Hinweis markiert.
3. Liest pro Aktion Name, Aktions- und Normalpreis, Rabatt, Zeitraum und Kategorie. Weine haben statt einer Kategorie Weintyp und Land, sie kommen in die Kategorie «Wein/Champagner».
4. «Sonstiges» gibt es bei Denner zweimal, bei Food und bei Non-Food. Das Skript fragt deshalb die beiden Filter der Seite einzeln ab und nennt die Kategorien «Sonstiges (Food)» und «Sonstiges (Non-Food)».

Die robots.txt von denner.ch schliesst nur Warenkorb, Einkaufsliste und Login aus, die Aktionen nicht.

Wenn denner.ch die Schnittstelle ändert, findet das Skript nichts mehr oder bricht ab. Dann `--debug` verwenden und die gespeicherten JSON-Dateien ansehen.

## Tests

```bash
python -m pytest tests
```
