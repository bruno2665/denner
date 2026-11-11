#!/usr/bin/env python3
"""Liest die Wochenaktionen von denner.ch und gibt sie nach Kategorien als Tabelle und CSV aus.

Beispiele:
    python denner_aktionen.py                          # alle Aktionen -> denner_aktionen.csv
    python denner_aktionen.py --min-rabatt 30          # nur Rabatt >= 30 %
    python denner_aktionen.py --kategorie Wein         # nur Kategorien, die "Wein" enthalten
    python denner_aktionen.py --woche naechste --csv naechste_woche.csv

Die Aktionsseite von denner.ch (https://www.denner.ch/de/aktionen/aktuelle-aktionen) zeigt im
HTML nur die ersten 24 Aktionen, die übrigen lädt sie beim Blättern nach. Das Skript fragt
deshalb dieselbe JSON-Schnittstelle ab wie die Webseite (keine KI, Preise exakt):

  POST /nuxt-api/promotions   {"promoFlag": "promo_current_week", "page": 1, "hitsPerPage": 100, ...}
    -> items       alle Aktionen der Woche (Name, Preise, Rabatt, Zeitraum, Kategorie)
    -> highlights  zusätzliche Wochenstart- und Wochenend-Aktionen
    -> facets      Kategorienfilter der Seite (Getränke, Food, Non-Food)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import time
from dataclasses import dataclass, asdict, fields

import requests

BASE = "https://www.denner.ch"
API = BASE + "/nuxt-api/promotions"
SEITE = BASE + "/de/aktionen/aktuelle-aktionen"

WOCHEN = {"aktuell": "promo_current_week", "naechste": "promo_next_week"}
PRO_SEITE = 100  # mehr liefert die Schnittstelle nicht pro Abfrage
OHNE_KATEGORIE = "Ohne Kategorie"
WEIN = "Wein/Champagner"

# Kategorienfilter der Seite; "Sonstiges" gibt es bei Food und bei Non-Food.
FILTER_GRUPPEN = {"type_beverages": "Getränke", "type_food": "Food", "type_non_food": "Non-Food"}
HIGHLIGHTS = {
    "start_of_the_week_highlight": "Wochenstart-Highlight",
    "weekend_highlight": "Wochenend-Highlight",
    "weekend_highlight_next_week": "Wochenend-Highlight",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-CH,de;q=0.9",
    "Origin": BASE,
    "Referer": SEITE,
}

BETRAG = re.compile(r"(\d{1,3}(?:['’]\d{3})*)[.,](\d{2}|[–—-])")
PROZENT = re.compile(r"(\d{1,2})\s?%")
NUR_PROZENT = re.compile(r"-?\d{1,2}\s?%")
ZEITRAUM = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})?\s*[–—-]\s*(\d{1,2})\.(\d{1,2})\.(\d{4})")
BIS = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


@dataclass
class Aktion:
    kategorie: str
    name: str
    preis: float | None
    vergleich: float | None
    rabatt: int | None
    menge: str
    hinweis: str
    gueltig_von: str
    gueltig_bis: str
    url: str


def clean(s: object) -> str:
    """Entfernt HTML-Tags und überflüssige Leerzeichen."""
    return " ".join(re.sub(r"<[^>]+>", " ", str(s or "")).split())


def betrag(s: object) -> float | None:
    """Liest den ersten Frankenbetrag aus einem Text: "statt 2.75" -> 2.75, "5.–" -> 5.0."""
    m = BETRAG.search(str(s or ""))
    if not m:
        return None
    rappen = m.group(2) if m.group(2).isdigit() else "00"
    return float(re.sub(r"\D", "", m.group(1)) + "." + rappen)


def attribute(item: dict) -> dict[str, str]:
    """Macht aus der Attributliste eines Produkts ein einfaches Wörterbuch (erster Wert je Attribut)."""
    out = {}
    for a in item.get("attributeInfo") or []:
        if isinstance(a, dict) and a.get("attributeName"):
            vals = a.get("vals") or [{}]
            out[a["attributeName"]] = str((vals[0] or {}).get("value") or "")
    return out


def tag_aus_zeitstempel(ts: str) -> str:
    """Unix-Zeit -> Datum in der Schweiz (Aktionen enden um Mitternacht Schweizer Zeit)."""
    try:
        t = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc) + dt.timedelta(hours=2)
    except (ValueError, OverflowError, OSError):
        return ""
    return t.date().isoformat()


def zeitraum(a: dict[str, str]) -> tuple[str, str]:
    """Liest den Aktionszeitraum aus dem Text ("05.11.–11.11.2026", "Bis 11.11.2026"), sonst aus den Zeitstempeln."""
    von, bis = tag_aus_zeitstempel(a.get("promotionFrom", "")), tag_aus_zeitstempel(a.get("promotionTo", ""))
    text = a.get("promotionLabel") or a.get("promotionLabelPublication") or ""
    try:
        m = ZEITRAUM.search(text)
        if m:
            t1, m1, j1, t2, m2, j2 = (int(x) if x else None for x in m.groups())
            if j1 is None:  # Jahreswechsel: 29.12.–04.01.2027
                j1 = j2 - 1 if m1 > m2 else j2
            return dt.date(j1, m1, t1).isoformat(), dt.date(j2, m2, t2).isoformat()
        m = BIS.search(text)
        if m:
            bis = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        pass
    return von, bis


def berechne_rabatt(preis: float | None, vergleich: float | None) -> int | None:
    if preis and vergleich and vergleich > preis:
        return round((1 - preis / vergleich) * 100)
    return None


def kategorie_von(a: dict[str, str]) -> str:
    """Bei Wein steht im Feld category2 der Weintyp und in category das Land, sonst die Kategorie."""
    if a.get("_tracking_item_category"):
        return WEIN
    return clean(a.get("_tracking_item_category2")) or OHNE_KATEGORIE


def aus_produkt(item: dict, highlight: str = "") -> Aktion | None:
    """Wandelt einen Eintrag der Schnittstelle in eine Aktion um."""
    a = attribute(item)
    name = clean(a.get("name"))
    if not name:
        return None
    stopper = clean(a.get("discount_text"))  # "30%", "½ PREIS", "SPECIAL", "20% ab 2 Stück"
    sortiment = a.get("isAssortmentPromotion") == "true"  # "20% auf alle Red Band-Produkte"

    preis = None if sortiment else betrag(a.get("priceFormatted"))
    if preis is None and not sortiment and isinstance(item.get("price"), (int, float)) and item["price"] > 0:
        preis = round(float(item["price"]), 2)
    vergleich = betrag(a.get("insteadPriceText"))
    if vergleich is not None and preis is not None and vergleich <= preis:
        vergleich = None

    rabatt = int(a["discount_percent"]) if a.get("discount_percent", "").isdigit() and a["discount_percent"] != "0" else None
    if rabatt is None:
        m = PROZENT.search(stopper)
        rabatt = int(m.group(1)) if m else berechne_rabatt(preis, vergleich)

    hinweise = []
    if sortiment:
        name = f"{stopper} {name}".strip()
    elif stopper and not NUR_PROZENT.fullmatch(stopper):
        hinweise.append(stopper)
    if a.get("_tracking_item_category"):  # Wein: "Rotwein / 2024" + Land; der Jahrgang steht verlässlicher in der Menge
        typ = clean(a.get("_tracking_item_category2")).split("/")[0].strip()
        hinweise.append(", ".join(x for x in (typ, clean(a["_tracking_item_category"])) if x))
    hinweise += [clean(a.get("priceSubText")), clean(a.get("footnote")), highlight]

    von, bis = zeitraum(a)
    return Aktion(
        kategorie=kategorie_von(a),
        name=name,
        preis=preis,
        vergleich=vergleich,
        rabatt=rabatt,
        menge=clean(a.get("nameSubline")),
        hinweis="; ".join(h for h in hinweise if h),
        gueltig_von=von,
        gueltig_bis=bis,
        url=BASE + a["itemUrl"] if a.get("itemUrl", "").startswith("/") else SEITE,
    )


def mehrdeutige_filter(facets: list) -> list[tuple[str, str, str]]:
    """Kategorien, die in mehreren Filtergruppen vorkommen (z. B. "Sonstiges" bei Food und Non-Food).
    Ergebnis: (Filtername, Filterwert, eindeutiger Name wie "Sonstiges (Non-Food)")."""
    optionen = [
        (f["attributeName"], str(o.get("value")), clean(o.get("label")))
        for f in facets or []
        if isinstance(f, dict) and f.get("attributeName") in FILTER_GRUPPEN
        for o in f.get("options") or []
        if isinstance(o, dict) and o.get("label")
    ]
    labels = [label for _, _, label in optionen]
    return [(n, v, f"{label} ({FILTER_GRUPPEN[n]})") for n, v, label in optionen if labels.count(label) > 1]


class Denner:
    def __init__(self, woche: str, sprache: str, pause: float, debug: bool):
        self.flag, self.sprache, self.pause, self.debug = WOCHEN[woche], sprache, pause, debug
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.n = 0

    def seite(self, nr: int, filter_name: str | None = None, filter_wert: str | None = None) -> dict:
        body = {
            "lang": self.sprache,
            "promoFlag": self.flag,
            "facetName": filter_name,
            "facetValue": filter_wert,
            "page": nr,
            "hitsPerPage": PRO_SEITE,
            "sort": None,
            "includeHighlights": nr == 1 and filter_name is None,
        }
        r = self.s.post(API, json=body, timeout=40)
        r.raise_for_status()
        data = r.json()
        if self.debug:
            self.n += 1
            with open(f"debug_antwort_{self.n}.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        time.sleep(self.pause)
        return data if isinstance(data, dict) else {}

    def alle(self, filter_name: str | None = None, filter_wert: str | None = None) -> tuple[list[dict], dict]:
        """Blättert durch alle Seiten; gibt die Einträge und die erste Antwort (Filter, Highlights) zurück."""
        erste = self.seite(1, filter_name, filter_wert)
        items = list(erste.get("items") or [])
        seiten = int((erste.get("stats") or {}).get("totalPages") or 1)
        for nr in range(2, seiten + 1):
            try:
                items += self.seite(nr, filter_name, filter_wert).get("items") or []
            except (requests.RequestException, ValueError) as e:
                print(f"Hinweis: Seite {nr} nicht lesbar: {e}", file=sys.stderr)
        return [i for i in items if isinstance(i, dict)], erste


def scrape(woche: str, sprache: str, pause: float, debug: bool) -> list[Aktion]:
    d = Denner(woche, sprache, pause, debug)
    try:
        items, erste = d.alle()
    except (requests.RequestException, ValueError) as e:
        sys.exit(f"Fehler: denner.ch nicht lesbar: {e}")

    # Eindeutige Namen für Kategorien wie "Sonstiges": Produkte je Filter abfragen.
    eindeutig: dict[str, str] = {}
    for name, wert, kategorie in mehrdeutige_filter(erste.get("facets")):
        try:
            for it in d.alle(name, wert)[0]:
                eindeutig[it.get("sku")] = kategorie
        except (requests.RequestException, ValueError) as e:
            print(f"Hinweis: Filter '{kategorie}' nicht lesbar: {e}", file=sys.stderr)

    aktionen, gesehen = [], set()
    quellen = [(items, "")] + [
        (h.get("items") or [], HIGHLIGHTS.get(h.get("flag"), "Highlight"))
        for h in erste.get("highlights") or []
        if isinstance(h, dict)
    ]
    for liste, highlight in quellen:
        for it in liste:
            if not isinstance(it, dict) or it.get("sku") in gesehen:
                continue
            gesehen.add(it.get("sku"))
            a = aus_produkt(it, highlight)
            if a:
                a.kategorie = eindeutig.get(it.get("sku"), a.kategorie)
                aktionen.append(a)
    print(f"{len(items)} Aktionen und {len(aktionen) - len(items)} Highlights gefunden", file=sys.stderr)
    return aktionen


def sortiert(aktionen: list[Aktion]) -> list[Aktion]:
    """Nach Kategorie (alphabetisch, "Ohne Kategorie" am Schluss), innerhalb nach Rabatt absteigend."""
    return sorted(
        aktionen,
        key=lambda a: (a.kategorie == OHNE_KATEGORIE, a.kategorie.lower(), -(a.rabatt or 0), a.name.lower()),
    )


def fmt(x: float | None) -> str:
    return f"{x:.2f}" if x is not None else ""


def schreibe_csv(aktionen: list[Aktion], pfad: str) -> None:
    with open(pfad, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[x.name for x in fields(Aktion)], delimiter=";")
        w.writeheader()
        for a in aktionen:
            w.writerow({**asdict(a), "preis": fmt(a.preis), "vergleich": fmt(a.vergleich)})


def main() -> None:
    p = argparse.ArgumentParser(description="Wochenaktionen von denner.ch nach Kategorien auslesen")
    p.add_argument("--csv", default="denner_aktionen.csv", help="CSV-Datei (Standard: denner_aktionen.csv)")
    p.add_argument("--min-rabatt", type=int, default=0, help="nur Aktionen mit mindestens N %% Rabatt")
    p.add_argument("--kategorie", help="nur Kategorien, deren Name diesen Text enthält")
    p.add_argument("--woche", choices=list(WOCHEN), default="aktuell", help="aktuelle oder nächste Woche (Standard: aktuell)")
    p.add_argument("--sprache", choices=["de", "fr", "it"], default="de", help="Sprache der Texte (Standard: de)")
    p.add_argument("--pause", type=float, default=1.0, help="Sekunden zwischen Abfragen")
    p.add_argument("--debug", action="store_true", help="jede JSON-Antwort als debug_antwort_N.json speichern")
    args = p.parse_args()

    for strom in (sys.stdout, sys.stderr):  # Windows-Konsole: Umlaute und "½" nicht abstürzen lassen
        if hasattr(strom, "reconfigure"):
            strom.reconfigure(errors="replace")

    aktionen = scrape(args.woche, args.sprache, args.pause, args.debug)
    if args.min_rabatt > 0:
        aktionen = [a for a in aktionen if (a.rabatt or 0) >= args.min_rabatt]
    if args.kategorie:
        aktionen = [a for a in aktionen if args.kategorie.lower() in a.kategorie.lower()]
    aktionen = sortiert(aktionen)

    kategorie = None
    for a in aktionen:
        if a.kategorie != kategorie:
            kategorie = a.kategorie
            anzahl = sum(1 for x in aktionen if x.kategorie == kategorie)
            print(f"\n== {kategorie} ({anzahl}) ==")
            print(f"{'Rabatt':>6}  {'Preis':>8}  {'statt':>8}  Produkt")
        rab = f"-{a.rabatt}%" if a.rabatt else ""
        print(f"{rab:>6}  {fmt(a.preis):>8}  {fmt(a.vergleich):>8}  {a.name}")
    print(f"\n{len(aktionen)} Aktionen in {len({a.kategorie for a in aktionen})} Kategorien", file=sys.stderr)

    schreibe_csv(aktionen, args.csv)
    print(f"CSV gespeichert: {args.csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
