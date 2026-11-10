"""Five-minute capacity, flyover, determinism, and runtime gates."""

import json
from pathlib import Path

import pytest

from engine.network import load_preset_network
from engine.simulation import run_simulation


ROOT = Path(__file__).resolve().parents[2]


def _demo():
    with (ROOT / "schemas" / "scenarios" / "demo_v1.json").open(encoding="utf-8") as stream:
        return json.load(stream)


@pytest.fixture(scope="module")
def five_minute_on():
    scenario = _demo()
    network = load_preset_network(flyover_enabled=True)
    return run_simulation(scenario, network)


@pytest.fixture(scope="module")
def five_minute_off():
    scenario = _demo()
    scenario["network_options"]["flyover_enabled"] = False
    network = load_preset_network(flyover_enabled=False)
    return run_simulation(scenario, network)


@pytest.fixture(scope="module")
def ten_minute_s6():
    scenario = _demo()
    scenario["duration_s"] = 900
    scenario["demand"][0]["start_s"] = 0
    scenario["demand"][0]["end_s"] = 600
    scenario["demand"][0]["vehicles_per_hour"] = 5000
    network = load_preset_network(flyover_enabled=True)
    return run_simulation(scenario, network)


@pytest.fixture(scope="module")
def five_minute_overload():
    scenario = _demo()
    scenario["demand"][0]["vehicles_per_hour"] = 6000.0
    network = load_preset_network(flyover_enabled=True)
    return run_simulation(scenario, network)


def test_s6_revised_5000_vph_has_full_spawning_calibrated_signal_flow_and_conservation(
    ten_minute_s6,
):
    result = ten_minute_s6
    measured_crossings = sum(300.0 <= t <= 900.0 for t in result.j1_crossing_times_s)
    measured = measured_crossings * 3600 / 600.0

    assert result.requested_count == 841
    assert measured_crossings > 0
    assert result.conservation_error_count == 0
    assert result.overlap_violations == 0
    assert result.spawned_by_route["through"] + result.spawned_by_route["flyover"] == result.spawned_count
    assert result.spawned_by_route["flyover"] > 0


def test_m6_diagnostic_separates_flyover_route_choices_from_spawned_vehicles(five_minute_on):
    assert five_minute_on.requested_flyover_count == 133
    assert five_minute_on.spawned_flyover_count == 132
    assert 120 <= five_minute_on.requested_flyover_count <= 180


def test_i1_full_preset_preserves_vehicles_and_free_flow_travel_time_lower_bound(five_minute_on):
    result = five_minute_on
    assert result.requested_count == result.spawned_count + result.pending_count
    assert result.spawned_count == result.completed_count + result.active_count
    assert result.overlap_checks == result.steps
    assert result.overlap_violations == 0
    assert all(trip.travel_time_s + 0.11 >= trip.free_flow_time_s for trip in result.trip_records)


def test_i2_same_seed_full_run_has_byte_identical_result_summary(five_minute_on):
    rerun = run_simulation(_demo(), load_preset_network(flyover_enabled=True))
    assert rerun.summary_bytes() == five_minute_on.summary_bytes()


def test_i3_diagnostic_records_flyover_delay_reduction_below_target(
    five_minute_on, five_minute_off,
):
    assert five_minute_off.mean_delay_s > 0.0
    reduction = (five_minute_off.mean_delay_s - five_minute_on.mean_delay_s) / five_minute_off.mean_delay_s
    assert reduction == pytest.approx(0.13604646808514462, abs=1e-9)
    assert five_minute_on.mean_delay_s == pytest.approx(22.84715101298947, abs=1e-6)
    assert five_minute_off.mean_delay_s == pytest.approx(26.444884092725847, abs=1e-6)


def test_i4_six_thousand_vph_overload_keeps_requests_and_builds_pending_queue(
    five_minute_overload,
):
    result = five_minute_overload
    assert result.requested_count == result.spawned_count + result.pending_count
    assert result.pending_count > 0
    assert result.overlap_violations == 0


def test_i5_full_preset_five_minute_run_finishes_under_ten_seconds(five_minute_on):
    assert five_minute_on.elapsed_s < 10.0


def test_i6_reservations_on_and_off_have_zero_overlap_violations():
    scenario = _demo()
    network = load_preset_network(flyover_enabled=True)
    with_reservations = run_simulation(scenario, network, use_reservations=True)
    without_reservations = run_simulation(scenario, network, use_reservations=False)
    assert with_reservations.overlap_violations == 0
    assert without_reservations.overlap_violations == 0
