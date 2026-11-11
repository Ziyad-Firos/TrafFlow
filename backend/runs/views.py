import gzip
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from engine.network import load_preset_network
from engine.simulation import run_simulation
from engine.version import ENGINE_VERSION
from backend.runs.hashing import input_hash
from backend.runs.models import Run
from backend.runs.serializers import RunCreateSerializer


ROOT = Path(__file__).resolve().parents[2]
PRESET_SCENARIO = ROOT / "schemas" / "scenarios" / "demo_v1.json"
NETWORK_ID = "iisc_two_junctions_v1"


def _scenario_template() -> dict[str, Any]:
    return json.loads(PRESET_SCENARIO.read_text(encoding="utf-8"))


def _summary(result: Any) -> dict[str, Any]:
    frames = result.frames
    total_speed = sum(frames["v"])
    sample_count = len(frames["v"])
    counts_by_time: Counter[float] = Counter()
    queue_by_time: Counter[float] = Counter()
    ramp_queue_by_time: Counter[float] = Counter()
    for sample_time, edge_id, speed in zip(frames["t"], frames["edge"], frames["v"]):
        if speed < 1.0:
            queue_by_time[sample_time] += 1
        if edge_id == "r_e_on":
            counts_by_time[sample_time] += 1
            if speed < 1.0:
                ramp_queue_by_time[sample_time] += 1
    trips = result.trip_records
    mean_travel_time = (
        sum(trip.travel_time_s for trip in trips) / len(trips) if trips else 0.0
    )
    data = json.loads(result.summary_bytes())
    data.update(
        {
            "engine_version": result.engine_version,
            "seed": result.seed,
            "throughput_vph": result.j1_discharge_count * 3600 / result.duration_s,
            "mean_travel_time_s": mean_travel_time,
            "mean_delay_s": result.mean_delay_s,
            "max_queue": max(queue_by_time.values(), default=0),
            "max_ramp_queue": max(ramp_queue_by_time.values(), default=0),
            "max_ramp_occupancy": max(counts_by_time.values(), default=0),
            "mean_speed_mps": total_speed / sample_count if sample_count else 0.0,
            "duration_ms": round(result.elapsed_s * 1000),
        }
    )
    return data


class NetworkListView(APIView):
    def get(self, request):
        network = load_preset_network(flyover_enabled=True)
        return Response([{"id": network["id"], "name": "IISc two-junction arterial", "schema_version": network["schema_version"]}])


class NetworkDetailView(APIView):
    def get(self, request, network_id: str):
        if network_id != NETWORK_ID:
            return Response({"detail": "Network not found."}, status=status.HTTP_404_NOT_FOUND)
        flyover = request.query_params.get("flyover_enabled", "true").lower() != "false"
        return Response(load_preset_network(flyover_enabled=flyover))


class ScenarioListView(APIView):
    def get(self, request):
        scenario = _scenario_template()
        return Response([{"id": "demo_v1", "name": "Arterial rush hour", "scenario": scenario}])


class RunListCreateView(APIView):
    throttle_classes = [AnonRateThrottle]

    def get_throttles(self):
        return [throttle() for throttle in self.throttle_classes] if self.request.method == "POST" else []

    def get(self, request):
        return Response([
            {"run_id": str(run.id), "status": run.status, "created_at": run.created_at.isoformat(),
             "summary": {key: run.result_summary.get(key) for key in (
                 "throughput_vph", "mean_travel_time_s", "mean_delay_s", "max_queue", "mean_speed_mps"
             )}}
            for run in Run.objects.filter(status="done")[:20]
        ])

    def post(self, request):
        serializer = RunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scenario = serializer.validated_data["scenario_json"]
        seed = serializer.validated_data["seed"]
        network = load_preset_network(
            flyover_enabled=scenario.get("network_options", {}).get("flyover_enabled", True)
        )
        digest = input_hash(network=network, scenario=scenario, seed=seed, engine_version=ENGINE_VERSION)
        cached = Run.objects.filter(input_hash=digest, status="done").first()
        if cached:
            return Response({"run_id": str(cached.id), "status": cached.status, "cached": True,
                             "summary": cached.result_summary}, status=status.HTTP_200_OK)

        started = time.perf_counter()
        try:
            result = run_simulation(scenario, network, max_runtime_s=30.0)
        except TimeoutError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except (AssertionError, ValueError, KeyError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        elapsed = time.perf_counter() - started
        summary = _summary(result)
        frames_gzip = gzip.compress(
            json.dumps(result.frames, separators=(",", ":"), allow_nan=False).encode("utf-8"),
            compresslevel=9,
            mtime=0,
        )
        run, created = Run.objects.get_or_create(
            input_hash=digest,
            defaults={
                "status": "done",
                "duration_ms": round(elapsed * 1000),
                "scenario_json": scenario,
                "result_summary": summary,
                "result_frames": frames_gzip,
            },
        )
        return Response(
            {"run_id": str(run.id), "status": run.status, "cached": not created,
             "summary": run.result_summary},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class RunDetailView(APIView):
    def get(self, request, run_id):
        run = get_object_or_404(Run, pk=run_id, status="done")
        payload = {
            "schema_version": "1.0",
            "engine_version": run.result_summary.get("engine_version", ENGINE_VERSION),
            "seed": run.scenario_json["seed"],
            "frames_format": "json-v1",
            "summary": run.result_summary,
            "frames": json.loads(gzip.decompress(bytes(run.result_frames))),
        }
        response = HttpResponse(
            gzip.compress(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8"), compresslevel=6),
            content_type="application/json",
        )
        response["Content-Encoding"] = "gzip"
        response["Cache-Control"] = "private, max-age=60"
        return response
