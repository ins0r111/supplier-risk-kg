"""
Validate a knowledge graph against the SHACL shapes.

The graph is validated as ASSERTED, without OWL/RDFS inference. The ontology
is mixed in only so that sh:class can follow rdfs:subClassOf (a Product is
an Item). Inference must stay off: rdfs:range srk:Product on
srk:orderedProduct would otherwise *infer* that the unknown item P-999 is a
product, and the broken order would pass. OWL infers, SHACL checks.

Each violation is reported with the business key of the offending record
(e.g. ACC-1007), so the report can be read without knowing any IRIs.

Usage:
    python scripts/validate.py clean     # exit code 0 if the data conforms
    python scripts/validate.py dirty     # exit code 1, prints the violations
"""

from __future__ import annotations

import sys
from pathlib import Path

from pyshacl import validate
from rdflib import Graph, Namespace, RDF
from rdflib.namespace import PROV

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_graph import build  # noqa: E402

SH = Namespace("http://www.w3.org/ns/shacl#")
SRK = Namespace("https://example.org/supplier-risk-kg/ontology#")

SHAPES = ROOT / "shapes" / "supplier-risk-shapes.ttl"
ONTOLOGY = ROOT / "ontology" / "supplier-risk.ttl"


def business_key(data: Graph, node) -> str:
    """The ID a business user would recognise for a node."""
    key = data.value(node, SRK.identifier)
    if key is None:  # canonical customers: use the CRM record they come from
        source = data.value(node, PROV.wasDerivedFrom)
        key = data.value(source, SRK.identifier) if source is not None else None
    return str(key) if key is not None else str(node)


def run(data: Graph, inference: str = "none") -> tuple[bool, list[dict]]:
    conforms, report, _ = validate(
        data,
        shacl_graph=Graph().parse(SHAPES),
        ont_graph=Graph().parse(ONTOLOGY),
        inference=inference,
        advanced=True,  # enables SHACL-SPARQL constraints
        allow_warnings=False,
    )
    violations = []
    for result in report.subjects(RDF.type, SH.ValidationResult):
        violations.append({
            "record": business_key(data, report.value(result, SH.focusNode)),
            "rule": str(report.value(result, SH.resultMessage)),
        })
    violations.sort(key=lambda v: (v["record"], v["rule"]))
    return conforms, violations


def main() -> None:
    variants = sys.argv[1:] or ["clean", "dirty"]
    all_conform = True
    for variant in variants:
        conforms, violations = run(build(variant))
        all_conform &= conforms
        status = "conforms" if conforms else f"{len(violations)} violation(s)"
        print(f"{variant}: {status}")
        for v in violations:
            print(f"  {v['record']:<14} {v['rule']}")
    sys.exit(0 if all_conform else 1)


if __name__ == "__main__":
    main()
