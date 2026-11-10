"""Multi-step invariants on small synthetic networks, never the preset."""

import random

import pytest

from engine.invariants import check_no_overlap
from engine.movement import step_network
from engine.state import Vehicle


CAR = {
    "length_m": 4.5,
    "v0_mps": 13.9,
    "A_mps2": 1.5,
    "B_mps2": 2.0,
    "T_s": 1.5,
    "s0_m": 2.0,
}


def _three_edge_network():
    return {
        "edges": [
            {"id": "e1", "length": 100.0, "lanes": 2, "speed_limit": 13.9},
            {"id": "e2", "length": 150.0, "lanes": 1, "speed_limit": 13.9},
            {"id": "e3", "length": 100.0, "lanes": 1, "speed_limit": 13.9},
        ],
        "connections": [
            {"from_edge": "e1", "to_edge": "e2", "lanes": [0, 0]},
            {"from_edge": "e2", "to_edge": "e3", "lanes": [0]},
        ],
    }


def _vehicle(vehicle_id, edge_id, lane, s, v, route):
    return Vehicle(
        id=vehicle_id,
        edge_id=edge_id,
        lane=lane,
        s=s,
        v=v,
        length=4.5,
        route=route,
    )


def _run_state(seed, steps=300):
    network = _three_edge_network()
    rng = random.Random(seed)
    vehicles = {}
    lanes = {"e1": [[], []], "e2": [[]], "e3": [[]]}
    type_ids = {}
    vehicle_id = 1
    for lane_index in range(2):
        position = 2.0
        for _ in range(5):
            position += 8.0 + rng.uniform(0.0, 3.0)
            vehicles[vehicle_id] = _vehicle(
                vehicle_id, "e1", lane_index, position, 0.0, ["e1", "e2", "e3"]
            )
            lanes["e1"][lane_index].append(vehicle_id)
            type_ids[vehicle_id] = "car"
            vehicle_id += 1
    for _ in range(steps):
        step_network(vehicles, lanes, network, type_ids, {"car": CAR}, dt=0.1)
        assert check_no_overlap(vehicles, lanes) == []
    return vehicles


def test_blocked_vehicle_brakes_to_rest_and_never_moves_backward():
    network = _three_edge_network()
    blocked = _vehicle(1, "e1", 0, 98.0, 13.9, ["e1", "e2", "e3"])
    fixed_blocker = _vehicle(2, "e2", 0, 0.0, 0.0, ["e2"])
    vehicles = {1: blocked, 2: fixed_blocker}
    lanes = {"e1": [[1], []], "e2": [[2]], "e3": [[]]}
    type_ids = {1: "car", 2: "car"}
    previous_s = blocked.s
    previous_v = blocked.v
    maximum_allowed_s = 100.0 - CAR["s0_m"]
    step_five_speed = None

    for step_number in range(1, 31):
        step_network(vehicles, lanes, network, type_ids, {"car": CAR}, dt=0.1)
        fixed_blocker.s = 0.0
        fixed_blocker.v = 0.0
        assert blocked.v <= previous_v
        assert blocked.s <= previous_s
        assert blocked.s <= maximum_allowed_s
        assert check_no_overlap(vehicles, lanes) == []
        previous_s, previous_v = blocked.s, blocked.v
        if step_number == 5:
            step_five_speed = blocked.v

    assert step_five_speed == pytest.approx(0.0, abs=1e-2)
    assert blocked.v <= 0.01


def test_ten_vehicles_run_300_steps_without_overlap_after_any_step():
    _run_state(seed=8172, steps=300)


def test_same_seed_has_byte_identical_sorted_states_after_300_steps():
    first = _run_state(seed=8172, steps=300)
    second = _run_state(seed=8172, steps=300)

    def state_bytes(vehicles):
        state = [
            (vehicle.id, vehicle.edge_id, vehicle.lane, round(vehicle.s, 6), round(vehicle.v, 6))
            for vehicle in sorted(vehicles.values(), key=lambda item: item.id)
        ]
        return repr(state).encode("utf-8")

    assert state_bytes(first) == state_bytes(second)


def test_cumulative_distance_matches_speed_integral_across_edge_transition():
    network = {
        "edges": [
            {"id": "e1", "length": 100.0, "lanes": 2, "speed_limit": 13.9},
            {"id": "e2", "length": 150.0, "lanes": 1, "speed_limit": 13.9},
        ],
        "connections": [
            {"from_edge": "e1", "to_edge": "e2", "lanes": [0, 0]}
        ],
    }
    vehicles = {
        1: _vehicle(1, "e1", 0, 99.5, 13.9, ["e1", "e2"]),
        2: _vehicle(2, "e2", 0, 50.0, 0.0, ["e2"]),
    }
    lanes = {"e1": [[1], []], "e2": [[2]]}
    type_ids = {1: "car", 2: "car"}
    dt = 0.1
    integrated_distance = 0.0
    measured_displacement = 0.0

    for _ in range(20):
        before = {vehicle_id: (vehicle.edge_id, vehicle.s) for vehicle_id, vehicle in vehicles.items()}
        step_network(vehicles, lanes, network, type_ids, {"car": CAR}, dt=dt)
        integrated_distance += sum(vehicle.v * dt for vehicle in vehicles.values())
        edge_lengths = {edge["id"]: edge["length"] for edge in network["edges"]}
        for vehicle_id, vehicle in vehicles.items():
            old_edge, old_s = before[vehicle_id]
            if vehicle.edge_id == old_edge:
                measured_displacement += vehicle.s - old_s
            else:
                measured_displacement += edge_lengths[old_edge] - old_s + vehicle.s

    assert abs(integrated_distance - measured_displacement) <= 1e-6 * len(vehicles)


def test_d4_unreserved_race_overlaps_at_rear_clear_but_reservation_prevents_it():
    network = {
        "edges": [
            {"id": "edge_A", "length": 100.0, "lanes": 2, "speed_limit": 13.9},
            {"id": "edge_B", "length": 100.0, "lanes": 1, "speed_limit": 13.9},
        ],
        "connections": [
            {"from_edge": "edge_A", "to_edge": "edge_B", "lanes": [0, 0]}
        ],
    }
    def fresh_race():
        vehicles = {
            1: _vehicle(1, "edge_A", 0, 99.5, 13.9, ["edge_A", "edge_B"]),
            2: _vehicle(2, "edge_A", 1, 99.5, 13.9, ["edge_A", "edge_B"]),
        }
        lanes = {"edge_A": [[1], [2]], "edge_B": [[]]}
        return vehicles, lanes, {1: "car", 2: "car"}

    unreserved, unreserved_lanes, type_ids = fresh_race()
    first_overlap_step = None
    for step_number in range(1, 21):
        step_network(
            unreserved, unreserved_lanes, network, type_ids, {"car": CAR},
            dt=0.1, use_reservations=False,
        )
        if check_no_overlap(unreserved, unreserved_lanes):
            first_overlap_step = step_number
            break
    assert first_overlap_step == 4

    reserved, reserved_lanes, type_ids = fresh_race()
    b_front_crossings = 0
    for step_number in range(1, 21):
        b_before = reserved[2].s
        step_network(reserved, reserved_lanes, network, type_ids, {"car": CAR}, dt=0.1)
        assert check_no_overlap(reserved, reserved_lanes) == []
        if b_before <= 100.0 < reserved[2].s and reserved[2].edge_id == "edge_A":
            b_front_crossings += 1
            a = reserved[1]
            b_overflow = reserved[2].s - 100.0
            assert a.edge_id == "edge_B"
            assert a.s - a.length >= b_overflow + CAR["s0_m"]
    assert b_front_crossings == 1
