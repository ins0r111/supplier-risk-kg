"""
Tests for the ontology itself, run on small hand-made examples.

They document what the reasoner is expected to do with the ontology:
infer the full bill of materials, connect orders to real customers, and
reject individuals that break a disjointness axiom.
"""

from pathlib import Path

import owlrl
import pytest
from rdflib import Graph, Literal, Namespace, RDF, URIRef

ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY = ROOT / "ontology" / "supplier-risk.ttl"

SRK = Namespace("https://example.org/supplier-risk-kg/ontology#")
ID = Namespace("https://example.org/supplier-risk-kg/id/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
OWL_RL_ERROR = URIRef("http://www.daml.org/2002/03/agents/agent-ont#error")


def load_ontology() -> Graph:
    return Graph().parse(ONTOLOGY)


def reason(triples) -> Graph:
    """Ontology + example triples, expanded with OWL 2 RL reasoning."""
    g = load_ontology()
    for t in triples:
        g.add(t)
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
    return g


def reasoner_errors(g: Graph) -> list[str]:
    return [str(msg) for msg in g.objects(None, OWL_RL_ERROR)]


def test_every_term_has_german_and_english_label():
    """The ontology doubles as a bilingual business glossary."""
    g = load_ontology()
    query = """
        PREFIX owl:  <http://www.w3.org/2002/07/owl#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        SELECT ?term ?lang WHERE {
          VALUES ?type { owl:Class owl:ObjectProperty owl:DatatypeProperty }
          VALUES ?lang { "de" "en" }
          ?term a ?type .
          FILTER (STRSTARTS(STR(?term), STR(<https://example.org/supplier-risk-kg/ontology#>)))
          FILTER NOT EXISTS {
            ?term skos:prefLabel ?label .
            FILTER (LANG(?label) = ?lang)
          }
        }
    """
    missing = [(str(r.term), str(r.lang)) for r in g.query(query)]
    assert missing == [], f"terms without prefLabel: {missing}"


def test_bill_of_materials_is_inferred_at_any_depth():
    """product -> assembly -> sub-assembly -> part: three direct links."""
    g = reason([
        (ID.P1, SRK.hasDirectComponent, ID.A1),
        (ID.A1, SRK.hasDirectComponent, ID.A2),
        (ID.A2, SRK.hasDirectComponent, ID.T1),
    ])
    assert (ID.P1, SRK.hasComponent, ID.T1) in g
    assert (ID.A1, SRK.hasComponent, ID.T1) in g
    assert (ID.T1, SRK.hasComponent, ID.P1) not in g


def test_order_is_connected_to_real_customer_via_property_chain():
    """order --placedBy--> ERP record --describes--> customer."""
    g = reason([
        (ID.O1, SRK.placedBy, ID.KD1),
        (ID.KD1, SRK.describes, ID.C1),
    ])
    assert (ID.O1, SRK.orderedBy, ID.C1) in g
    assert (ID.C1, RDF.type, SRK.Customer) in g  # from the range of orderedBy
    assert reasoner_errors(g) == []


@pytest.mark.parametrize("class_a, class_b", [
    (SRK.Product, SRK.Part),
    (SRK.Assembly, SRK.Part),
    (SRK.CrmAccount, SRK.Customer),  # a record is not the company it describes
])
def test_disjoint_classes_are_detected(class_a, class_b):
    g = reason([
        (ID.X, RDF.type, class_a),
        (ID.X, RDF.type, class_b),
    ])
    assert reasoner_errors(g), f"{class_a} and {class_b} should be disjoint"


def test_customer_can_also_be_supplier():
    """Customer and Supplier are intentionally not disjoint."""
    g = reason([
        (ID.X, RDF.type, SRK.Customer),
        (ID.X, RDF.type, SRK.Supplier),
        (ID.X, SRK.country, Literal("DE")),
    ])
    assert reasoner_errors(g) == []
