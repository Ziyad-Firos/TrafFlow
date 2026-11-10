"""Deterministic zipper arbitration and movement integration for merge slots."""

import copy

from engine.movement import step_network
from engine.state import Vehicle
from engine.merges import arbitrate_merge_slot


def _choose(approaches, last_served, waiters, can_reserve=lambda _vehicle_id: True):
    slot = ("out", 0)
    state = {slot: last_served} if last_served is not None else {}
    selected = arbitrate_merge_slot(slot, approaches, state, waiters, can_reserve)
    return selected, state.get(slot)


def test_m1_three_lane_slot_initializes_with_lane_zero_first():
    approaches = [("in", 0), ("in", 1), ("in", 2)]
    selected, last_served = _choose(
        approaches, None, {approach: [approach[1] + 10] for approach in approaches}
    )
    assert selected == (("in", 0), 10)
    assert last_served == ("in", 0)


def test_m2_two_waiters_each_lane_are_admitted_in_alternating_order():
    approaches = [("in", 0), ("in", 1)]
    state = {}
    waiters = {("in", 0): [1, 2], ("in", 1): [3, 4]}
    admitted = []
    for _ in range(4):
        vehicle = arbitrate_merge_slot(("out", 0), approaches, state, waiters)
        assert vehicle is not None
        approach, vehicle_id = vehicle
        admitted.append(vehicle_id)
        waiters[approach].remove(vehicle_id)
    assert admitted == [1, 3, 2, 4]


def test_m3_only_nonempty_approach_is_served_in_id_order():
    approaches = [("in", 0), ("in", 1), ("in", 2)]
    state = {}
    waiters = {("in", 0): [], ("in", 1): [12, 11], ("in", 2): []}
    admitted = []
    for _ in range(2):
        selected = arbitrate_merge_slot(("out", 0), approaches, state, waiters)
        assert selected is not None
        approach, vehicle_id = selected
        admitted.append(vehicle_id)
        waiters[approach].remove(vehicle_id)
    assert admitted == [11, 12]


def test_m4_failed_reservation_admits_nobody_and_preserves_turn():
    approaches = [("arterial", 0), ("ramp", 0)]
    initial = ("ramp", 0)
    selected, last_served = _choose(
        approaches, initial, {("arterial", 0): [1], ("ramp", 0): [2]},
        can_reserve=lambda _vehicle_id: False,
    )
    assert selected is None
    assert last_served == initial


def test_m5_lowest_vehicle_id_wins_within_selected_approach():
    approaches = [("in", 0), ("in", 1)]
    selected, last_served = _choose(
        approaches, ("in", 1), {("in", 0): [9, 3], ("in", 1): []}
    )
    assert selected == (("in", 0), 3)
    assert last_served == ("in", 0)


def _same_edge_network():
    return {
        "edges": [
            {"id": "in", "length": 100.0, "lanes": 2, "speed_limit": 13.9},
            {"id": "out", "length": 1000.0, "lanes": 1, "speed_limit": 13.9},
        ],
        "connections": [{"from_edge": "in", "to_edge": "out", "lanes": [0, 0]}],
    }


def _run_m7():
    vehicles = {
        1: Vehicle(1, "in", 0, 99.5, 13.9, 4.5, ["in", "out"]),
        2: Vehicle(2, "in", 0, 93.0, 13.9, 4.5, ["in", "out"]),
        3: Vehicle(3, "in", 1, 99.5, 13.9, 4.5, ["in", "out"]),
        4: Vehicle(4, "in", 1, 93.0, 13.9, 4.5, ["in", "out"]),
    }
    lanes = {"in": [[2, 1], [4, 3]], "out": [[]]}
    merge_state = {}
    car = {"length_m": 4.5, "v0_mps": 13.9, "A_mps2": 1.5, "B_mps2": 2.0, "T_s": 1.5, "s0_m": 2.0}
    for _ in range(20):
        step_network(
            vehicles, lanes, _same_edge_network(), {i: "car" for i in vehicles}, {"car": car},
            dt=0.1, merge_state=merge_state,
        )
    states = tuple(
        (i, v.edge_id, v.lane, round(v.s, 6), round(v.v, 6))
        for i, v in sorted(vehicles.items())
    )
    return copy.deepcopy(merge_state), states


def test_m7_same_seed_twenty_steps_has_identical_merge_and_vehicle_states():
    first_state, first_vehicles = _run_m7()
    second_state, second_vehicles = _run_m7()
    assert repr(first_state).encode() == repr(second_state).encode()
    assert first_vehicles == second_vehicles


def test_m8_empty_lane_is_skipped_with_round_robin_over_active_lanes():
    approaches = [("in", 0), ("in", 1), ("in", 2)]
    state = {}
    waiters = {("in", 0): [], ("in", 1): [11, 12], ("in", 2): [21, 22]}
    served_lanes = []
    for _ in range(4):
        selected = arbitrate_merge_slot(("out", 0), approaches, state, waiters)
        assert selected is not None
        approach, vehicle_id = selected
        served_lanes.append(approach[1])
        waiters[approach].remove(vehicle_id)
    assert served_lanes == [1, 2, 1, 2]


def test_m9_multi_edge_slot_alternates_arterial_ramp_arterial():
    approaches = [("a_j1_d2", 0), ("r_e_off", 0)]
    state = {("a_d2_j2", 0): approaches[-1]}
    waiters = {approaches[0]: [1], approaches[1]: [2]}
    admitted = []
    for vehicle_id in (1, 2, 1):
        approach = approaches[0] if vehicle_id == 1 else approaches[1]
        waiters[approach] = [vehicle_id]
        selected = arbitrate_merge_slot(("a_d2_j2", 0), approaches, state, waiters)
        assert selected == (approach, vehicle_id)
        admitted.append(selected)
    assert admitted == [(("a_j1_d2", 0), 1), (("r_e_off", 0), 2), (("a_j1_d2", 0), 1)]


def test_m10_continuous_two_approach_demand_does_not_starve_off_ramp():
    approaches = [("a_j1_d2", 0), ("r_e_off", 0)]
    state = {("a_d2_j2", 0): approaches[-1]}
    counts = {approach: 0 for approach in approaches}
    for step in range(100):
        waiters = {approach: [step * 2 + i] for i, approach in enumerate(approaches)}
        selected = arbitrate_merge_slot(("a_d2_j2", 0), approaches, state, waiters)
        assert selected is not None
        counts[selected[0]] += 1
    assert counts == {("a_j1_d2", 0): 50, ("r_e_off", 0): 50}
