"""
Tests for the CSV -> RDF conversion.

They check that nothing is lost, that CRM and ERP customers are matched
exactly where the VAT IDs agree, that every fact carries its provenance,
and that the reasoner connects every order to a real customer.
"""

import sys
from pathlib import Path

import owlrl
import pytest
from rdflib import Graph, Namespace, RDF
from rdflib.namespace import PROV

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_graph import build  # noqa: E402

SRK = Namespace("https://example.org/supplier-risk-kg/ontology#")
ID = Namespace("https://example.org/supplier-risk-kg/id/")


@pytest.fixture(scope="module")
def clean() -> Graph:
    return build("clean")


@pytest.fixture(scope="module")
def dirty() -> Graph:
    return build("dirty")


def reasoned(g: Graph) -> Graph:
    full = Graph().parse(ROOT / "ontology" / "supplier-risk.ttl")
    full += g
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(full)
    return full


def count(g: Graph, cls) -> int:
    return len(set(g.subjects(RDF.type, cls)))


def test_nothing_is_lost(clean):
    assert count(clean, SRK.Customer) == 15
    assert count(clean, SRK.CrmAccount) == 15
    assert count(clean, SRK.ErpCustomerRecord) == 15
    assert count(clean, SRK.Order) == 40
    assert count(clean, SRK.Product) == 5
    assert count(clean, SRK.Assembly) == 5
    assert count(clean, SRK.Part) == 15
    assert count(clean, SRK.BomLine) == 33
    assert count(clean, SRK.Supplier) == 8


def test_every_erp_customer_is_matched_in_clean_data(clean):
    unmatched = [r for r in clean.subjects(RDF.type, SRK.ErpCustomerRecord)
                 if (r, SRK.describes, None) not in clean]
    assert unmatched == []


def test_crm_and_erp_record_point_to_the_same_customer(clean):
    crm = clean.value(ID["crm/account/ACC-1001"], SRK.describes)
    erp = clean.value(ID["erp/customer/KD-50001"], SRK.describes)
    assert crm is not None and crm == erp


def test_vat_typo_leaves_erp_record_unmatched(dirty):
    assert (ID["erp/customer/KD-50012"], SRK.describes, None) not in dirty


def test_every_record_order_and_item_has_its_source_system(clean):
    for cls in (SRK.CrmAccount, SRK.ErpCustomerRecord, SRK.Order,
                SRK.Product, SRK.Assembly, SRK.Part, SRK.BomLine, SRK.Supplier):
        for s in clean.subjects(RDF.type, cls):
            sources = list(clean.objects(s, PROV.wasAttributedTo))
            assert len(sources) == 1, f"{s} has {len(sources)} source systems"


def test_every_customer_is_derived_from_a_crm_record(clean):
    for customer in clean.subjects(RDF.type, SRK.Customer):
        source = clean.value(customer, PROV.wasDerivedFrom)
        assert (source, RDF.type, SRK.CrmAccount) in clean


def test_build_is_deterministic():
    first = build("clean").serialize(format="turtle")
    second = build("clean").serialize(format="turtle")
    assert first == second


def test_reasoner_connects_every_order_to_a_customer(clean):
    g = reasoned(clean)
    orders = set(g.subjects(RDF.type, SRK.Order))
    assert all((o, SRK.orderedBy, None) in g for o in orders)


def test_orders_of_unmatched_erp_record_have_no_customer(dirty):
    g = reasoned(dirty)
    orders = set(g.subjects(SRK.placedBy, ID["erp/customer/KD-50012"]))
    assert orders, "KD-50012 should have orders"
    assert all((o, SRK.orderedBy, None) not in g for o in orders)
