"""
Convert the CSV exports of CRM, ERP, PLM and SRM into one RDF graph.

What this script does beyond a 1:1 mapping:

* Customer identity. CRM is the master for customer data. For every CRM
  account one canonical srk:Customer is created. ERP customer records are
  linked to it via the VAT ID. An ERP record whose VAT ID matches no CRM
  account gets no srk:describes link; the SHACL shapes report it.
* Provenance. Every record, order, item and supplier states which source
  system it comes from (prov:wasAttributedTo); every customer states which
  CRM record it was derived from (prov:wasDerivedFrom).
* Only asserted facts are written. Inferred facts (full bill of materials,
  order -> customer) are left to the reasoner.

IRIs are deterministic, so building twice yields the identical file.
Canonical customers get opaque IRIs (UUIDv5 of the VAT ID), because a
real-world company should not be named after one system's internal key.

Usage:
    python scripts/build_graph.py            # builds clean and dirty
    python scripts/build_graph.py clean      # builds one variant
"""

from __future__ import annotations

import csv
import sys
import uuid
from decimal import Decimal
from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.namespace import PROV, XSD

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "graph"

SRK = Namespace("https://example.org/supplier-risk-kg/ontology#")
ID = Namespace("https://example.org/supplier-risk-kg/id/")

SYSTEMS = {
    "crm": "CRM (customer relationship management)",
    "erp": "ERP (enterprise resource planning)",
    "plm": "PLM (product lifecycle management)",
    "srm": "SRM (supplier relationship management)",
}

ITEM_CLASS = {"Product": SRK.Product, "Assembly": SRK.Assembly, "Part": SRK.Part}


def read(variant: str, table: str) -> list[dict]:
    with open(DATA / variant / f"{table}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def system(key: str) -> URIRef:
    return ID[f"system/{key}"]


def customer_iri(vat_id: str) -> URIRef:
    return ID[f"customer/{uuid.uuid5(uuid.NAMESPACE_URL, 'vat:' + vat_id)}"]


def add_record(g: Graph, iri: URIRef, cls: URIRef, identifier: str, source: str) -> None:
    g.add((iri, RDF.type, cls))
    g.add((iri, SRK.identifier, Literal(identifier)))
    g.add((iri, PROV.wasAttributedTo, system(source)))


def build(variant: str) -> Graph:
    g = Graph()
    g.bind("srk", SRK)
    g.bind("prov", PROV)
    # Short prefixes keep the Turtle output readable.
    for prefix, path in [("system", "system/"), ("crm", "crm/account/"),
                         ("customer", "customer/"), ("erp", "erp/customer/"),
                         ("order", "erp/order/"), ("item", "item/"),
                         ("bom", "bom/"), ("supplier", "supplier/")]:
        g.bind(prefix, ID[path])

    # Source systems
    for key, label in SYSTEMS.items():
        g.add((system(key), RDF.type, SRK.SourceSystem))
        g.add((system(key), RDFS.label, Literal(label, lang="en")))

    # CRM: accounts and the canonical customers derived from them
    customer_by_vat: dict[str, URIRef] = {}
    for row in read(variant, "crm_accounts"):
        record = ID[f"crm/account/{row['crm_id']}"]
        add_record(g, record, SRK.CrmAccount, row["crm_id"], "crm")
        g.add((record, SRK.recordName, Literal(row["name"])))
        g.add((record, SRK.vatId, Literal(row["vat_id"])))

        customer = customer_iri(row["vat_id"])
        customer_by_vat[row["vat_id"]] = customer
        g.add((record, SRK.describes, customer))
        g.add((customer, RDF.type, SRK.Customer))
        g.add((customer, RDFS.label, Literal(row["name"])))
        g.add((customer, SRK.segment, Literal(row["segment"])))
        g.add((customer, SRK.keyAccountManager, Literal(row["key_account_manager"])))
        g.add((customer, PROV.wasDerivedFrom, record))
        if row["country"]:  # a missing value stays missing; SHACL reports it
            g.add((customer, SRK.country, Literal(row["country"])))

    # ERP: customer records, matched to CRM customers via VAT ID
    for row in read(variant, "erp_customers"):
        record = ID[f"erp/customer/{row['erp_customer_id']}"]
        add_record(g, record, SRK.ErpCustomerRecord, row["erp_customer_id"], "erp")
        g.add((record, SRK.recordName, Literal(row["name"])))
        g.add((record, SRK.vatId, Literal(row["vat_id"])))
        g.add((record, SRK.paymentTermsDays,
               Literal(int(row["payment_terms_days"]), datatype=XSD.integer)))
        match = customer_by_vat.get(row["vat_id"])
        if match is not None:
            g.add((record, SRK.describes, match))

    # ERP: orders (they only know the ERP customer ID)
    for row in read(variant, "erp_orders"):
        order = ID[f"erp/order/{row['order_id']}"]
        add_record(g, order, SRK.Order, row["order_id"], "erp")
        g.add((order, SRK.placedBy, ID[f"erp/customer/{row['erp_customer_id']}"]))
        g.add((order, SRK.orderedProduct, ID[f"item/{row['product_id']}"]))
        g.add((order, SRK.quantity, Literal(int(row["quantity"]), datatype=XSD.integer)))
        g.add((order, SRK.unitPrice, Literal(Decimal(row["unit_price_eur"]), datatype=XSD.decimal)))
        g.add((order, SRK.orderDate, Literal(row["order_date"], datatype=XSD.date)))

    # Items and suppliers exist in only one system each, so they get no
    # separate record layer; provenance is attached to them directly.

    # PLM: items and bill of materials
    for row in read(variant, "items"):
        item = ID[f"item/{row['item_id']}"]
        add_record(g, item, ITEM_CLASS[row["item_type"]], row["item_id"], "plm")
        g.add((item, RDFS.label, Literal(row["name"], lang="en")))

    for row in read(variant, "bom"):
        parent, child = ID[f"item/{row['parent_id']}"], ID[f"item/{row['child_id']}"]
        line = ID[f"bom/{row['parent_id']}_{row['child_id']}"]
        g.add((line, RDF.type, SRK.BomLine))
        g.add((line, SRK.parentItem, parent))
        g.add((line, SRK.childItem, child))
        g.add((line, SRK.quantity, Literal(int(row["quantity"]), datatype=XSD.integer)))
        g.add((line, PROV.wasAttributedTo, system("plm")))
        g.add((parent, SRK.hasDirectComponent, child))

    # SRM: suppliers and sourcing
    for row in read(variant, "suppliers"):
        supplier = ID[f"supplier/{row['supplier_id']}"]
        add_record(g, supplier, SRK.Supplier, row["supplier_id"], "srm")
        g.add((supplier, RDFS.label, Literal(row["name"])))
        g.add((supplier, SRK.country, Literal(row["country"])))

    for row in read(variant, "supply"):
        g.add((ID[f"item/{row['part_id']}"], SRK.suppliedBy, ID[f"supplier/{row['supplier_id']}"]))

    return g


def main() -> None:
    variants = sys.argv[1:] or ["clean", "dirty"]
    OUT.mkdir(exist_ok=True)
    for variant in variants:
        g = build(variant)
        path = OUT / f"{variant}.ttl"
        g.serialize(path, format="turtle")
        print(f"{variant}: {len(g)} triples -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
