"""Transition and same-step lane-reservation tests on a minimal graph."""

from engine.invariants import check_no_overlap
from engine.state import Vehicle
from engine.movement import step_network
import pytest


def _network():
    return {
        "edges": [
            {"id": "edge_A", "length": 100.0, "lanes": 2, "speed_limit": 13.9},
            {"id": "edge_B", "length": 100.0, "lanes": 1, "speed_limit": 13.9},
        ],
        "connections": [
            {"from_edge": "edge_A", "to_edge": "edge_B", "lanes": [0, 0]}
        ],
    }


def _vehicle(vehicle_id: int, lane: int, s: float, v: float = 13.9) -> Vehicle:
    return Vehicle(
        id=vehicle_id,
        edge_id="edge_A",
        lane=lane,
        s=s,
        v=v,
        length=4.5,
        route=["edge_A", "edge_B"],
    )


def _vehicle_types():
    return {
        "car": {
            "length_m": 4.5,
            "v0_mps": 13.9,
            "A_mps2": 1.5,
            "B_mps2": 2.0,
            "T_s": 1.5,
            "s0_m": 2.0,
        }
    }


def test_same_step_arrivals_reserve_shared_downstream_lane_before_rear_clear():
    network = _network()
    vehicles = {1: _vehicle(1, lane=0, s=99.5), 2: _vehicle(2, lane=1, s=99.5)}
    lanes = {"edge_A": [[1], [2]], "edge_B": [[]]}
    type_ids = {1: "car", 2: "car"}

    step_network(vehicles, lanes, network, type_ids, _vehicle_types(), dt=0.1)

    assert vehicles[1].s == 100.89
    assert vehicles[1].edge_id == "edge_A"
    assert vehicles[2].s == 99.5
    assert vehicles[2].edge_id == "edge_A"
    assert vehicles[1].s - vehicles[1].length <= vehicles[2].s
    assert check_no_overlap(vehicles, lanes) == []

    for _ in range(3):
        step_network(vehicles, lanes, network, type_ids, _vehicle_types(), dt=0.1)
        assert check_no_overlap(vehicles, lanes) == []

    assert vehicles[1].edge_id == "edge_B"
    assert vehicles[1].s == pytest.approx(5.06, abs=1e-9)
    assert vehicles[2].edge_id == "edge_A"


def test_clean_crossing_keeps_edge_attribution_until_rear_clears():
    network = _network()
    vehicles = {1: _vehicle(1, lane=0, s=99.5)}
    lanes = {"edge_A": [[1], []], "edge_B": [[]]}
    type_ids = {1: "car"}

    step_network(vehicles, lanes, network, type_ids, _vehicle_types(), dt=0.1)
    assert vehicles[1].edge_id == "edge_A"
    assert vehicles[1].s == pytest.approx(100.89, abs=1e-9)

    for _ in range(3):
        assert vehicles[1].edge_id == "edge_A"
        step_network(vehicles, lanes, network, type_ids, _vehicle_types(), dt=0.1)
        if vehicles[1].edge_id == "edge_A":
            assert vehicles[1].s - vehicles[1].length < 100.0

    assert vehicles[1].edge_id == "edge_B"
    assert vehicles[1].s == pytest.approx(5.06, abs=1e-9)


def test_blocked_downstream_holds_vehicle_without_moving_it_backward():
    network = _network()
    incoming = _vehicle(1, lane=0, s=99.5)
    downstream = Vehicle(
        id=2,
        edge_id="edge_B",
        lane=0,
        s=0.0,
        v=0.0,
        length=4.5,
        route=["edge_B"],
    )
    vehicles = {1: incoming, 2: downstream}
    lanes = {"edge_A": [[1], []], "edge_B": [[2]]}
    type_ids = {1: "car", 2: "car"}

    step_network(vehicles, lanes, network, type_ids, _vehicle_types(), dt=0.1)

    assert incoming.edge_id == "edge_A"
    assert incoming.s == 99.5
    assert incoming.s >= 99.5
    assert incoming.v == 0.0
    assert check_no_overlap(vehicles, lanes) == []
