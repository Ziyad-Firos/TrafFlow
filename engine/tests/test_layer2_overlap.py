"""Synthetic-state tests for the pure lane overlap checker."""

from engine.state import Vehicle
from engine.invariants import check_no_overlap


def _vehicle(vehicle_id: int, s: float, length: float = 4.5) -> Vehicle:
    return Vehicle(
        id=vehicle_id,
        edge_id="edge-1",
        lane=0,
        s=s,
        v=0.0,
        length=length,
        route=["edge-1"],
    )


def test_empty_lane_has_no_overlap_violations():
    vehicles = {}
    lanes = {"edge-1": [[]]}

    assert check_no_overlap(vehicles, lanes) == []


def test_single_vehicle_lane_has_no_overlap_violations():
    vehicles = {1: _vehicle(1, s=20.0)}
    lanes = {"edge-1": [[1]]}

    assert check_no_overlap(vehicles, lanes) == []


def test_two_vehicles_with_a_gap_have_no_overlap_violations():
    vehicles = {1: _vehicle(1, s=90.0), 2: _vehicle(2, s=100.0)}
    lanes = {"edge-1": [[1, 2]]}

    assert check_no_overlap(vehicles, lanes) == []


def test_two_vehicles_touching_exactly_have_no_overlap_violations():
    vehicles = {1: _vehicle(1, s=95.5), 2: _vehicle(2, s=100.0)}
    lanes = {"edge-1": [[1, 2]]}

    assert check_no_overlap(vehicles, lanes) == []


def test_deliberate_two_vehicle_overlap_reports_exact_pair_and_depth():
    vehicles = {1: _vehicle(1, s=96.0), 2: _vehicle(2, s=100.0)}
    lanes = {"edge-1": [[1, 2]]}

    violations = check_no_overlap(vehicles, lanes)

    assert len(violations) == 1
    assert violations[0].follower_id == 1
    assert violations[0].leader_id == 2
    assert abs(violations[0].overlap_m - 0.5) <= 1e-6


def test_three_evenly_spaced_vehicles_have_no_overlap_violations():
    vehicles = {
        1: _vehicle(1, s=80.0),
        2: _vehicle(2, s=90.0),
        3: _vehicle(3, s=100.0),
    }
    lanes = {"edge-1": [[1, 2, 3]]}

    assert check_no_overlap(vehicles, lanes) == []


def test_three_vehicle_lane_reports_only_the_middle_pair_overlap():
    vehicles = {
        1: _vehicle(1, s=85.0),
        2: _vehicle(2, s=96.0),
        3: _vehicle(3, s=100.0),
    }
    lanes = {"edge-1": [[1, 2, 3]]}

    violations = check_no_overlap(vehicles, lanes)

    assert len(violations) == 1
    assert violations[0].follower_id == 2
    assert violations[0].leader_id == 3
    assert abs(violations[0].overlap_m - 0.5) <= 1e-6


def test_overlap_uses_actual_leader_length_for_mixed_vehicle_lengths():
    vehicles = {
        1: _vehicle(1, s=90.2, length=4.5),
        2: _vehicle(2, s=100.0, length=10.0),
    }
    lanes = {"edge-1": [[1, 2]]}

    violations = check_no_overlap(vehicles, lanes)

    assert len(violations) == 1
    assert violations[0].follower_id == 1
    assert violations[0].leader_id == 2
    assert abs(violations[0].overlap_m - 0.2) <= 1e-6
