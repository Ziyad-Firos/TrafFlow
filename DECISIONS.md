# Design and gate log

## Layer 4a review notes

- S1's -757 m/s^2 is unphysical for a single step but correct for the snapshot. Root cause: strict yellow rule turns phantom leader on instantly. Vehicles near the stop line at yellow onset will experience extreme braking. Known limitation of v1's spec-compliant rule; fix in v1.1 by committed-vehicle exception.
- S6 (saturation flow measurement) scheduled for 4a but requires spawning and routing from 4c. Deferred to 4d where it becomes a required gate alongside I1-I5. Tolerance unchanged: 3645 ± 10%.
- controlled_edges added to scope signal gating to specific incoming edges. Defensive for v1 (no minor-road demand), required for v1.1. Tested by test_red_signal_does_not_gate_uncontrolled_minor_road.
