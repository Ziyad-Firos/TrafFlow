"""Metric, sampling, and result-contract tests for Layer 5."""

import gzip
import json
from collections import Counter
from pathlib import Path
import re

import pytest

from engine.metrics import RunMetrics
from engine.network import load_preset_network
from engine.recording import FrameRecorder
from engine.simulation import run_simulation
from engine.state import Vehicle


def test_run_metrics_add_step_values_and_keep_concrete_counts():
    metrics = RunMetrics()
    metrics.record_step(
        distance_m=2.2,
        speed_integral_m=2.2,
        j1_crossings=2,
        overlap_checks=1,
        overlap_violations=0,
    )
    metrics.record_step(
        distance_m=1.1,
        speed_integral_m=1.1,
        j1_crossings=1,
        overlap_checks=1,
        overlap_violations=0,
    )

    summary = metrics.summary()

    assert summary["cumulative_distance_m"] == pytest.approx(3.3, abs=1e-12)
    assert summary["speed_integral_m"] == pytest.approx(3.3, abs=1e-12)
    assert summary["j1_discharge_count"] == 3
    assert summary["overlap_checks"] == 2
    assert summary["overlap_violations"] == 0


def test_frame_recorder_samples_every_fifth_step_at_zero_and_half_second():
    recorder = FrameRecorder(dt_s=0.1, record_interval_s=0.5)
    vehicle = Vehicle(1, "edge", 0, 0.0, 13.9, 4.5, ["edge"])
    vehicles = {1: vehicle}

    assert recorder.record_if_due(step_index=0, time_s=0.0, vehicles=vehicles)
    vehicle.s = 6.95  # 13.9 m/s * 0.5 s = 6.95 m.
    assert recorder.record_if_due(step_index=5, time_s=0.5, vehicles=vehicles)
    assert not recorder.record_if_due(step_index=6, time_s=0.6, vehicles=vehicles)

    assert recorder.frames == {
        "t": [0.0, 0.5],
        "id": [1, 1],
        "edge": ["edge", "edge"],
        "s": [0.0, 6.95],
        "lane": [0, 0],
        "v": [13.9, 13.9],
    }


def test_frame_recorder_uses_nearest_step_without_interpolating_record_time():
    recorder = FrameRecorder(dt_s=0.12, record_interval_s=0.5)
    vehicles = {1: Vehicle(1, "edge", 0, 8.0, 3.0, 4.5, ["edge"])}

    assert recorder.record_if_due(step_index=0, time_s=0.0, vehicles=vehicles)
    assert recorder.record_if_due(step_index=4, time_s=0.48, vehicles=vehicles)
    assert not recorder.record_if_due(step_index=5, time_s=0.60, vehicles=vehicles)
    assert recorder.frames["t"] == [0.0, 0.48]
    assert recorder.frames["s"] == [8.0, 8.0]


def test_result_json_separates_summary_and_columnar_frames_deterministically():
    network = {
        "schema_version": "1.0",
        "id": "empty_test",
        "geo_anchor": None,
        "nodes": [
            {"id": "W", "x": 0.0, "y": 0.0, "type": "plain"},
            {"id": "E", "x": 10.0, "y": 0.0, "type": "plain"},
        ],
        "edges": [
            {"id": "edge", "from_node": "W", "to_node": "E", "length": 10.0,
             "lanes": 1, "speed_limit": 13.9, "polyline": [[0.0, 0.0], [10.0, 0.0]],
             "type": "road"}
        ],
        "connections": [],
    }
    scenario = {
        "schema_version": "1.0",
        "network_id": "empty_test",
        "network_options": {"flyover_enabled": False},
        "duration_s": 1.0,
        "dt_s": 0.1,
        "record_interval_s": 0.5,
        "seed": 42,
        "demand": [],
        "signals": [],
        "vehicle_types": {},
        "events": [],
    }

    first = run_simulation(scenario, network)
    second = run_simulation(scenario, network)
    payload = json.loads(first.to_json_bytes())

    assert set(payload) == {
        "schema_version", "engine_version", "seed", "frames_format", "summary", "frames"
    }
    assert payload["schema_version"] == "1.0"
    assert payload["frames_format"] == "json-v1"
    assert re.fullmatch(r"\d+\.\d+\.\d+", payload["engine_version"])
    assert payload["seed"] == 42
    assert set(payload["frames"]) == {"t", "id", "edge", "s", "lane", "v"}
    assert len({len(column) for column in payload["frames"].values()}) == 1
    assert first.to_json_bytes() == second.to_json_bytes()
ROOT = Path(__file__).resolve().parents[2]


def _demo_scenario():
    return json.loads((ROOT / "schemas" / "scenarios" / "demo_v1.json").read_text(encoding="utf-8"))


def _demo_result():
    return run_simulation(
        _demo_scenario(), load_preset_network(flyover_enabled=True)
    )




def test_engine_runtime_limit_aborts_before_first_step():
    with pytest.raises(TimeoutError, match="exceeded 0.0 seconds"):
        run_simulation(
            _demo_scenario(), load_preset_network(flyover_enabled=True), max_runtime_s=0.0
        )


def test_demo_seed_summary_is_byte_identical_to_committed_golden_file():
    result = _demo_result()
    golden_path = ROOT / "engine" / "tests" / "golden" / "demo_seed_20261110_summary.json"

    assert result.summary_bytes() == golden_path.read_bytes()


def test_five_minute_columnar_payload_gzip_is_measured_below_two_megabytes():
    result = _demo_result()
    frame_counts = Counter(result.frames["t"])
    payload = result.to_json_bytes()
    compressed_size = len(gzip.compress(payload, compresslevel=9))

    assert result.requested_count == 369
    assert result.spawned_count == 366
    assert len(result.frames["id"]) == 105461
    assert len(frame_counts) == 598
    assert max(frame_counts.values()) == 332
    assert compressed_size == 985398
    assert compressed_size < 2_000_000
