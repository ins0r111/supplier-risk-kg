# supplier-risk-kg

**A hands-on learning path for knowledge graphs with OWL, SHACL and SPARQL,
built around one business question:**

> **Which customers are affected if supplier X fails?**

The answer is spread across four systems that share no common customer ID.
It requires following a chain that no single system holds (supplier → part →
assembly → product → order → customer) through a bill of materials of varying
depth. This is exactly where plain vector-based RAG struggles and an
ontology-backed knowledge graph does not.

Everything runs locally in a few seconds, is fully reproducible and is
covered by tests.

## Who this is for

You know some Python and SQL and want to understand how knowledge graphs,
ontologies and data validation work in practice, on a realistic enterprise
problem rather than on pizzas or wine. No prior semantic web experience is
needed. Plan for one to two days if you do the exercises.

**You will learn to:**

- turn tables from several systems into an RDF graph with provenance
- model a domain in OWL, including a bilingual business glossary with SKOS
- let a reasoner infer new facts (transitivity, property chains)
- validate data quality with SHACL, and understand why OWL is not a validator
- answer business questions in SPARQL, including multi-hop questions
- make the whole pipeline reproducible and tested

## Quick start

```bash
git clone <this repository>
cd supplier-risk-kg
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/generate_data.py   # 1. CSV source data (clean and dirty)
python scripts/build_graph.py     # 2. RDF graphs in graph/
python scripts/validate.py clean  # 3. SHACL validation
python scripts/query.py           # 4. answer the competency questions
pytest                            # 29 tests
```

## The scenario

*Bodensee Antriebstechnik GmbH* (fictional) builds electric drives for car
makers: window lifts, seat motors, wiper motors, sunroof and tailgate drives.
Its data lives in four systems:

| System | What it is | Files | Holds |
|---|---|---|---|
| CRM | Customer relationship management (sales) | `crm_accounts.csv` | Customers as "accounts": country, segment, key account manager |
| ERP | Enterprise resource planning (orders, invoicing) | `erp_customers.csv`, `erp_orders.csv` | Customers as "Debitoren" with their own IDs and spelling; orders |
| PLM | Product lifecycle management | `items.csv`, `bom.csv` | Products, assemblies, parts, bill of materials |
| SRM | Supplier relationship management | `suppliers.csv`, `supply.csv` | Suppliers and the parts they deliver |

CRM and ERP spell names differently (*Rheinstahl Fahrzeugbau AG* vs.
*RHEINSTAHL FAHRZEUGBAU*) and use different IDs. The only shared key is the
VAT ID.

**The story in the data.** The microcontroller is single-sourced from
supplier S3 and sits three levels deep in the bill of materials (product →
control unit → PCB assembly → microcontroller). Every product except the
wiper motor contains it. Two commercial vehicle makers buy only wiper motors,
so a failure of S3 affects 13 of 15 customers, not all of them.

All company names and VAT IDs are fictional.

## Competency questions

Competency questions define what the knowledge graph must be able to answer.
They come first; the ontology is designed to answer them.

| # | Question | Answered by |
|---|---|---|
| 1 | Which customers are affected if supplier S3 fails? | `queries/cq1_affected_customers.rq` |
| 2 | How much order value depends on supplier S3? | `queries/cq2_revenue_at_risk.rq` |
| 3 | Which products depend on a part that has only one supplier? | `queries/cq3_single_source_parts.rq` |
| 4 | Which CRM accounts and ERP customers are the same company? | `queries/cq4_customer_identity.rq` |
| 5 | Which records violate the data quality rules? | `shapes/supplier-risk-shapes.ttl` |

---

# The learning path

Each lesson names the files to read, explains the key ideas and ends with
something to try. Read the code alongside: every file is commented with the
reasoning behind it.

## Lesson 0: Look at the raw data

**Files:** `data/clean/*.csv`, `data/dirty/*.csv`, `scripts/generate_data.py`

The generator writes two datasets from a fixed random seed. `clean/` is
consistent. `dirty/` is the same data with five deliberately injected errors,
documented in `data/dirty/expected_violations.json`.

**Try it:** before reading on, compare `clean/` and `dirty/` and find the five
errors yourself. Then ask: which of them would a database constraint catch,
and which would slip through?

## Lesson 1: From tables to triples

**Files:** `scripts/build_graph.py`, `graph/clean.ttl`

RDF describes everything as *subject – predicate – object* triples. Every
thing gets a global identifier (an IRI), not a row number:

```turtle
order:O-2026-0001 a srk:Order ;
    srk:placedBy       erp:KD-50007 ;
    srk:orderedProduct item:P-200 ;
    srk:quantity       3000 ;
    prov:wasAttributedTo system:erp .
```

Key ideas:

- **IRIs instead of IDs.** `erp:KD-50007` is globally unique; no two systems
  can collide. Canonical customers get opaque IRIs (a UUIDv5 of the VAT ID),
  because a real company should not be named after one system's internal key.
- **Typed literals.** `3000` is an `xsd:integer`, dates are `xsd:date`.
  Validation and arithmetic depend on it.
- **Edges cannot carry attributes.** A BOM entry has a quantity, which is an
  attribute of the relation itself. In a property graph (e.g. Neo4j) that
  would be a relationship property. In RDF the relation becomes a node of its
  own, `srk:BomLine`, with `parentItem`, `childItem` and `quantity`.
- **Provenance with PROV-O.** Every record states its source system
  (`prov:wasAttributedTo`), every customer the CRM record it was derived from
  (`prov:wasDerivedFrom`). An answer is only explainable if every fact knows
  where it came from.
- **Linking systems.** Each CRM account yields one canonical customer. ERP
  records are attached to it via the VAT ID. A record without a match gets no
  link, and stays visible as a problem.

**Try it:** open `graph/clean.ttl`, find order `O-2026-0001` and follow the
links by hand to the customer's name. Count how many hops it takes.

## Lesson 2: Modelling the domain in OWL

**Files:** `ontology/supplier-risk.ttl`, `tests/test_ontology.py`

The ontology defines the vocabulary: classes (`srk:Customer`, `srk:Part`),
properties (`srk:suppliedBy`) and the rules connecting them. Read it top to
bottom; each design decision is explained in a comment.

Key ideas:

- **Records are not companies.** A CRM account and an ERP record are two
  descriptions of one real-world customer. Instead of merging them with
  `owl:sameAs`, both point to a canonical `srk:Customer` via `srk:describes`.
  `srk:Record` and `srk:Organization` are disjoint: a record is not the
  company it describes.
- **Disjointness catches modelling errors.** Nothing can be both a product
  and a part. But customer and supplier are deliberately *not* disjoint: a
  company can buy from us and sell to us.
- **The ontology is the business glossary.** Every term has a German and an
  English `skos:prefLabel`, plus `skos:altLabel`s for the words departments
  actually use: a customer is an *Account* in sales and a *Debitor* in
  accounting; a supplier is a *Kreditor*. A test enforces the labels.

**Try it:** remove `owl:TransitiveProperty` from `srk:hasComponent`, run
`pytest tests/test_ontology.py` and watch which test fails. Put it back.

## Lesson 3: Letting the reasoner work

**Files:** `scripts/query.py` (function `reasoned_graph`), `tests/test_build_graph.py`

A reasoner derives facts that were never written down. This project uses
OWL 2 RL, the rule-based OWL profile designed for large data, via `owlrl`.

| | Triples |
|---|---|
| Asserted data | 972 |
| Ontology | 203 |
| After reasoning | 2,777 |

Two inferences carry the whole project:

- **Transitive bill of materials.** From 33 direct BOM links
  (`srk:hasDirectComponent`), the reasoner infers 100 `srk:hasComponent`
  links at any depth, e.g. that the window lift drive contains the
  microcontroller three levels down.
- **Property chain.** Orders only know ERP customer IDs. The axiom
  `srk:orderedBy owl:propertyChainAxiom (srk:placedBy srk:describes)`
  connects all 40 orders to the real customer.

Reasoning is not the only way: the SPARQL property path
`srk:hasDirectComponent+` computes the same closure at query time. A test
proves both give identical answers. The difference: the reasoner turns the
result into explicit knowledge that every consumer can use.

**Try it:** OWL uses the *open-world assumption*. If a customer has no
country in the data, OWL does not conclude "no country", only "unknown".
Think about what this means for data validation, then read Lesson 4.

## Lesson 4: Data quality with SHACL

**Files:** `shapes/supplier-risk-shapes.ttl`, `scripts/validate.py`, `tests/test_shapes.py`

SHACL describes what valid data looks like (required fields, formats, value
ranges, references to the right class) and reports every record that
violates it.

```
$ python scripts/validate.py dirty
dirty: 5 violation(s)
  ACC-1007       Every customer has exactly one country.
  KD-50012       Every ERP customer matches exactly one CRM account via VAT ID.
  O-2026-0017    Every order refers to an existing product.
  O-2026-0023    Order quantity is a positive integer.
  T-13           Every part has at least one supplier.
```

The clean data conforms; the dirty data yields exactly the five expected
violations, no more and no fewer. A test enforces this contract.

**OWL infers, SHACL checks.** This is the most important lesson of the
project. `rdfs:range srk:Product` on `srk:orderedProduct` does not *check*
that an ordered item is a product; it *concludes* that it is one. Validation
therefore runs on the asserted graph without inference. A test shows what
happens otherwise: with RDFS inference switched on, the order for the
non-existent product P-999 passes, because the reasoner declares P-999 a
product. The error resurfaces as three confusing violations on an item
nobody ever defined.

**Beyond SHACL Core.** "No item may contain itself" requires following the
bill of materials to any depth. SHACL Core cannot express that; a
SHACL-SPARQL constraint can, with `$this srk:hasDirectComponent+ $this`.

**Try it:** add a shape that rejects order dates in the future
(`sh:maxInclusive` with an `xsd:date`). Add a matching error to the dirty data
in `generate_data.py` and to `expected_violations.json`, and make the tests
pass again.

## Lesson 5: Answering questions with SPARQL

**Files:** `queries/*.rq`, `scripts/query.py`, `tests/test_queries.py`

```
$ python scripts/query.py clean cq2
affectedOrders  affectedValue  totalValue  sharePercent
26              4173970.00     5076080.00  82
```

82 % of the order value depends on one microcontroller supplier. Each query
shows a SPARQL technique:

- **CQ1** follows the full chain supplier → part → product → order →
  customer and returns the key account manager to call. It relies on the
  inferred `srk:hasComponent` and `srk:orderedBy`.
- **CQ2** avoids double counting. An order can depend on S3 through three
  different parts; a naive join would count it three times. A subquery
  collects each affected order once before summing.
- **CQ3** combines aggregation (`GROUP BY … HAVING COUNT = 1`) with graph
  traversal to find single-source parts and the products that contain them.
- **CQ4** uses `OPTIONAL` so that unmatched ERP records stay in the result
  with empty CRM columns, sorted to the top for a data steward.

**Dirty data creates blind spots.** Run CQ1 on the dirty data: Moravia
Automotive disappears from the risk list. The VAT typo broke the ERP → CRM
link, so Moravia's orders reach no customer. A data quality issue has become
a wrong business answer, without any error message. This is why Lesson 4
matters.

The tests check the answers against independent calculations from the raw
CSV files, so a wrong query cannot pass just by agreeing with itself.

**Try it:** change the supplier in CQ1 from S3 to S2, the only supplier of
the NdFeB magnets. Why are now all 15 customers affected?

## Lesson 6: Reproducibility and CI

**Files:** `.github/workflows/ci.yml`, `requirements.txt`

A knowledge graph is only trustworthy if it can be rebuilt exactly:

- a fixed random seed for the data
- deterministic IRIs, including the UUIDv5 customer IRIs
- pinned library versions, so a new rdflib release cannot change the output

On every push, CI regenerates data and graphs, checks with `git diff` that
they are byte-identical to the committed files, validates the clean data and
runs all tests.

---

## Exercises for going further

1. **Consistency across systems.** Write a SHACL-SPARQL constraint that
   checks whether an ERP record and the CRM account describing the same
   customer carry the same VAT ID.
2. **A second source for suppliers.** In real companies suppliers also live
   in the ERP (as *Kreditoren*). Add them and apply the record pattern from
   customers.
3. **A real triplestore.** Load `graph/clean.ttl` and the ontology into
   Apache Jena Fuseki or GraphDB and run the queries against the SPARQL
   endpoint.
4. **Declarative mappings.** Replace `build_graph.py` with RML mappings, the
   W3C community standard for mapping CSV and databases to RDF.
5. **Grounding an LLM.** Ask a language model question 1 twice: once with a
   text description of the company as context, once with the CQ1 result and
   its provenance. Compare the answers. This is the idea behind combining
   vector search with graph retrieval.

## Design decisions at a glance

| Decision | Why |
|---|---|
| Records point to a canonical customer via `srk:describes` instead of `owl:sameAs` | Keeps each system's ID, spelling and provenance; unmatched records stay visible |
| CRM is master for customer data | One system must own name, country and segment; ERP keeps only its own fields |
| Opaque, deterministic customer IRIs | A company should not be named after one system's key; builds stay reproducible |
| BOM line as a node | RDF edges cannot carry the quantity |
| Direct vs. transitive BOM property | Data asserts one level; the reasoner infers all levels |
| No record layer for items and suppliers | They come from one system each; provenance is attached directly |
| Validation without inference | OWL range and domain would infer away the errors SHACL should find |

## Repository structure

```
supplier-risk-kg/
├── .github/workflows/  # CI: reproducibility, validation, tests
├── data/
│   ├── clean/          # consistent source data (CSV)
│   └── dirty/          # same data with injected errors + expected_violations.json
├── graph/              # generated RDF: clean.ttl, dirty.ttl
├── ontology/           # OWL ontology with SKOS glossary
├── shapes/             # SHACL shapes
├── queries/            # SPARQL queries for the competency questions
├── scripts/
│   ├── generate_data.py
│   ├── build_graph.py
│   ├── validate.py
│   └── query.py
└── tests/              # 29 tests
```

## Further reading

- [OWL 2 Primer](https://www.w3.org/TR/owl2-primer/) and [OWL 2 Profiles](https://www.w3.org/TR/owl2-profiles/) (for OWL 2 RL)
- [SHACL specification](https://www.w3.org/TR/shacl/), surprisingly readable, with examples
- [SPARQL 1.1 Query Language](https://www.w3.org/TR/sparql11-query/)
- [PROV-O](https://www.w3.org/TR/prov-o/) and [SKOS Primer](https://www.w3.org/TR/skos-primer/)
- [Knowledge Graphs lecture series by Harald Sack](https://www.youtube.com/playlist?list=PLNXdQl4kBgzubTOfY5cbtxZCgg9UTe-uF) (openHPI)
- [SHACL Masterclass](https://github.com/veleda/shacl-masterclass) by Veronika Heimsbakk
- [Protégé Pizza Tutorial](https://ddll.inf.tu-dresden.de/w/images/0/06/Protege-Pizza-Tutorial.pdf), the classic introduction to OWL modelling

## Author

Matthias Held · [ORCID 0000-0002-8541-8830](https://orcid.org/0000-0002-8541-8830)
