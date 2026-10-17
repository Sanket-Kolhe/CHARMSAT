# CHARMSAT — 3-Minute Live Hackathon Demo Script
**Event:** CODE APEX 3.0 (VIT Pune) | **Problem Statement:** IO SIGNAL SUDOKU  
**Team:** lost_in_the_shine | **Lead:** Prathmesh Vishwakarma  

---

## Demo Timing & Sequence (Matching Pitch Deck)

### [0:00 – 0:40] Introduction & The Problem
- **Speaker:** "Good morning judges. Control engineers today spend hundreds of hours manually arranging 10,000+ IO signals into cabinets, CIOCs, baseplates, and CHARMs using Excel. When a customer sends Rev B, engineers have to recheck every single rule by eye. One wrong slot means physical rewiring on site. Our solution is **CHARMSAT**: a rule-driven constraint optimization engine powered by OR-Tools CP-SAT and backed by an independent verifier that guarantees zero rule violations."

---

### [0:40 – 1:10] Step 1: Upload & Column Auto-Mapping (Screen 1)
- **Action:** Open `Screen 1: Upload & Mapping`.
- **Action:** Click **"LOAD DEMO FILE"** (1,000 Signals).
- **Showcase:**
  - Point to the **Rapidfuzz Confidence Bar** showing automatic column resolution (e.g. `TAG_NAME` → `Tag`, `CHANNEL_TYPE` → `IO Type`).
  - Toggle **"Fuzz Headers"** to show resilience against messy real-world customer spreadsheets.
  - Click **"Confirm Mapping & Proceed to Solve"**.

---

### [1:10 – 1:35] Step 2: Rule Panel & Natural Language Assistant (Screen 2)
- **Action:** Navigate to `Screen 2: Rule Panel`.
- **Showcase:**
  - Show that rules are **data, not hardcoded logic**.
  - Point to editable parameters resolving problem statement ambiguities:
    - *A/B Segregation level* (CIOC vs Cabinet).
    - *Small Cable Straddling* (6/2-pair boundary crossing toggle).
    - *Spare Margin slider* (10% to 20%).
    - *Naming Patterns* (DeltaV AR1CIOC vs 3-digit numeric).
  - Demonstrate the **Natural Language Rule Assistant**:
    - Type: `"Segregate Train A and Train B signals at CIOC level"`.
    - Click **"Compile to Rule Draft"** → Explain that AI is strictly restricted to wording syntax and *never places signals*.
  - Show the live **YAML Rule Preview**.

---

### [1:35 – 2:05] Step 3: Physical DeltaV Cabinet Grid & KPIs (Screen 3)
- **Action:** Navigate to `Screen 3: Allocation Grid`.
- **Showcase:**
  - **KPI Cards:** Read the LIVE values — signals placed + held-by-TQ (= coverage), checker violations, cabinets / lower bound / gap, empty baseplates per cabinet vs required, runtime, solver status. (If a card shows an empty state, say so — never invent a number.)
  - **Physical Layout:** Explain the 4 CIOCs per cabinet, 8 baseplates per CIOC, 12 CHARMs per baseplate (384 slots/cabinet).
  - Hover over a slot: show the interactive tooltip displaying `Tag`, `Cable`, `Pair`, `CHARM Model`, and `Terminal Block`.
  - Point out the **TRAIN A (Cyan)** and **TRAIN B (Amber)** segregation badges on CIOC headers.

---

### [2:05 – 2:30] Step 4: The Credibility Demo — Plant a Violation (Screen 4)
- **Action:** Navigate to `Screen 4: Checker Report`.
- **Showcase:**
  - Point to the glowing green badge: **"0 VIOLATIONS — CLEAN AUDIT // VERIFIED"**.
  - Explain: *"Judges might ask: does your checker just share your solver's bugs? No. It is an independent module with zero shared code."*
  - **The Hook:** Click **"Plant A/B Leak"**!
  - The screen flashes red with the violations the checker caught (live count — point to it). Point to the exact offending row highlighted in red where an A signal was leaked into a B CIOC.
  - Click **"Reset to Clean"** to return to 0 violations.

---

### [2:30 – 2:50] Step 5: Infeasibility & TQs (Screen 5)
- **Action:** Navigate to `Screen 5: Technical Queries (TQs)`.
- **Action:** Click **"LOAD ADVERSARIAL CONFLICT FILE"**.
- **Showcase:**
  - Explain: *"When real-world data is contradictory, CHARMSAT never crashes or silently drops signals. It raises a TQ naming the conflicting rules and the minimal set that cannot all hold (the MUS)."*
  - Expand the conflict TQ: show the plain-English explanation naming the cable, the rules, and the fix options.

---

### [2:50 – 3:15] Step 6: Minimum-Move Revision B (Screen 6)
- **Action:** Click **"DEMO MODE"** to reset, then navigate to `Screen 6: Revision Diff`.
- **Showcase:**
  - Point to the live numbers: **OURS (keep-literal revision)** vs **from-scratch re-solve** moves, both computed in the run. Read the ratio aloud from the screen — do not quote a rehearsed figure.
  - Highlight: *"Because our solver treats Rev A as soft hints with a move penalty, field terminations stay valid unless a rule forces a move — and each move names its forcing rule."*
  - Scroll down to the cabinet grid: point to the relocated slots pulsing in **neon amber**.

---

### [3:15 – 3:35] Step 7: Empirical Benchmarks (Screen 7)
- **Action:** Navigate to `Screen 7: Benchmarks`.
- **Pre-flight:** run `make bench` before the slot and confirm the table is populated. If the screen shows "No benchmark run yet", say so and run it live (or show the pre-run) — never quote remembered numbers.
- **Showcase:** Read the live table aloud: B0 violations, B1 violations + moves, CHARMSAT violations + cabinets/lower bound/gap + runtime. Point to `bench/results.md` + `meta.json` (machine, date, commit) as the source judges can re-run.

---

### [3:35 – 3:50] Step 8: Production Export (Screen 8)
- **Action:** Navigate to `Screen 8: Export`.
- **Showcase:**
  - Click **"DOWNLOAD FILLED EXCEL (.XLSX)"**.
  - Show that the exported workbook contains all 5 styled sheets: Project Summary KPIs, IO Assignment Matrix, Independent Checker Audit, TQ Log, and Revision B Diff.

---

### [3:50 – 4:00] Conclusion
- *"In summary: CHARMSAT gives EPCs and plant owners guaranteed zero-violation allocations, plain-English TQs, and minimum-move revisions that prevent physical rewiring. Thank you!"*

---

## Optional WOW detours (if time allows)

- **Live-added rule (Screen 2):** add a custom rule in the panel (relation /
  attribute / level / k / classes), watch the YAML box and the schema badge.
  Type a typo in the YAML box → the badge turns red with the schema errors and
  SAVE is refused. Fix it, SAVE, and the allocation re-solves with the new
  rule — no code change.
- **Rule assistant (Screen 2):** type *"keep each group on one cabinet"* →
  the offline assistant drafts a typed rule (schema-validated, human-confirm).
  Stress: it only drafts wording; it never receives IO rows or places signals.
  Each draft shows its provenance badge (OFFLINE PARSER). Only if an API key is
  configured can you tick *"Use optional LLM drafter"* for a messy sentence — the
  badge then says LLM DRAFT (non-reproducible) and the draft still must pass the
  schema and be confirmed by you. Default demo path needs no key and no network.
- **What-if (Screen 3):** add one signal or drop the spare margin → the panel
  recomputes cabinets/coverage live and states plainly it did not commit.
- **Why is this here (Screen 3):** click any CHARM → the explainer re-derives
  the rules that slot satisfies and which rule pins it.
- **Mapping profile (Screen 1):** name and save the mapping, then confirm a
  second file with the same headers — it reuses the saved profile.

