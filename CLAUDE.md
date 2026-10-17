# CHARMSAT — context for coding agents

## What this is
A hackathon entry (CODE APEX 3.0, problem #02 "IO SIGNAL SUDOKU"). It allocates a customer IO list
(Excel, one row per signal) to Emerson DeltaV hardware: cabinet (4 CIOCs) > CIOC (8 baseplates) >
baseplate (12 CHARM slots). It writes the organiser's Excel template, raises Technical Queries (TQs),
and re-allocates revisions (Rev A -> Rev B) with the fewest moves.

## Non-negotiable constraints
1. Python 3.11+ backend. OR-Tools CP-SAT for placement. React UI in frontend/ (keep it).
2. NOTHING hard-coded about rules: every rule lives in a YAML rule set validated by
   backend/app/engine/rules/schema.json. A new rule of an existing kind needs no code change.
3. NO hand-edited or fabricated outputs. Every number shown in the UI, README, BENCHMARK.md or slides
   must come from code that ran. Never type a metric into source code. Empty state > fake number.
4. AI/LLMs NEVER place signals. They may only (a) suggest column mappings from header names and
   (b) draft rules from a sentence; drafts are schema-validated and confirmed by a human.
   LLMs never receive IO-list rows. The app must work fully offline.
5. backend/checker/ must not import anything from backend/app/. It re-derives every rule from the
   written workbook + the input IO list + the rule YAML.
6. Determinism: same input + same rule set => byte-identical allocation rows and the same output hash.
   CP-SAT runs with num_workers=1 and max_deterministic_time unless the user picks "fast" mode.
7. Organiser sample data and template stay in data/organiser/ (gitignored). Never commit or upload them.

## Definition of done (from the problem statement)
- 100% of signals allocated, or held by a TQ that explains why (coverage = placed + held = 100%).
- Zero violations of the user's rules, as reported by backend/checker on the exported workbook.
- Right CHARM, terminal block and names (hardware table and naming patterns are data).
- Revision-friendly: unchanged signals stay put unless a rule forces a move; each move names the rule.
- Flexible: a new rule or a new IO list needs no code change.

## Commands
make install | make run | make test | make bench | make demo-check | make integrity
