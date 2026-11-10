"""Layer 1 contract and preset-network regression tests."""

from math import hypot
from copy import deepcopy
import json
from pathlib import Path

import pytest

from engine.network import (
    find_route,
    load_preset_network,
    normalize_route_share,
    validate_network,
)
from engine.scenario import may_enter_junction, signal_phase_at, validate_scenario


def test_preset_network_contract_and_connection_endpoints():
    network = load_preset_network(flyover_enabled=True)

    assert network["schema_version"] == "1.0"
    assert network["geo_anchor"] is None
    assert len(network["nodes"]) == 14
    assert len(network["edges"]) == 24
    assert validate_network(network) == []

    nodes = {node["id"] for node in network["nodes"]}
    edges = {edge["id"]: edge for edge in network["edges"]}
    assert all(edge["from_node"] in nodes and edge["to_node"] in nodes for edge in edges.values())
    assert all(
        edges[connection["from_edge"]]["to_node"]
        == edges[connection["to_edge"]]["from_node"]
        for connection in network["connections"]
    )


def test_every_edge_length_matches_polyline_distance_within_one_centimetre():
    network = load_preset_network(flyover_enabled=True)

    for edge in network["edges"]:
        points = edge["polyline"]
        measured = sum(
            hypot(right[0] - left[0], right[1] - left[1])
            for left, right in zip(points, points[1:])
        )
        assert abs(edge["length"] - measured) <= 0.01, edge["id"]


def test_validator_rejects_connection_with_mismatched_endpoint_nodes():
    network = load_preset_network(flyover_enabled=True)
    broken = deepcopy(network)
    broken["connections"][0]["to_edge"] = "a_j2_e"

    assert any("mismatched endpoint nodes" in error for error in validate_network(broken))


def test_validator_rejects_edge_length_outside_polyline_tolerance():
    network = load_preset_network(flyover_enabled=True)
    broken = deepcopy(network)
    broken["edges"][0]["length"] += 0.02

    assert any("differs from polyline length" in error for error in validate_network(broken))


def test_enabled_flyover_has_west_to_east_route_via_f_e():
    network = load_preset_network(flyover_enabled=True)
    route = find_route(network, "W", "E", required_edge="f_e")

    assert route is not None
    assert "f_e" in route
    assert route[0] == "a_w_d1"
    assert route[-1] == "a_j2_e"


def test_enabled_flyover_has_correct_westbound_route_via_f_w():
    network = load_preset_network(flyover_enabled=True)
    route = find_route(network, "E", "W", required_edge="f_w")

    assert route is not None
    assert route == ["a_e_j2", "a_j2_d2", "r_w_on", "f_w", "r_w_off", "a_d1_w"]


def test_disabled_flyover_removes_all_flyover_edges_connections_and_routes():
    network = load_preset_network(flyover_enabled=False)
    route = find_route(network, "W", "E")
    edge_ids = {edge["id"] for edge in network["edges"]}
    connection_ids = {
        edge_id
        for connection in network["connections"]
        for edge_id in (connection["from_edge"], connection["to_edge"])
    }

    assert route is not None
    assert "f_e" not in route
    assert not any(edge_id.startswith("r_") or edge_id.startswith("f_") for edge_id in edge_ids)
    assert not any(edge_id.startswith("r_") or edge_id.startswith("f_") for edge_id in connection_ids)
    assert route == ["a_w_d1", "a_d1_j1", "a_j1_d2", "a_d2_j2", "a_j2_e"]


def test_signal_cycle_sums_to_80_seconds_and_yellow_is_closed_for_entry():
    signal = {"cycle_s": 80.0, "green_s": 54.0, "yellow_s": 2.0, "red_s": 24.0}

    assert signal["green_s"] + signal["yellow_s"] + signal["red_s"] == signal["cycle_s"]
    assert signal_phase_at(signal, 53.9) == "green"
    assert signal_phase_at(signal, 54.0) == "yellow"
    assert not may_enter_junction(signal_phase_at(signal, 54.0), already_past_stop_line=False)
    assert may_enter_junction(signal_phase_at(signal, 54.0), already_past_stop_line=True)
    assert signal_phase_at(signal, 56.0) == "red"
    assert signal_phase_at(signal, 80.0) == "green"


def test_route_share_validates_available_keys_and_sum():
    normalized = normalize_route_share(
        {"through": 0.6, "flyover": 0.4},
        available_routes={"through", "flyover"},
        flyover_enabled=True,
    )

    assert normalized == {"through": 0.6, "flyover": 0.4}

    with pytest.raises(ValueError, match="sum to 1"):
        normalize_route_share(
            {"through": 0.6, "flyover": 0.3},
            available_routes={"through", "flyover"},
            flyover_enabled=True,
        )

    with pytest.raises(ValueError, match="unavailable route"):
        normalize_route_share(
            {"through": 0.6, "flyover": 0.4},
            available_routes={"through"},
            flyover_enabled=True,
        )

    within_tolerance = normalize_route_share(
        {"through": 0.6, "flyover": 0.405},
        available_routes={"through", "flyover"},
        flyover_enabled=True,
    )
    assert sum(within_tolerance.values()) == pytest.approx(1.0)

    with pytest.raises(ValueError, match="sum to 1"):
        normalize_route_share(
            {"through": 0.6, "flyover": 0.411},
            available_routes={"through", "flyover"},
            flyover_enabled=True,
        )


def test_disabled_flyover_share_redistributes_to_remaining_routes():
    normalized = normalize_route_share(
        {"through": 0.6, "flyover": 0.4},
        available_routes={"through"},
        flyover_enabled=False,
    )

    assert normalized == {"through": 1.0}

    all_flyover = normalize_route_share(
        {"flyover": 1.0},
        available_routes={"through"},
        flyover_enabled=False,
    )
    assert all_flyover == {"through": 1.0}


def test_scenario_validator_checks_signal_cycle_sum_and_route_share():
    network = load_preset_network(flyover_enabled=True)
    scenario_path = Path(__file__).resolve().parents[2] / "schemas" / "scenarios" / "demo_v1.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))

    assert validate_scenario(scenario, network) == []
    broken = deepcopy(scenario)
    broken["signals"][0]["red_s"] = 23.0
    errors = validate_scenario(broken, network)
    assert any("cycle_s must equal" in error for error in errors)

    bad_share = deepcopy(scenario)
    bad_share["demand"][0]["route_share"] = {"through": 0.6, "flyover": 0.3}
    errors = validate_scenario(bad_share, network)
    assert any("sum to 1" in error for error in errors)


def test_scenario_validator_applies_disabled_flyover_share_redistribution():
    network = load_preset_network(flyover_enabled=False)
    scenario_path = Path(__file__).resolve().parents[2] / "schemas" / "scenarios" / "demo_v1.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))

    assert validate_scenario(scenario, network) == []


def test_ramp_connections_feed_single_lane_from_all_arterial_lanes():
    network = load_preset_network(flyover_enabled=True)
    on_ramp = next(
        connection for connection in network["connections"]
        if connection["from_edge"] == "a_w_d1" and connection["to_edge"] == "r_e_on"
    )

    assert on_ramp["lanes"] == [0, 0, 0]

    westbound_on_ramp = next(
        connection for connection in network["connections"]
        if connection["from_edge"] == "a_j2_d2" and connection["to_edge"] == "r_w_on"
    )
    assert westbound_on_ramp["lanes"] == [0, 0, 0]
