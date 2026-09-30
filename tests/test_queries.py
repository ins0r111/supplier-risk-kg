"""
Tests for the competency questions.

Where possible, the SPARQL answer is checked against an independent
calculation from the raw CSV files, so a wrong query cannot pass just
because it agrees with itself.
"""

import csv
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from rdflib import Graph

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_graph import build  # noqa: E402
from query import QUERIES, reasoned_graph, run_query  # noqa: E402


@pytest.fixture(scope="module")
def clean() -> Graph:
    return reasoned_graph("clean")


@pytest.fixture(scope="module")
def dirty() -> Graph:
    return reasoned_graph("dirty")


def answer(g: Graph, name: str) -> list[dict]:
    columns, rows = run_query(g, QUERIES / name)
    return [dict(zip(columns, row)) for row in rows]


def csv_rows(variant: str, table: str) -> list[dict]:
    with open(ROOT / "data" / variant / f"{table}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_all_queries_parse():
    g = Graph()
    for path in sorted(QUERIES.glob("*.rq")):
        g.query(path.read_text(encoding="utf-8"))


def test_cq1_affected_customers(clean):
    customers = {r["customer"] for r in answer(clean, "cq1_affected_customers.rq")}
    assert len(customers) == 13
    # They buy only wiper motors, which contain no control unit.
    assert "Oderbruch Nutzfahrzeuge AG" not in customers
    assert "Carpathia Motors S.R.L." not in customers


def test_cq1_same_answer_with_property_paths_and_no_reasoning(clean):
    """The reasoner and SPARQL property paths reach the same result."""
    query = """
        PREFIX srk:  <https://example.org/supplier-risk-kg/ontology#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?customer WHERE {
          ?part srk:suppliedBy <https://example.org/supplier-risk-kg/id/supplier/S3> .
          ?product a srk:Product ; srk:hasDirectComponent+ ?part .
          ?order srk:orderedProduct ?product ;
                 srk:placedBy/srk:describes ?c .
          ?c rdfs:label ?customer .
        }
    """
    asserted_only = build("clean")
    via_paths = {str(r.customer) for r in asserted_only.query(query)}
    via_reasoning = {r["customer"] for r in answer(clean, "cq1_affected_customers.rq")}
    assert via_paths == via_reasoning


def test_cq1_dirty_data_hides_an_affected_customer(dirty):
    """
    The VAT typo on KD-50012 breaks the ERP -> CRM link, so Moravia's
    orders reach no customer and Moravia drops out of the risk list:
    a data quality issue becomes a blind spot in the business answer.
    """
    customers = {r["customer"] for r in answer(dirty, "cq1_affected_customers.rq")}
    assert "Moravia Automotive a.s." not in customers
    assert len(customers) == 12


def test_cq2_revenue_at_risk_matches_independent_calculation(clean):
    # Independent check: every product except the wiper motor contains S3 parts.
    orders = csv_rows("clean", "erp_orders")
    value = lambda r: int(r["quantity"]) * Decimal(r["unit_price_eur"])
    affected = [r for r in orders if r["product_id"] != "P-300"]

    [row] = answer(clean, "cq2_revenue_at_risk.rq")
    assert int(row["affectedOrders"]) == len(affected)
    assert Decimal(row["affectedValue"]) == sum(map(value, affected))
    assert Decimal(row["totalValue"]) == sum(map(value, orders))


def test_cq3_single_source_parts(clean):
    rows = {r["part"]: r for r in answer(clean, "cq3_single_source_parts.rq")}
    supply = csv_rows("clean", "supply")
    suppliers_per_part = {}
    for r in supply:
        suppliers_per_part.setdefault(r["part_id"], set()).add(r["supplier_id"])
    single = {p for p, s in suppliers_per_part.items() if len(s) == 1}
    names = {r["item_id"]: r["name"] for r in csv_rows("clean", "items")}
    assert set(rows) == {names[p] for p in single}

    micro = rows["Microcontroller"]
    assert micro["soleSupplier"] == "Semicon Nordic AB"
    assert int(micro["productCount"]) == 4
    assert "Wiper motor" not in micro["products"]


def test_cq4_every_erp_customer_matched_in_clean_data(clean):
    rows = answer(clean, "cq4_customer_identity.rq")
    assert len(rows) == 15
    assert all(r["crmId"] for r in rows)
    assert {r["erpId"]: r["crmId"] for r in rows}["KD-50001"] == "ACC-1001"


def test_cq4_unmatched_record_is_listed_first(dirty):
    rows = answer(dirty, "cq4_customer_identity.rq")
    assert rows[0]["erpId"] == "KD-50012"
    assert rows[0]["crmId"] == ""
    assert all(r["crmId"] for r in rows[1:])
