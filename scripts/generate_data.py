"""
Generate the synthetic source data for supplier-risk-kg.

The scenario: a fictional automotive supplier ("Bodensee Antriebstechnik GmbH")
builds electric drives for car makers. Its data lives in separate systems that
do not share identifiers:

    CRM   -> crm_accounts.csv          (customers as "accounts")
    ERP   -> erp_customers.csv         (customers as "Auftraggeber", other IDs)
             erp_orders.csv
    PLM   -> items.csv, bom.csv        (products, assemblies, parts)
    SRM   -> suppliers.csv, supply.csv (who supplies which part)

The only shared key between CRM and ERP is the VAT ID, and the ERP spells
customer names differently. Linking the two is part of the exercise.

Two datasets are written:

    data/clean/  consistent data; must pass all SHACL shapes
    data/dirty/  the same data with a small set of deliberately injected
                 errors; each error is listed in expected_violations.json so
                 the test suite can check that validation finds exactly these.

All company names and VAT IDs are fictional. A fixed random seed makes the
output fully reproducible.

Usage:
    python scripts/generate_data.py
"""

from __future__ import annotations

import copy
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 42
N_ORDERS = 40
ROOT = Path(__file__).resolve().parent.parent
OUT_CLEAN = ROOT / "data" / "clean"
OUT_DIRTY = ROOT / "data" / "dirty"

# --------------------------------------------------------------------------
# Master data (hand-written so the story stays readable)
# --------------------------------------------------------------------------

# item_id, name, item_type
ITEMS = [
    # Products (what customers order)
    ("P-100", "Window lift drive", "Product"),
    ("P-200", "Seat adjustment motor", "Product"),
    ("P-300", "Wiper motor", "Product"),
    ("P-400", "Sunroof drive", "Product"),
    ("P-500", "Power tailgate drive", "Product"),
    # Assemblies
    ("A-10", "Motor unit", "Assembly"),
    ("A-20", "Gear unit", "Assembly"),
    ("A-30", "Electronic control unit", "Assembly"),
    ("A-31", "PCB assembly", "Assembly"),
    ("A-40", "Sealing kit", "Assembly"),
    # Parts (what suppliers deliver)
    ("T-01", "Copper winding", "Part"),
    ("T-02", "NdFeB magnet", "Part"),
    ("T-03", "Ball bearing", "Part"),
    ("T-04", "Motor housing", "Part"),
    ("T-05", "Worm gear", "Part"),
    ("T-06", "Spur gear", "Part"),
    ("T-07", "Gear housing", "Part"),
    ("T-08", "ECU housing", "Part"),
    ("T-09", "Connector", "Part"),
    ("T-10", "Microcontroller", "Part"),
    ("T-11", "Hall sensor", "Part"),
    ("T-12", "Bare PCB", "Part"),
    ("T-13", "Sealing ring", "Part"),
    ("T-14", "Screw set", "Part"),
    ("T-15", "Spindle", "Part"),
]

# parent_id, child_id, quantity
# Depth differs on purpose: P-100 -> A-30 -> A-31 -> T-10 is three levels,
# P-500 -> T-15 is one. Queries must handle both.
BOM = [
    # Products
    ("P-100", "A-10", 1), ("P-100", "A-20", 1), ("P-100", "A-30", 1), ("P-100", "A-40", 1),
    ("P-200", "A-10", 1), ("P-200", "A-20", 1), ("P-200", "A-30", 1),
    ("P-300", "A-10", 1), ("P-300", "A-20", 1), ("P-300", "A-40", 1),  # no ECU
    ("P-400", "A-10", 1), ("P-400", "A-20", 1), ("P-400", "A-30", 1), ("P-400", "A-40", 1),
    ("P-500", "A-10", 1), ("P-500", "A-30", 1), ("P-500", "A-40", 1), ("P-500", "T-15", 2),
    # Assemblies
    ("A-10", "T-01", 1), ("A-10", "T-02", 2), ("A-10", "T-03", 2), ("A-10", "T-04", 1),
    ("A-20", "T-05", 1), ("A-20", "T-06", 2), ("A-20", "T-07", 1),
    ("A-30", "A-31", 1), ("A-30", "T-08", 1), ("A-30", "T-09", 1),
    ("A-31", "T-10", 1), ("A-31", "T-11", 2), ("A-31", "T-12", 1),
    ("A-40", "T-13", 2), ("A-40", "T-14", 1),
]

# supplier_id, name, country (ISO 3166-1 alpha-2)
SUPPLIERS = [
    ("S1", "Kupferwerk Hansa GmbH", "DE"),
    ("S2", "Far East Magnetics Co., Ltd.", "CN"),
    ("S3", "Semicon Nordic AB", "SE"),
    ("S4", "Waelzlager Franken GmbH", "DE"),
    ("S5", "Praezisionsguss Alb GmbH", "DE"),
    ("S6", "Getriebeteile Ostalb GmbH", "DE"),
    ("S7", "Sensorika Brno s.r.o.", "CZ"),
    ("S8", "Dichtungstechnik Bodensee GmbH", "DE"),
]

# part_id, supplier_id  (many-to-many; one row per sourcing relation)
# T-10 (microcontroller) is single-sourced from S3: the central risk story.
SUPPLY = [
    ("T-01", "S1"),
    ("T-02", "S2"),
    ("T-03", "S4"), ("T-03", "S6"),
    ("T-04", "S5"),
    ("T-05", "S6"), ("T-05", "S5"),
    ("T-06", "S6"),
    ("T-07", "S5"),
    ("T-08", "S5"), ("T-08", "S7"),
    ("T-09", "S7"), ("T-09", "S3"),
    ("T-10", "S3"),
    ("T-11", "S3"), ("T-11", "S7"),
    ("T-12", "S7"),
    ("T-13", "S8"),
    ("T-14", "S8"), ("T-14", "S4"),
    ("T-15", "S6"),
]

# name, country, segment
CUSTOMERS = [
    ("Rheinstahl Fahrzeugbau AG", "DE", "OEM"),
    ("Voltaris Mobility GmbH", "DE", "OEM"),
    ("Hansekraft Automobile SE", "DE", "OEM"),
    ("Isartal Motorenwerke AG", "DE", "OEM"),
    ("Moselwerk Fahrzeuge GmbH", "DE", "Tier 1"),
    ("Oderbruch Nutzfahrzeuge AG", "DE", "Commercial vehicles"),
    ("Lechfeld E-Mobil GmbH", "DE", "OEM"),
    ("Danubia Fahrzeugtechnik GmbH", "AT", "Tier 1"),
    ("Loire Mobilite SAS", "FR", "OEM"),
    ("Ebro Vehiculos S.L.", "ES", "OEM"),
    ("Padania Automotive S.p.A.", "IT", "OEM"),
    ("Moravia Automotive a.s.", "CZ", "Tier 1"),
    ("Vistula Auto S.A.", "PL", "OEM"),
    ("Carpathia Motors S.R.L.", "RO", "Commercial vehicles"),
    ("Nordkap Electric Vehicles AS", "NO", "OEM"),
]

# One key account manager per account; every name is unique.
KEY_ACCOUNT_MANAGERS = [
    "J. Keller", "A. Brandt", "M. Yilmaz", "S. Novak", "L. Hoffmann",
    "K. Petrova", "T. Schneider", "E. Rossi", "F. Dubois", "N. Kowalski",
    "C. Fischer", "D. Horvat", "R. Lindqvist", "P. Martins", "H. Wagner",
]

# The two commercial vehicle makers buy only wiper motors. P-300 contains no
# electronic control unit, so these are the customers NOT affected when S3
# (the only microcontroller supplier) fails. Without them every customer
# would be affected and the risk question would have a trivial answer.
PRODUCT_PORTFOLIO = {
    "Oderbruch Nutzfahrzeuge AG": ["P-300"],
    "Carpathia Motors S.R.L.": ["P-300"],
}

UNIT_PRICE_EUR = {
    "P-100": 38.50,
    "P-200": 44.90,
    "P-300": 27.80,
    "P-400": 61.20,
    "P-500": 73.40,
}

LEGAL_FORMS = ["GmbH", "AG", "SE", "SAS", "S.L.", "S.p.A.", "a.s.", "S.A.", "S.R.L.", "AS"]


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------

def fake_vat_id(country: str, rng: random.Random) -> str:
    """Fictional VAT ID: country prefix + 9 digits (format only, not valid)."""
    return f"{country}{rng.randrange(10**8, 10**9)}"


def erp_spelling(name: str) -> str:
    """Mimic how an ERP stores names: uppercase, legal form stripped."""
    parts = [p for p in name.split() if p not in LEGAL_FORMS]
    return " ".join(parts).upper()


def build_clean(rng: random.Random) -> dict[str, list[dict]]:
    assert len(KEY_ACCOUNT_MANAGERS) == len(set(KEY_ACCOUNT_MANAGERS)) == len(CUSTOMERS)
    crm_accounts, erp_customers = [], []
    for i, (name, country, segment) in enumerate(CUSTOMERS):
        vat = fake_vat_id(country, rng)
        crm_accounts.append({
            "crm_id": f"ACC-{1001 + i}",
            "name": name,
            "country": country,
            "segment": segment,
            "vat_id": vat,
            "key_account_manager": KEY_ACCOUNT_MANAGERS[i],
        })
        erp_customers.append({
            "erp_customer_id": f"KD-{50001 + i}",
            "name": erp_spelling(name),
            "vat_id": vat,
            "payment_terms_days": rng.choice([30, 45, 60, 90]),
        })

    start = date(2026, 1, 1)
    erp_orders = []
    for n in range(1, N_ORDERS + 1):
        i = rng.randrange(len(erp_customers))
        customer = erp_customers[i]
        portfolio = PRODUCT_PORTFOLIO.get(CUSTOMERS[i][0], list(UNIT_PRICE_EUR))
        product = rng.choice(portfolio)
        erp_orders.append({
            "order_id": f"O-2026-{n:04d}",
            "erp_customer_id": customer["erp_customer_id"],
            "product_id": product,
            "quantity": rng.randrange(100, 5001, 50),
            "unit_price_eur": f"{UNIT_PRICE_EUR[product]:.2f}",
            "order_date": (start + timedelta(days=rng.randrange(0, 272))).isoformat(),
        })
    erp_orders.sort(key=lambda o: o["order_date"])
    for n, order in enumerate(erp_orders, start=1):  # IDs follow date order
        order["order_id"] = f"O-2026-{n:04d}"

    return {
        "crm_accounts": crm_accounts,
        "erp_customers": erp_customers,
        "erp_orders": erp_orders,
        "items": [{"item_id": i, "name": n, "item_type": t} for i, n, t in ITEMS],
        "bom": [{"parent_id": p, "child_id": c, "quantity": q} for p, c, q in BOM],
        "suppliers": [{"supplier_id": s, "name": n, "country": c} for s, n, c in SUPPLIERS],
        "supply": [{"part_id": p, "supplier_id": s} for p, s in SUPPLY],
    }


def inject_errors(clean: dict[str, list[dict]]) -> tuple[dict, list[dict]]:
    """Copy the clean data and inject a fixed, documented set of errors."""
    dirty = copy.deepcopy(clean)
    errors = []

    def find(table: str, key: str, value: str) -> dict:
        return next(r for r in dirty[table] if r[key] == value)

    # 1. CRM account without a country
    acc = find("crm_accounts", "crm_id", "ACC-1007")
    acc["country"] = ""
    errors.append({"file": "crm_accounts.csv", "record": "ACC-1007",
                   "rule": "Every customer has exactly one country."})

    # 2. Order referencing a product that does not exist
    order = find("erp_orders", "order_id", "O-2026-0017")
    order["product_id"] = "P-999"
    errors.append({"file": "erp_orders.csv", "record": "O-2026-0017",
                   "rule": "Every order refers to an existing product."})

    # 3. Order with a negative quantity
    order = find("erp_orders", "order_id", "O-2026-0023")
    order["quantity"] = -250
    errors.append({"file": "erp_orders.csv", "record": "O-2026-0023",
                   "rule": "Order quantity is a positive integer."})

    # 4. Part without any supplier
    dirty["supply"] = [r for r in dirty["supply"] if r["part_id"] != "T-13"]
    errors.append({"file": "supply.csv", "record": "T-13",
                   "rule": "Every part has at least one supplier."})

    # 5. ERP customer whose VAT ID has a typo: cannot be matched to the CRM
    cust = find("erp_customers", "erp_customer_id", "KD-50012")
    vat = cust["vat_id"]
    cust["vat_id"] = vat[:-2] + vat[-1] + vat[-2]  # swap last two digits
    errors.append({"file": "erp_customers.csv", "record": "KD-50012",
                   "rule": "Every ERP customer matches exactly one CRM account via VAT ID."})

    return dirty, errors


def write_dataset(data: dict[str, list[dict]], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for table, rows in data.items():
        with open(out / f"{table}.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


def main() -> None:
    rng = random.Random(SEED)
    clean = build_clean(rng)
    dirty, errors = inject_errors(clean)

    write_dataset(clean, OUT_CLEAN)
    write_dataset(dirty, OUT_DIRTY)
    with open(OUT_DIRTY / "expected_violations.json", "w", encoding="utf-8") as f:
        json.dump(errors, f, indent=2, ensure_ascii=False)

    print(f"clean data -> {OUT_CLEAN.relative_to(ROOT)}")
    print(f"dirty data -> {OUT_DIRTY.relative_to(ROOT)} ({len(errors)} injected errors)")


if __name__ == "__main__":
    main()
