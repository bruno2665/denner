import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from denner_aktionen import (
    aus_produkt, betrag, mehrdeutige_filter, sortiert, schreibe_csv, zeitraum, Aktion, OHNE_KATEGORIE, WEIN,
)


def item(price=0, **attrs):
    return {
        "sku": attrs.get("name", "x"),
        "price": price,
        "attributeInfo": [{"attributeName": k, "vals": [{"value": v, "label": ""}]} for k, v in attrs.items()],
    }


BANANEN = item(
    1.9,
    name="Bio Bananen",
    nameSubline="Herkunft siehe Etikette, per kg",
    priceFormatted="1.90",
    insteadPriceText="statt 2.75",
    discount_percent="30",
    discount_text="30%",
    promotionLabel="05.11.–11.11.2026",
    promotionFrom="1793849213",
    promotionTo="1794351600",
    itemUrl="/de/aktionen/bio-bananen~p1006255?variant=d12e",
    _tracking_item_category="",
    _tracking_item_category2="Früchte und Gemüse",
)


def test_produkt():
    a = aus_produkt(BANANEN)
    assert a.kategorie == "Früchte und Gemüse"
    assert a.name == "Bio Bananen"
    assert (a.preis, a.vergleich, a.rabatt) == (1.9, 2.75, 30)
    assert a.menge == "Herkunft siehe Etikette, per kg"
    assert a.hinweis == ""
    assert (a.gueltig_von, a.gueltig_bis) == ("2026-11-05", "2026-11-11")
    assert a.url == "https://www.denner.ch/de/aktionen/bio-bananen~p1006255?variant=d12e"


def test_wein():
    a = aus_produkt(item(
        29.85,
        name="Argento Cabernet Sauvignon ",
        nameSubline="Argentinien, Mendoza, 2025, 6\xa0x\xa075\xa0cl",
        priceFormatted="29.85",
        insteadPriceText="statt 59.70",
        discount_percent="50",
        discount_text="½ PREIS",
        priceSubText="Flasche: 5.– statt 9.95",
        _tracking_item_category="Argentinien",
        _tracking_item_category2="Rotwein / 2024",
    ))
    assert a.kategorie == WEIN
    assert a.name == "Argento Cabernet Sauvignon"
    assert (a.preis, a.vergleich, a.rabatt) == (29.85, 59.7, 50)
    assert a.menge == "Argentinien, Mendoza, 2025, 6 x 75 cl"
    assert a.hinweis == "½ PREIS; Rotwein, Argentinien; Flasche: 5.– statt 9.95"


def test_special_ohne_rabatt_und_kategorie():
    a = aus_produkt(item(4.9, name="Salami", priceFormatted="4.90", discount_text="SPECIAL", discount_percent="0"))
    assert (a.preis, a.vergleich, a.rabatt, a.hinweis) == (4.9, None, None, "SPECIAL")
    assert a.kategorie == OHNE_KATEGORIE
    assert a.url.endswith("/de/aktionen/aktuelle-aktionen")


def test_mengenrabatt_und_highlight():
    a = aus_produkt(item(
        1.5, name="Skyr", priceFormatted="1.50", insteadPriceText="statt 1.90", discount_percent="21",
        discount_text="20% <vertical>ab 2 Stück</vertical>", footnote="Nicht kumulierbar.",
        promotionLabel="Bis 11.11.2026", promotionFrom="1793849213",
    ), "Wochenstart-Highlight")
    assert (a.preis, a.vergleich, a.rabatt) == (1.5, 1.9, 21)
    assert a.hinweis == "20% ab 2 Stück; Nicht kumulierbar.; Wochenstart-Highlight"
    assert (a.gueltig_von, a.gueltig_bis) == ("2026-11-05", "2026-11-11")


def test_sortimentsaktion():
    a = aus_produkt(item(
        0, name="auf alle Red Band-Produkte", priceFormatted="auf alle Red Band-Produkte", discount_text="20%",
        isAssortmentPromotion="true", footnote="Auch auf bestehende Aktionspreise!\nNicht kumulierbar.",
        _tracking_item_category2="Schokolade/Süsses",
    ))
    assert a.name == "20% auf alle Red Band-Produkte"
    assert (a.preis, a.vergleich, a.rabatt) == (None, None, 20)
    assert a.hinweis == "Auch auf bestehende Aktionspreise! Nicht kumulierbar."


def test_ohne_name():
    assert aus_produkt(item(1.0, priceFormatted="1.00")) is None


def test_betrag():
    assert betrag("statt 2.75") == 2.75
    assert betrag("5.–") == 5.0
    assert betrag("1'299.00") == 1299.0
    assert betrag("auf alle Produkte") is None


def test_zeitraum_jahreswechsel():
    assert zeitraum({"promotionLabel": "29.12.–04.01.2027"}) == ("2026-12-29", "2027-01-04")
    assert zeitraum({"promotionFrom": "1793849213", "promotionTo": "1794351600"}) == ("2026-11-05", "2026-11-11")


def test_mehrdeutige_filter():
    facets = [
        {"attributeName": "type_food", "options": [{"value": "1", "label": "Sonstiges"}, {"value": "2", "label": "Bier"}]},
        {"attributeName": "type_non_food", "options": [{"value": "3", "label": "Sonstiges"}]},
        {"attributeName": "eco_labels", "options": [{"value": "4", "label": "Sonstiges"}]},
    ]
    assert mehrdeutige_filter(facets) == [
        ("type_food", "1", "Sonstiges (Food)"),
        ("type_non_food", "3", "Sonstiges (Non-Food)"),
    ]


def test_sortiert_und_csv(tmp_path):
    def akt(kat, name, rabatt):
        return Aktion(kat, name, 1.0, 2.0, rabatt, "", "", "", "", "")

    liste = sortiert([akt(OHNE_KATEGORIE, "z", 50), akt("Bier", "a", 20), akt("Bier", "b", 40), akt("Aperitif", "c", None)])
    assert [a.name for a in liste] == ["c", "b", "a", "z"]
    pfad = tmp_path / "t.csv"
    schreibe_csv(liste, str(pfad))
    zeilen = pfad.read_text(encoding="utf-8-sig").splitlines()
    assert zeilen[0] == "kategorie;name;preis;vergleich;rabatt;menge;hinweis;gueltig_von;gueltig_bis;url"
    assert zeilen[2] == "Bier;b;1.00;2.00;40;;;;;"
