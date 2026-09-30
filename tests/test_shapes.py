"""
Tests for the SHACL shapes.

The central contract: clean data conforms, and dirty data produces exactly
the violations listed in data/dirty/expected_violations.json, no more and
no fewer.
"""

import json
import sys
from pathlib import Path

from rdflib import Namespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_graph import build  # noqa: E402
from validate import run  # noqa: E402

ID = Namespace("https://example.org/supplier-risk-kg/id/")
SRK = Namespace("https://example.org/supplier-risk-kg/ontology#")


def as_set(violations):
    return {(v["record"], v["rule"]) for v in violations}


def test_clean_data_conforms():
    conforms, violations = run(build("clean"))
    assert conforms, violations


def test_dirty_data_yields_exactly_the_expected_violations():
    expected = json.loads((ROOT / "data" / "dirty" / "expected_violations.json").read_text())
    conforms, violations = run(build("dirty"))
    assert not conforms
    assert len(violations) == len(expected)
    assert as_set(violations) == {(e["record"], e["rule"]) for e in expected}


def test_inference_before_validation_hides_the_broken_order():
    """
    OWL infers, SHACL checks. With RDFS inference switched on, the range of
    srk:orderedProduct turns the unknown item P-999 into a srk:Product.
    The broken order then passes, and the error resurfaces as three
    confusing violations on a product nobody ever defined.
    """
    _, without = run(build("dirty"), inference="none")
    _, with_rdfs = run(build("dirty"), inference="rdfs")
    order_error = ("O-2026-0017", "Every order refers to an existing product.")
    assert order_error in as_set(without)
    assert order_error not in as_set(with_rdfs)
    assert any(r.endswith("item/P-999") for r, _ in as_set(with_rdfs))


def test_cycle_in_bill_of_materials_is_detected():
    g = build("clean")
    g.add((ID["item/A-31"], SRK.hasDirectComponent, ID["item/A-30"]))  # A-30 -> A-31 -> A-30
    conforms, violations = run(g)
    assert not conforms
    cyclic = {r for r, rule in as_set(violations) if "cycle" in rule}
    assert cyclic == {"A-30", "A-31"}


def test_part_with_components_is_rejected():
    g = build("clean")
    g.add((ID["item/T-10"], SRK.hasDirectComponent, ID["item/T-12"]))
    _, violations = run(g)
    assert ("T-10", "A part is purchased as a whole and has no components.") in as_set(violations)
