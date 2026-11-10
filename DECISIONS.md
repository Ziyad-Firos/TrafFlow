# Design and gate log

## Layer 4a review notes

- S1's -757 m/s^2 is unphysical for a single step but correct for the snapshot. Root cause: strict yellow rule turns phantom leader on instantly. Vehicles near the stop line at yellow onset will experience extreme braking. Known limitation of v1's spec-compliant rule; fix in v1.1 by committed-vehicle exception.
- S6 (saturation flow measurement) scheduled for 4a but requires spawning and routing from 4c. Deferred to 4d where it becomes a required gate alongside I1-I5. Tolerance unchanged: 3645 ± 10%.
- controlled_edges added to scope signal gating to specific incoming edges. Defensive for v1 (no minor-road demand), required for v1.1. Tested by test_red_signal_does_not_gate_uncontrolled_minor_road.

## Layer 4b topology correction

Clarification 1 of the 4b handoff claimed 'no multi-from-edge merges in v1.' Factually wrong. The preset has two — (a_d2_j2,0) shared by arterial lane 0 and r_e_off; (a_d1_w,0) shared by arterial lane 0 and r_w_off. Caught by AI before 4b was written. State shape revised from per-connection to per-slot to support zipper across approach types. Without this fix, the flyover comparison (I3) would silently fail because off-ramp vehicles starve under id order. This is a factual claim about topology I asserted with confidence, not an arithmetic slip — the most consequential of the seven errors I have made, since every layer above this one trusted the connections list.

- v1.1 multi-edge merge state may benefit from a `RunState` dataclass refactor; v1 keeps mutable merge state as an explicit `step_network` argument.
- v1 admits at most one vehicle per merge slot per step. At 1800 veh/hr, expected flow is 0.05 veh/step, so two admissions in one 0.1 s step are rare; this remains a deliberate simplification.
- v1 uses a uniform 4.5 m car length, so a failed 6.5 m (length + s0) entry clearance implies no approach can fit. With multiple vehicle lengths in v1.1, reservation failure may need to try another approach when vehicle length is the binding constraint.
- M6 (merge-flow demand test) deferred to 4d with S6 and I1-I5; target remains 150 ± 20% (120–180).
- The earlier D4 expectation of an overlap with reservations disabled is superseded by per-slot zipper admission: at most one contender per downstream slot can be admitted in a step, so that specific race cannot be reproduced through `step_network`. D4 now checks that same-slot zipper arbitration preserves no-overlap with reservations both enabled and disabled. Reservation rejection remains covered directly by M4.
