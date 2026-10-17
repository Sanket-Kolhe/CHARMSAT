"""Measured trade-off: reserve extra empty baseplates in Rev A (growth headroom), revise with the normal 10% spare."""
import copy, json, sys
import charmsat_core as E
n = int(sys.argv[1])
sig_a, sz_a = E.generate(n, seed=42)
sig_b, sz_b, meta = E.generate_revision(sig_a, sz_a)
for reserve_pct in (10.0, 12.5, 15.0, 18.75):          # 4, 4, 5, 6 empty baseplates in Rev A
    ra_rules = copy.deepcopy(E.DEFAULT_RULES); ra_rules["spare"]["percent"] = reserve_pct
    rb_rules = copy.deepcopy(E.DEFAULT_RULES)          # Rev B must still honour 10%
    ra = E.allocate(sig_a, sz_a, ra_rules)
    rb = E.allocate(sig_b, sz_b, rb_rules, prev=ra["placements"])
    mv = E.count_moves(ra["rows"], rb["rows"], sig_a, sig_b)
    print(json.dumps({"N": n, "revA_empty_bp": E.spare_baseplates(ra_rules), "revA_cabinets": ra["cabinets"],
                      "revB_cabinets": rb["cabinets"], "moves": mv["moved"], "unchanged": mv["unchanged_inputs"]}), flush=True)
