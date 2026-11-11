"""Deterministic end-to-end runner for the pure-Python traffic engine."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from engine.invariants import check_no_overlap
from engine.metrics import RunMetrics
from engine.movement import step_network
from engine.recording import FrameColumns, FrameRecorder
from engine.spawning import SpawnRecord, SpawnState, generate_spawn_schedule, attempt_due_spawns
from engine.state import LanesByEdge, Vehicle
from engine.version import ENGINE_VERSION


@dataclass(frozen=True, slots=True)
class TripRecord:
    vehicle_id: int
    route: tuple[str, ...]
    departure_time_s: float
    arrival_time_s: float
    travel_time_s: float
    free_flow_time_s: float

    @property
    def delay_s(self) -> float:
        return self.travel_time_s - self.free_flow_time_s


@dataclass(frozen=True, slots=True)
class SimulationResult:
    engine_version: str
    seed: int
    duration_s: float
    dt_s: float
    steps: int
    requested_count: int
    requested_flyover_count: int
    spawned_count: int
    spawned_flyover_count: int
    active_before_j1_count: int
    pending_count: int
    completed_count: int
    active_count: int
    delayed_spawns: int
    delayed_attempts: int
    spawn_records: tuple[SpawnRecord, ...]
    trip_records: tuple[TripRecord, ...]
    frames: FrameColumns
    j1_discharge_count: int
    j1_crossing_times_s: tuple[float, ...]
    overlap_checks: int
    overlap_violations: int
    cumulative_distance_m: float
    speed_integral_m: float
    elapsed_s: float

    @property
    def mean_delay_s(self) -> float:
        if not self.trip_records:
            return 0.0
        return sum(trip.delay_s for trip in self.trip_records) / len(self.trip_records)

    @property
    def conservation_error_m(self) -> float:
        return abs(self.cumulative_distance_m - self.speed_integral_m)

    @property
    def steps_per_second(self) -> float:
        return self.steps / self.elapsed_s if self.elapsed_s > 0.0 else 0.0

    @property
    def conservation_error_count(self) -> int:
        return abs(
            self.spawned_count
            - self.j1_discharge_count
            - self.spawned_flyover_count
            - self.active_before_j1_count
        )

    @property
    def requested_by_route(self) -> dict[str, int]:
        return {
            "through": self.requested_count - self.requested_flyover_count,
            "flyover": self.requested_flyover_count,
        }

    @property
    def spawned_by_route(self) -> dict[str, int]:
        return {
            "through": self.spawned_count - self.spawned_flyover_count,
            "flyover": self.spawned_flyover_count,
        }

    def summary_bytes(self) -> bytes:
        """Return deterministic summary bytes; wall-clock runtime is excluded."""
        summary = {
            "duration_s": round(self.duration_s, 6),
            "dt_s": round(self.dt_s, 6),
            "steps": self.steps,
            "requested_count": self.requested_count,
            "requested_flyover_count": self.requested_flyover_count,
            "spawned_count": self.spawned_count,
            "spawned_flyover_count": self.spawned_flyover_count,
            "active_before_j1_count": self.active_before_j1_count,
            "pending_count": self.pending_count,
            "completed_count": self.completed_count,
            "active_count": self.active_count,
            "delayed_spawns": self.delayed_spawns,
            "delayed_attempts": self.delayed_attempts,
            "j1_discharge_count": self.j1_discharge_count,
            "measurement_window": {
                "start_time_s": 0.0,
                "end_time_s": round(self.duration_s, 6),
                "duration_s": round(self.duration_s, 6),
            },
            "requested_by_route": self.requested_by_route,
            "spawned_by_route": self.spawned_by_route,
            "conservation": {
                "spawned": self.spawned_count,
                "j1_crossings": self.j1_discharge_count,
                "flyover_users": self.spawned_flyover_count,
                "active_on_network": self.active_before_j1_count,
                "unaccounted": self.conservation_error_count,
            },
            "overlap_checks": self.overlap_checks,
            "overlap_violations": self.overlap_violations,
            "cumulative_distance_m": round(self.cumulative_distance_m, 6),
            "speed_integral_m": round(self.speed_integral_m, 6),
            "spawn_records": [
                [r.arrival_time_s, r.spawned_at_s, r.vehicle_id, list(r.route), r.lane,
                 r.speed_mps, r.vehicle_type, r.demand_index, r.arrival_index]
                for r in self.spawn_records
            ],
            "trip_records": [
                [t.vehicle_id, list(t.route), t.departure_time_s, t.arrival_time_s,
                 t.travel_time_s, t.free_flow_time_s]
                for t in self.trip_records
            ],
        }
        return json.dumps(summary, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

    def to_json_bytes(self) -> bytes:
        """Serialize the v1 result envelope with summary and columnar frames."""
        payload = {
            "schema_version": "1.0",
            "engine_version": self.engine_version,
            "seed": self.seed,
            "frames_format": "json-v1",
            "summary": json.loads(self.summary_bytes()),
            "frames": self.frames,
        }
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")


def run_simulation(
    scenario: dict[str, Any],
    network: dict[str, Any],
    *,
    use_reservations: bool = True,
    max_runtime_s: float | None = None,
) -> SimulationResult:
    """Precompute demand, then run fixed-dt movement with stepwise invariants."""
    started = time.perf_counter()
    dt_s = float(scenario["dt_s"])
    duration_s = float(scenario["duration_s"])
    steps = round(duration_s / dt_s)
    if abs(steps * dt_s - duration_s) > 1e-8:
        raise ValueError("duration_s must be an integer multiple of dt_s")

    schedule = generate_spawn_schedule(scenario, network)
    spawn_state = SpawnState(schedule=schedule)
    edges = {edge["id"]: edge for edge in network["edges"]}
    vehicle_types = scenario["vehicle_types"]
    signal_configs = {signal["node_id"]: signal for signal in scenario.get("signals", [])}

    vehicles: dict[int, Vehicle] = {}
    lanes: LanesByEdge = {
        edge_id: [[] for _ in range(edge["lanes"])]
        for edge_id, edge in edges.items()
    }
    vehicle_type_ids: dict[int, str] = {}
    departure_by_id: dict[int, float] = {}
    merge_state: dict[tuple[str, int], tuple[str, int]] = {}
    signal_commitments: dict[int, str] = {}
    trips: list[TripRecord] = []
    j1_crossed_ids: set[int] = set()
    j1_crossing_times_s: list[float] = []
    metrics = RunMetrics()
    frame_recorder = FrameRecorder(
        dt_s=dt_s,
        record_interval_s=float(scenario["record_interval_s"]),
    )

    j1_signal = signal_configs.get("J1")
    controlled_j1_edges = set(j1_signal.get("controlled_edges", [])) if j1_signal else set()
    if j1_signal and not controlled_j1_edges:
        controlled_j1_edges = {
            edge["id"] for edge in network["edges"]
            if edge.get("to_node") == "J1"
        }

    for step_index in range(steps):
        if max_runtime_s is not None and time.perf_counter() - started > max_runtime_s:
            raise TimeoutError(f"simulation exceeded {max_runtime_s:.1f} seconds")
        now_s = round(step_index * dt_s, 10)
        spawned_now = attempt_due_spawns(
            now_s, spawn_state, vehicles, lanes, network, scenario
        )
        for record in spawned_now:
            vehicle_type_ids[record.vehicle_id] = record.vehicle_type
            departure_by_id[record.vehicle_id] = record.spawned_at_s

        # Samples are taken at the start of due steps, including t=0. This
        # yields t=0.0..duration-interval on an exact cadence, without a
        # synthetic frame at the terminal time.
        frame_recorder.record_if_due(
            step_index=step_index, time_s=now_s, vehicles=vehicles
        )

        before = {
            vehicle_id: (vehicle.edge_id, vehicle.s)
            for vehicle_id, vehicle in vehicles.items()
        }
        step_network(
            vehicles,
            lanes,
            network,
            vehicle_type_ids,
            vehicle_types,
            dt=dt_s,
            use_reservations=use_reservations,
            merge_state=merge_state,
            time_s=now_s,
            signals=signal_configs,
            signal_commitments=signal_commitments,
        )

        step_distance_m = 0.0
        step_speed_integral_m = 0.0
        step_j1_crossings = 0
        for vehicle_id, (old_edge_id, old_s) in before.items():
            vehicle = vehicles[vehicle_id]
            old_edge = edges[old_edge_id]
            new_edge_id, new_s = vehicle.edge_id, vehicle.s
            if (
                old_edge_id in controlled_j1_edges
                and old_s <= old_edge["length"] < new_s
            ):
                step_j1_crossings += 1
                j1_crossed_ids.add(vehicle_id)
                j1_crossing_times_s.append(round(now_s + dt_s, 10))

            if new_edge_id == old_edge_id:
                step_distance_m += new_s - old_s
            else:
                step_distance_m += old_edge["length"] - old_s + new_s
            step_speed_integral_m += vehicle.v * dt_s

        violations = check_no_overlap(vehicles, lanes)
        metrics.record_step(
            distance_m=step_distance_m,
            speed_integral_m=step_speed_integral_m,
            j1_crossings=step_j1_crossings,
            overlap_checks=1,
            overlap_violations=len(violations),
        )
        if violations:
            involved_ids = {
                vehicle_id
                for violation in violations
                for vehicle_id in (violation.follower_id, violation.leader_id)
            }
            details = {
                vehicle_id: {
                    "edge_id": vehicles[vehicle_id].edge_id,
                    "lane": vehicles[vehicle_id].lane,
                    "s": vehicles[vehicle_id].s,
                    "v": vehicles[vehicle_id].v,
                    "length": vehicles[vehicle_id].length,
                    "route": vehicles[vehicle_id].route,
                }
                for vehicle_id in sorted(involved_ids)
            }
            raise AssertionError(
                f"no-overlap invariant failed at t={now_s + dt_s:.1f}: "
                f"{violations!r}; vehicles={details!r}"
            )

        finished = [
            vehicle_id for vehicle_id, vehicle in vehicles.items()
            if vehicle.route[-1] == vehicle.edge_id
            and vehicle.s >= edges[vehicle.edge_id]["length"]
        ]
        for vehicle_id in sorted(finished):
            vehicle = vehicles.pop(vehicle_id)
            vehicle_type_ids.pop(vehicle_id)
            departure_time = departure_by_id.pop(vehicle_id)
            route = tuple(vehicle.route)
            free_flow = sum(edges[edge_id]["length"] / edges[edge_id]["speed_limit"] for edge_id in route)
            arrival_time = now_s + dt_s
            trips.append(TripRecord(
                vehicle_id=vehicle_id,
                route=route,
                departure_time_s=departure_time,
                arrival_time_s=arrival_time,
                travel_time_s=arrival_time - departure_time,
                free_flow_time_s=free_flow,
            ))
        if finished:
            finished_set = set(finished)
            for edge_lanes in lanes.values():
                for lane in edge_lanes:
                    lane[:] = [vehicle_id for vehicle_id in lane if vehicle_id not in finished_set]

    # Requests timestamped in the final simulation interval are due at t=duration.
    final_spawns = attempt_due_spawns(
        duration_s, spawn_state, vehicles, lanes, network, scenario
    )
    for record in final_spawns:
        vehicle_type_ids[record.vehicle_id] = record.vehicle_type
        departure_by_id[record.vehicle_id] = record.spawned_at_s
    final_violations = check_no_overlap(vehicles, lanes)
    if final_violations:
        raise AssertionError(f"no-overlap invariant failed at t={duration_s:.1f}: {final_violations!r}")

    elapsed_s = time.perf_counter() - started
    active_before_j1_count = sum(
        1
        for vehicle in vehicles.values()
        if "f_e" not in vehicle.route
        and "a_d1_j1" in vehicle.route
        and vehicle.id not in j1_crossed_ids
    )
    return SimulationResult(
        engine_version=ENGINE_VERSION,
        seed=int(scenario["seed"]),
        duration_s=duration_s,
        dt_s=dt_s,
        steps=steps,
        requested_count=len(schedule),
        requested_flyover_count=sum("f_e" in request.route for request in schedule),
        spawned_count=spawn_state.successful_spawns,
        spawned_flyover_count=sum("f_e" in record.route for record in spawn_state.records),
        active_before_j1_count=active_before_j1_count,
        pending_count=len(spawn_state.pending),
        completed_count=len(trips),
        active_count=len(vehicles),
        delayed_spawns=spawn_state.delayed_spawns,
        delayed_attempts=spawn_state.delayed_attempts,
        spawn_records=tuple(spawn_state.records),
        trip_records=tuple(sorted(trips, key=lambda trip: trip.vehicle_id)),
        frames=frame_recorder.frames,
        j1_discharge_count=metrics.j1_discharge_count,
        j1_crossing_times_s=tuple(j1_crossing_times_s),
        overlap_checks=metrics.overlap_checks,
        overlap_violations=metrics.overlap_violations,
        cumulative_distance_m=metrics.cumulative_distance_m,
        speed_integral_m=metrics.speed_integral_m,
        elapsed_s=elapsed_s,
    )
