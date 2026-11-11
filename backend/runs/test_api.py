import gzip
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from backend.runs.models import Run
from backend.runs.hashing import input_hash


ROOT = Path(__file__).resolve().parents[2]


def _scenario():
    return json.loads((ROOT / "schemas" / "scenarios" / "demo_v1.json").read_text(encoding="utf-8"))


def _fake_result():
    summary = {
        "duration_s": 300.0, "dt_s": 0.1, "steps": 3000,
        "spawned_count": 0, "spawned_by_route": {"through": 0, "flyover": 0},
        "overlap_violations": 0,
    }
    return SimpleNamespace(
        engine_version="0.1.0", seed=31,
        frames={"t": [], "id": [], "edge": [], "s": [], "lane": [], "v": []},
        trip_records=(), mean_delay_s=0.0, j1_discharge_count=0,
        duration_s=300.0, elapsed_s=0.02,
        summary_bytes=lambda: json.dumps(summary).encode(),
    )


@pytest.mark.django_db
def test_post_run_validates_executes_persists_and_returns_cached_id():
    client = APIClient()
    body = {"scenario_json": _scenario(), "seed": 31}
    with patch("backend.runs.views.run_simulation", return_value=_fake_result()) as runner:
        first = client.post("/api/runs/", body, format="json")
        second = client.post("/api/runs/", body, format="json")

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.data["run_id"] == second.data["run_id"]
    assert second.data["cached"] is True
    assert runner.call_count == 1
    assert Run.objects.count() == 1


@pytest.mark.django_db
def test_run_detail_returns_gzipped_columnar_result():
    client = APIClient()
    body = {"scenario_json": _scenario(), "seed": 32}
    with patch("backend.runs.views.run_simulation", return_value=_fake_result()):
        created = client.post("/api/runs/", body, format="json")
    response = client.get(f"/api/runs/{created.data['run_id']}/")

    assert response.status_code == 200
    assert response["Content-Encoding"] == "gzip"
    payload = json.loads(gzip.decompress(response.content))
    assert payload["frames_format"] == "json-v1"
    assert payload["frames"]["id"] == []


def test_network_scenario_and_health_endpoints_return_preset_contracts():
    client = APIClient()
    health = client.get("/health/")
    networks = client.get("/api/networks/")
    network = client.get("/api/networks/iisc_two_junctions_v1/")
    scenarios = client.get("/api/scenarios/")

    assert health.status_code == 200 and json.loads(health.content)["status"] == "ok"
    assert networks.status_code == 200 and networks.data[0]["id"] == "iisc_two_junctions_v1"
    assert network.status_code == 200 and len(network.data["edges"]) > 0
    assert scenarios.status_code == 200 and scenarios.data[0]["scenario"]["dt_s"] == 0.1


def test_run_request_rejects_wrong_schema_version():
    client = APIClient()
    scenario = _scenario()
    scenario["schema_version"] = "99.0"
    response = client.post("/api/runs/", {"scenario_json": scenario, "seed": 5}, format="json")

    assert response.status_code == 400


@pytest.mark.django_db
def test_run_timeout_is_returned_as_422():
    client = APIClient()
    with patch("backend.runs.views.run_simulation", side_effect=TimeoutError("simulation exceeded 10.0 seconds")):
        response = client.post("/api/runs/", {"scenario_json": _scenario(), "seed": 8}, format="json")

    assert response.status_code == 422
    assert "10.0 seconds" in response.data["detail"]


def test_input_hash_sorts_keys_and_rounds_float_values_to_six_places():
    network_a = {"z": 2.0000001, "a": [1.2345671]}
    network_b = {"a": [1.2345674], "z": 2.0000004}
    scenario = {"seed": 7}
    first = input_hash(network=network_a, scenario=scenario, seed=7, engine_version="1.0.0")
    second = input_hash(network=network_b, scenario=scenario, seed=7, engine_version="1.0.0")

    assert first == second
