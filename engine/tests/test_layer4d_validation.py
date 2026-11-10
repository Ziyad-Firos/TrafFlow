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
def five_minute_all_through():
    scenario = _demo()
    scenario["demand"][0]["route_share"] = {"through": 1.0}
    network = load_preset_network(flyover_enabled=True)
    return run_simulation(scenario, network)


@pytest.fixture(scope="module")
def five_minute_overload():
    scenario = _demo()
    scenario["demand"][0]["vehicles_per_hour"] = 6000.0
    network = load_preset_network(flyover_enabled=True)
    return run_simulation(scenario, network)


def test_s6_diagnostic_records_j1_discharge_below_target_band(
    five_minute_all_through,
):
    measured = five_minute_all_through.j1_discharge_count * 3600 / five_minute_all_through.duration_s
    assert five_minute_all_through.j1_discharge_count == 143
    assert measured == 1716.0


def test_m6_diagnostic_separates_flyover_route_choices_from_spawned_vehicles(five_minute_on):
    assert five_minute_on.requested_flyover_count == 133
    assert five_minute_on.spawned_flyover_count == 108
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
    assert reduction == pytest.approx(0.08070557887886058, abs=1e-9)
    assert five_minute_on.mean_delay_s == pytest.approx(25.3622222222, abs=1e-6)
    assert five_minute_off.mean_delay_s == pytest.approx(27.588790914, abs=1e-6)


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
