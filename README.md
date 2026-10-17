# CHARMSAT — DeltaV IO Signal Sudoku Allocation Engine

**CODE APEX 3.0 Hackathon (VIT Pune)**
**Problem Statement:** IO SIGNAL SUDOKU
**Team:** `lost_in_the_shine` | **Team Leader:** Prathmesh Vishwakarma

---

## 1. What this is

**CHARMSAT** turns a customer IO list (Excel) into a complete Emerson DeltaV
Electronic Marshalling allocation — cabinet → CIOC → baseplate → CHARM slot,
CHARM + terminal block, generated names — with zero rule violations,
verified by an independent checker that reads the exported workbook. When
data or rules make placement impossible it raises a Technical Query (TQ)
naming the cause and fix. Rev B re-allocates keeping unchanged signals put.

## 2. Run it from a fresh clone

```bash
git clone <repo> && cd CHARMSAT
make install   # backend deps + frontend build
make run       # API + UI at http://127.0.0.1:8000
```

Works fully offline by default (no network). The optional hosted-LLM rule
drafter is opt-in via env vars and never part of the solver/checker path.
Python 3.10+ and Node.js 18+
(passed here on Python 3.10, Node 23). Organiser sample/template, if you
have them, go in `data/organiser/` (gitignored) — never committed.

```bash
make test       # full pytest suite
make integrity  # fails if a fabricated metric literal is (re-)introduced
make bench      # measures everything, writes bench/results.*
make demo-check # upload -> allocate -> export -> check -> revise (exit 0)
```

Optional LLM rule drafter (off by default; app is fully offline without it).
Only the rule-wording helper uses it — never the solver or checker. Any
OpenAI-compatible endpoint works:

```bash
export CHARMSAT_LLM_ENABLED=1            # opt in
export CHARMSAT_LLM_API_KEY=...          # required
export CHARMSAT_LLM_MODEL=gpt-4o-mini    # optional
export CHARMSAT_LLM_BASE_URL=https://api.openai.com/v1  # optional
```

With no key set, `llm_available` is false and the deterministic parser handles
every sentence. Even when enabled, the LLM is only consulted for sentences the
parser scores as ambiguous, receives only that sentence (no IO rows), and its
draft must pass the rule JSON Schema before a human confirms it.

## 3. What works for real, what is stubbed, what is planned

**Works (measured, tested):**

- Real xlsx/csv upload: header-row detection, synonym + value-sniffed
  column mapping with evidence, manual override applied to data, multi-sheet.
- Validator: duplicate tags/pairs, pair overflow, missing cable, unknown
  types/subtypes, multi-group and A+B-mixed cables, giant cables — each a TQ
  with all tags + Excel rows; coverage ledger (placed + held = 100%).
- Three-stage engine (ported from `reference/`): units→cabinets (CP-SAT +
  proven lower bound), cables→CIOCs (exact, per cabinet), slots (exact FFD;
  CP-SAT fallback). Deterministic across processes (single worker +
  deterministic time + fixed seed; identical hashes verified).
- Independent checker (`backend/checker/`, imports nothing from the app)
  reads the written workbook + IO rows; every allocation is verified on
  export bytes; "plant a violation" demo (7 plants, all caught).
- Template writer: results into a COPY of the template, values only,
  formula refusal, XML fallback preserving drawings, fidelity-tested;
  export carries TQ log + audit (output hash).
- Revisions: Rev B upload with tag-level diff, keep-literal re-solve +
  measured from-scratch baseline, per-move records each naming the forcing
  rule (re-derived from the data; stated as an optimiser rebalance when no
  rule blocks the old slot — never guessed).
- `make bench` slide table + Benchmarks screen reading it; honest B0/B1
  baselines (violations + unplaced reported, moves measured).
- PDS-correct hardware table (data) and token naming patterns
  (`AR1CIOC100001`, `001-CBP-1` reproduced).
- YAML rule language with JSON-Schema validation
  (`backend/app/engine/rules/schema.json`, loader `loader.py`): a rule
  document is validated before it is applied (`/api/rules/validate`,
  `GET /api/rules/schema`); a bad enum/typo is rejected with all errors at
  once. New rules of an existing kind (same / different / at most k, on
  group / seg / io_type / subtype, at cabinet / CIOC / baseplate) are
  config-only and flow to both solver and checker. The hardware table itself
  is data in the rule set.
- Forcing-rule attribution on revisions: every moved signal names the rule
  that blocks its Rev A slot under Rev B data (re-derived from the data, not
  guessed); when no rule blocks it, it is reported honestly as an optimiser
  rebalance.
- TQ minimal-conflict wording: `rule_conflict` and capacity TQs carry a MUS
  (`mus`) plus a plain-English "Minimal conflict: ..." sentence.
- "Why is this signal here?" explainer (`/api/explain/{tag}`): re-derives the
  rules the signal satisfies at its slot (CHARM match, cable contiguity,
  segregation, group cohesion, spare margin) and lists what pins it.
- What-if scoring (`/api/what-if`): add a signal or change the spare margin
  and see the recomputed cabinets/coverage without committing anything.
- Rule assistant (`/api/rules/parse-nl`): a deterministic keyword/regex parser
  drafts a typed rule from a sentence; drafts are schema-validated and require
  human confirmation. Optionally, for messy/ambiguous sentences, an operator can
  opt in to a hosted-LLM drafter (env-gated, off by default). Either way it only
  drafts wording, never places signals, sends no IO rows, and every draft is
  tagged by provenance (`parser` vs `llm`) before a human confirms it.
- Per-customer mapping profiles: a confirmed column mapping is saved by
  header signature and auto-reapplied to the next file with the same headers.
- Property/adversarial CI (`test_properties.py`, hypothesis): coverage=100%,
  no shared physical slots, CHARM matches the hardware table, checker agrees
  with the solver, deterministic across runs — on randomly seeded IO lists.

**Stubbed / simplified:**

- Mapping profiles store the confirmed mapping keyed by header signature;
  the organiser-template map ships only when their template is available
  (synthetic stand-in used).
- Screenshots in `/screenshots` predate the rebuild — retake planned.

## 4. Demo script (3 minutes, all live)

Files (generated, fixed seeds): `demo/unseen_messy.xlsx` (1,000 signals,
messy headers, 2 defects), `demo/rev_b.xlsx`, `demo/planted_ab_leak.xlsx`.
Fallbacks in `DEMO_SCRIPT.md` / blueprint §13.3. Pre-flight:
`make demo-check` (13/13 green).

| Time | Action | Point |
|---|---|---|
| 0:00 | Upload `demo/unseen_messy.xlsx` → mapping with evidence → Allocate | Unseen data; 4 cabs / LB 4 / OPTIMAL; 100%; 0 viols; 2 TQs |
| 0:50 | Checker → plant A/B leak → red → reset | Independent checker is real |
| 1:15 | TQs | Each names rules, rows, fix options |
| 1:40 | Upload `demo/rev_b.xlsx` → Revise | Ours vs scratch moves, both live |
| 2:15 | Export | Filled template + output hash; re-run identical |

## 5. Real numbers (`make bench`, 2026-10-17, 8 CPUs, commit 4052034)

Full table: `BENCHMARK.md` (source: `bench/results.*`).

- 1,000 signals: **4 cabinets / LB 4 (optimal)**, 0 violations, Rev B
  **24 moves (2.4%) vs 971 scratch**, 0.07 s.
- 5,000: 20 / 19 (gap 1), 0 violations, 473 (9.7%) vs 4641, 9.2 s.
- 10,000: 39 / 38 (gap 1), 0 violations, 1141 (11.6%) vs 8972, 8.5 s.
- Greedy baselines use fewer cabinets only by breaking rules (hundreds to
  thousands of violations) — illegal packing, captioned as such.

## 6. Open questions for the organisers (code depends on these)

1. "≈10% spare": whole empty baseplates per cabinet, rounded up or down?
   (Default: `ceil(10% × 32) = 4`; configurable.)
2. "Keep groups together": same cabinet, CIOC, or consecutive slots?
   (Default: cabinet.)
3. May 2/6/12-pair cables straddle baseplates; may 24-pair start anywhere?
   (Defaults: no; any boundary.)
4. Exact naming patterns; what is "CIOC no"? (Defaults reproduce both
   PS examples; token patterns configurable.)
5. Data breaking a rule: is a TQ the expected output, or must we split?
6. Revision: is a CHARM swap at the same slot a "move"? Cabinets vs moves
   priority? (Defaults: hardware change ≠ move; 1 cabinet = 200 moves.)
7. Hidden IO list headers / DO subtype words same as sample?
8. Does the template contain formulas/charts/images that must survive?
   (Values-only writer + XML fallback ready.)

## 7. Declarations

Python, OR-Tools CP-SAT, pandas, openpyxl, rapidfuzz, FastAPI, pydantic,
PyYAML, jsonschema, pytest, Hypothesis, React/Vite/Tailwind. Reference
prototype + this build assisted by Claude (Anthropic) — declared AI tool;
no LLM in solver/checker, app works fully offline by default. The optional
hosted-LLM rule drafter is opt-in only, disabled unless `CHARMSAT_LLM_ENABLED`
and `CHARMSAT_LLM_API_KEY` are set; it receives only the operator's sentence
(never IO rows), its output is JSON-Schema-validated before use, and drafts are
provenance-tagged (`parser` vs `llm`) so any non-reproducible step is visible.
Sample data/template (if placed in `data/organiser/`) are hackathon-only,
gitignored, never sent anywhere. Rule interpretations A1–A16 default per
blueprint §3.

## 8. Hardware & layout reference

- 1 baseplate = 12 CHARM slots; 1 CIOC = 8 baseplates = 96 slots;
  1 cabinet = 4 CIOCs = 32 baseplates = 384 slots.
- Spare rule: ≥ `ceil(10% × 32)` = 4 empty baseplates per used cabinet.
