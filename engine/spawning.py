"""Deterministic demand schedule generation and origin insertion."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from collections.abc import MutableMapping
from typing import Any

from engine.network import find_route, normalize_route_share
from engine.state import LanesByEdge, Vehicle


@dataclass(frozen=True, slots=True)
class SpawnRequest:
    """One immutable arrival request with its route fixed before simulation."""

    timestamp_s: float
    route: tuple[str, ...]
    vehicle_type: str
    origin_node: str
    demand_index: int
    arrival_index: int


@dataclass(frozen=True, slots=True)
class SpawnRecord:
    arrival_time_s: float
    spawned_at_s: float
    vehicle_id: int
    route: tuple[str, ...]
    lane: int
    speed_mps: float


@dataclass(slots=True)
class SpawnState:
    """Run-local sorted schedule, pending requests, and spawn accounting."""

    schedule: list[SpawnRequest]
    pending: list[SpawnRequest] = field(default_factory=list)
    next_schedule_index: int = 0
    next_vehicle_id: int = 1
    successful_spawns: int = 0
    delayed_spawns: int = 0
    delayed_attempts: int = 0
    delayed_request_keys: set[tuple[int, int]] = field(default_factory=set)
    records: list[SpawnRecord] = field(default_factory=list)


def sample_poisson(mean: float, rng: random.Random) -> int:
    """Draw an exact Poisson variate using Knuth's product method.

    Large means are split into independent smaller Poisson draws so the product
    remains numerically stable. The project's largest v1 mean is well below 700.
    """
    if not math.isfinite(mean) or mean < 0.0:
        raise ValueError("Poisson mean must be finite and non-negative")
    if mean == 0.0:
        return 0
    if mean > 700.0:
        parts = math.ceil(mean / 30.0)
        return sum(sample_poisson(mean / parts, rng) for _ in range(parts))
    limit = math.exp(-mean)
    product = 1.0
    count = 0
    while product > limit:
        count += 1
        product *= rng.random()
    return count - 1


def routes_for_demand(
    demand: dict[str, Any],
    network: dict[str, Any],
    *,
    flyover_enabled: bool,
) -> dict[str, tuple[str, ...]]:
    """Resolve named route choices to immutable edge sequences."""
    edge_by_id = {edge["id"]: edge for edge in network["edges"]}
    available = {"through"}
    if (
        flyover_enabled
        and demand.get("origin_node") == "W"
        and demand.get("destination_node") == "E"
        and "f_e" in edge_by_id
    ):
        available.add("flyover")
    raw_shares = demand.get("route_share", {"through": 1.0})
    shares = normalize_route_share(
        raw_shares,
        available_routes=available,
        flyover_enabled=flyover_enabled,
    )

    routes: dict[str, tuple[str, ...]] = {}
    if shares.get("through", 0.0) > 0.0:
        forbidden = {
            edge_id for edge_id, edge in edge_by_id.items()
            if edge.get("type") in {"flyover", "ramp"}
        }
        route = find_route(
            network,
            demand["origin_node"],
            demand["destination_node"],
            forbidden_edges=forbidden,
        )
        if route is None:
            raise ValueError("no through route for demand OD pair")
        routes["through"] = tuple(route)
    if shares.get("flyover", 0.0) > 0.0:
        route = find_route(
            network,
            demand["origin_node"],
            demand["destination_node"],
            required_edge="f_e",
        )
        if route is None:
            raise ValueError("flyover share requested but no route via f_e exists")
        routes["flyover"] = tuple(route)
    if not routes:
        raise ValueError("route_share has no positive available route")
    return routes


def choose_route(route_shares: dict[str, float], rng: random.Random) -> str:
    """Sample one route label from normalized shares in sorted-key order."""
    total = sum(route_shares.values())
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("route shares must have a positive finite total")
    draw = rng.random() * total
    cumulative = 0.0
    for route in sorted(route_shares):
        cumulative += route_shares[route]
        if draw < cumulative:
            return route
    return sorted(route_shares)[-1]


def generate_spawn_schedule(
    scenario: dict[str, Any], network: dict[str, Any]
) -> list[SpawnRequest]:
    """Precompute Poisson counts, uniform arrival times, then route draws.

    RNG draw order is fixed: counts in demand-list order; timestamps in demand
    and arrival-index order; then route labels in globally sorted timestamp
    order (stable ties use demand index and arrival index). This RNG is local to
    schedule creation and is never used in the simulation step loop.
    """
    rng = random.Random(scenario["seed"])
    demand_specs = scenario.get("demand", [])
    duration_s = float(scenario["duration_s"])
    flyover_enabled = bool(scenario.get("network_options", {}).get("flyover_enabled", False))

    windows: list[tuple[float, float, float, int]] = []
    counts: list[int] = []
    for demand_index, demand in enumerate(demand_specs):
        start_s = max(0.0, float(demand["start_s"]))
        end_s = min(duration_s, float(demand["end_s"]))
        window_s = max(0.0, end_s - start_s)
        mean = float(demand["vehicles_per_hour"]) * window_s / 3600.0
        windows.append((start_s, end_s, mean, demand_index))
        counts.append(sample_poisson(mean, rng))

    timed_arrivals: list[tuple[float, int, int]] = []
    for start_s, end_s, _mean, demand_index in windows:
        span_s = end_s - start_s
        for arrival_index in range(counts[demand_index]):
            timestamp = start_s + rng.random() * span_s
            timed_arrivals.append((timestamp, demand_index, arrival_index))
    timed_arrivals.sort(key=lambda item: (item[0], item[1], item[2]))

    route_maps = [
        routes_for_demand(demand, network, flyover_enabled=flyover_enabled)
        for demand in demand_specs
    ]
    route_shares = []
    edge_by_id = {edge["id"]: edge for edge in network["edges"]}
    for demand in demand_specs:
        available = {"through"}
        if (
            flyover_enabled
            and demand.get("origin_node") == "W"
            and demand.get("destination_node") == "E"
            and "f_e" in edge_by_id
        ):
            available.add("flyover")
        route_shares.append(normalize_route_share(
            demand.get("route_share", {"through": 1.0}),
            available_routes=available,
            flyover_enabled=flyover_enabled,
        ))

    schedule: list[SpawnRequest] = []
    for timestamp, demand_index, arrival_index in timed_arrivals:
        demand = demand_specs[demand_index]
        route_label = choose_route(route_shares[demand_index], rng)
        schedule.append(SpawnRequest(
            timestamp_s=timestamp,
            route=route_maps[demand_index][route_label],
            vehicle_type=demand["vehicle_type"],
            origin_node=demand["origin_node"],
            demand_index=demand_index,
            arrival_index=arrival_index,
        ))
    return schedule


def attempt_due_spawns(
    now_s: float,
    state: SpawnState,
    vehicles: dict[int, Vehicle],
    lanes: LanesByEdge,
    network: dict[str, Any],
    scenario: dict[str, Any],
) -> list[SpawnRecord]:
    """Submit due requests, retry pending ones, and insert eligible vehicles."""
    while (
        state.next_schedule_index < len(state.schedule)
        and state.schedule[state.next_schedule_index].timestamp_s <= now_s
    ):
        state.pending.append(state.schedule[state.next_schedule_index])
        state.next_schedule_index += 1

    edges = {edge["id"]: edge for edge in network["edges"]}
    vehicle_types = scenario["vehicle_types"]
    new_records: list[SpawnRecord] = []
    still_pending: list[SpawnRequest] = []

    for request in state.pending:
        edge_id = request.route[0]
        edge = edges[edge_id]
        vehicle_type = vehicle_types[request.vehicle_type]
        origin_lanes = lanes[edge_id]
        eligible: list[tuple[int, int]] = []
        for lane_index, lane_ids in enumerate(origin_lanes):
            if not lane_ids:
                eligible.append((0, lane_index))
                continue
            nearest = min((vehicles[vehicle_id] for vehicle_id in lane_ids), key=lambda vehicle: (vehicle.s, vehicle.id))
            required_front_distance = nearest.length + float(vehicle_type["s0_m"])
            if nearest.s >= required_front_distance:
                eligible.append((len(lane_ids), lane_index))

        if not eligible:
            request_key = (request.demand_index, request.arrival_index)
            if request_key not in state.delayed_request_keys:
                state.delayed_request_keys.add(request_key)
                state.delayed_spawns += 1
            state.delayed_attempts += 1
            still_pending.append(request)
            continue

        _occupancy, lane_index = min(eligible)
        vehicle_id = state.next_vehicle_id
        while vehicle_id in vehicles:
            vehicle_id += 1
        state.next_vehicle_id = vehicle_id + 1
        vehicle = Vehicle(
            id=vehicle_id,
            edge_id=edge_id,
            lane=lane_index,
            s=0.0,
            v=float(vehicle_type["v0_mps"]),
            length=float(vehicle_type["length_m"]),
            route=list(request.route),
        )
        vehicles[vehicle_id] = vehicle
        origin_lanes[lane_index].append(vehicle_id)
        origin_lanes[lane_index].sort(key=lambda item: (vehicles[item].s, item))
        record = SpawnRecord(
            arrival_time_s=request.timestamp_s,
            spawned_at_s=now_s,
            vehicle_id=vehicle_id,
            route=request.route,
            lane=lane_index,
            speed_mps=vehicle.v,
        )
        new_records.append(record)
        state.records.append(record)
        state.successful_spawns += 1

    state.pending = still_pending
    return new_records
