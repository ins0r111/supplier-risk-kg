"""
Answer the competency questions with SPARQL.

The graph is loaded together with the ontology and expanded with OWL 2 RL
reasoning first, so queries can use inferred facts such as the transitive
bill of materials (srk:hasComponent) and the order -> customer chain
(srk:orderedBy).

Usage:
    python scripts/query.py                  # all queries on clean data
    python scripts/query.py dirty            # all queries on dirty data
    python scripts/query.py clean cq1        # one query
"""

from __future__ import annotations

import sys
from pathlib import Path

import owlrl
from rdflib import Graph

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_graph import build  # noqa: E402

QUERIES = ROOT / "queries"
ONTOLOGY = ROOT / "ontology" / "supplier-risk.ttl"


def reasoned_graph(variant: str) -> Graph:
    g = Graph().parse(ONTOLOGY)
    g += build(variant)
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
    return g


def query_files(selector: str | None = None) -> list[Path]:
    files = sorted(QUERIES.glob("*.rq"))
    return [f for f in files if selector is None or f.name.startswith(selector)]


def run_query(g: Graph, path: Path) -> tuple[list[str], list[list[str]]]:
    result = g.query(path.read_text(encoding="utf-8"))
    columns = [str(v) for v in result.vars]
    rows = [["" if value is None else str(value) for value in row] for row in result]
    return columns, rows


def format_table(columns: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(c), *(len(r[i]) for r in rows)) if rows else len(c)
              for i, c in enumerate(columns)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths))
    return "\n".join([line(columns), line(["-" * w for w in widths])] + [line(r) for r in rows])


def main() -> None:
    variant = sys.argv[1] if len(sys.argv) > 1 else "clean"
    selector = sys.argv[2] if len(sys.argv) > 2 else None
    g = reasoned_graph(variant)
    for path in query_files(selector):
        question = path.read_text(encoding="utf-8").splitlines()[0].lstrip("# ")
        columns, rows = run_query(g, path)
        print(f"\n{question}\n")
        print(format_table(columns, rows))
        print(f"\n({len(rows)} rows)")


if __name__ == "__main__":
    main()
