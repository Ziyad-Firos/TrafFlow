"""Fixed-time signal gating at stop lines; no merge or signal metrics tests."""

import pytest

from engine.movement import step_network
from engine.state import Vehicle


SIGNAL = {
    "cycle_s": 80.0,
    "green_s": 54.0,
    "yellow_s": 2.0,
    "red_s": 24.0,
    "offset_s": 0.0,
    "controlled_edges": ["edge_A"],
}
CAR = {
    "length_m": 4.5,
    "v0_mps": 13.9,
    "A_mps2": 1.5,
    "B_mps2": 2.0,
    "T_s": 1.5,
    "s0_m": 2.0,
}


def _signal_network():
    return {
        "nodes": [
            {"id": "W", "x": 0.0, "y": 0.0, "type": "plain"},
            {"id": "J", "x": 100.0, "y": 0.0, "type": "signalized"},
            {"id": "E", "x": 200.0, "y": 0.0, "type": "plain"},
        ],
        "edges": [
            {"id": "edge_A", "from_node": "W", "to_node": "J", "length": 100.0, "lanes": 3, "speed_limit": 13.9},
            {"id": "edge_B", "from_node": "J", "to_node": "E", "length": 100.0, "lanes": 3, "speed_limit": 13.9},
        ],
        "connections": [
            {"from_edge": "edge_A", "to_edge": "edge_B", "lanes": [0, 1, 2]}
        ],
    }


def _state(s=99.5):
    vehicles = {
        1: Vehicle(
            id=1,
            edge_id="edge_A",
            lane=0,
            s=s,
            v=13.9,
            length=4.5,
            route=["edge_A", "edge_B"],
        )
    }
    lanes = {"edge_A": [[1], [], []], "edge_B": [[], [], []]}
    return vehicles, lanes


@pytest.mark.parametrize(
    ("time_s", "expected_s"),
    [
        (53.8, 100.89),  # step starts green
        (53.97, 100.89), # step starts green, even though the phase changes mid-step
        (55.97, 99.5),   # step starts yellow: entry is closed
        (79.97, 99.5),   # step starts red, even though green begins mid-step
    ],
)
def test_signal_phase_at_step_start_gates_stop_line_entry(time_s, expected_s):
    vehicles, lanes = _state()

    step_network(
        vehicles,
        lanes,
        _signal_network(),
        {1: "car"},
        {"car": CAR},
        dt=0.1,
        time_s=time_s,
        signals={"J": SIGNAL},
    )

    assert vehicles[1].edge_id == "edge_A"
    assert vehicles[1].s == pytest.approx(expected_s, abs=1e-9)


def test_vehicle_already_past_stop_line_continues_during_red():
    vehicles, lanes = _state(s=100.89)

    step_network(
        vehicles,
        lanes,
        _signal_network(),
        {1: "car"},
        {"car": CAR},
        dt=0.1,
        time_s=56.0,
        signals={"J": SIGNAL},
    )

    assert vehicles[1].edge_id == "edge_A"
    assert vehicles[1].s == pytest.approx(102.28, abs=1e-9)


def test_red_signal_does_not_gate_uncontrolled_minor_road():
    network = _signal_network()
    network["nodes"].extend([
        {"id": "N", "x": 100.0, "y": -100.0, "type": "plain"},
        {"id": "S", "x": 100.0, "y": 100.0, "type": "plain"},
    ])
    network["edges"].extend([
        {"id": "minor_in", "from_node": "N", "to_node": "J", "length": 100.0, "lanes": 1, "speed_limit": 8.3},
        {"id": "minor_out", "from_node": "J", "to_node": "S", "length": 100.0, "lanes": 1, "speed_limit": 8.3},
    ])
    network["connections"].append(
        {"from_edge": "minor_in", "to_edge": "minor_out", "lanes": [0]}
    )
    vehicle = Vehicle(
        id=2,
        edge_id="minor_in",
        lane=0,
        s=99.5,
        v=8.3,
        length=4.5,
        route=["minor_in", "minor_out"],
    )
    vehicles = {2: vehicle}
    lanes = {"edge_A": [[], [], []], "edge_B": [[], [], []], "minor_in": [[2]], "minor_out": [[]]}
    car = {**CAR, "v0_mps": 8.3}

    step_network(
        vehicles,
        lanes,
        network,
        {2: "car"},
        {"car": car},
        dt=0.1,
        time_s=56.0,
        signals={"J": SIGNAL},
    )

    assert vehicle.s == pytest.approx(100.33, abs=1e-9)
    assert vehicle.edge_id == "minor_in"
