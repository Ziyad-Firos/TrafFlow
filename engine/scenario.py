"""Scenario contract helpers used by the engine and Layer 1 validation."""

from __future__ import annotations

import math
from typing import Any

from engine.network import normalize_route_share


def validate_scenario(scenario: dict[str, Any], network: dict[str, Any]) -> list[str]:
    """Return scenario errors against the supplied, already-filtered network."""
    errors: list[str] = []
    if scenario.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")
    if not isinstance(scenario.get("seed"), int) or isinstance(scenario.get("seed"), bool):
        errors.append("seed must be an integer")
    for field in ("duration_s", "dt_s", "record_interval_s"):
        value = scenario.get(field)
        if not _finite_number(value) or value <= 0:
            errors.append(f"{field} must be a positive finite number")
    if scenario.get("dt_s") != 0.1:
        errors.append("dt_s must be 0.1 seconds in schema version 1.0")
    if scenario.get("record_interval_s") != 0.5:
        errors.append("record_interval_s must be 0.5 seconds in schema version 1.0")

    node_ids = {node["id"] for node in network["nodes"]}
    edge_ids = {edge["id"] for edge in network["edges"]}
    type_ids = set(scenario.get("vehicle_types", {}))
    for index, demand in enumerate(scenario.get("demand", [])):
        if demand.get("origin_node") not in node_ids or demand.get("destination_node") not in node_ids:
            errors.append(f"demand[{index}] references an unknown OD node")
        if demand.get("vehicle_type") not in type_ids:
            errors.append(f"demand[{index}] references an unknown vehicle_type")
        for field in ("vehicles_per_hour", "start_s", "end_s"):
            if not _finite_number(demand.get(field)):
                errors.append(f"demand[{index}].{field} must be finite")
        if _finite_number(demand.get("vehicles_per_hour")) and demand["vehicles_per_hour"] < 0:
            errors.append(f"demand[{index}].vehicles_per_hour must be non-negative")
        if _finite_number(demand.get("start_s")) and _finite_number(demand.get("end_s")):
            if demand["start_s"] < 0 or demand["end_s"] <= demand["start_s"]:
                errors.append(f"demand[{index}] must have 0 <= start_s < end_s")
        route_share = demand.get("route_share")
        if route_share is not None:
            origin, destination = demand.get("origin_node"), demand.get("destination_node")
            available = {"through"}
            if origin == "W" and destination == "E" and "f_e" in edge_ids:
                available.add("flyover")
            try:
                normalize_route_share(
                    route_share,
                    available_routes=available,
                    flyover_enabled="f_e" in edge_ids,
                )
            except (TypeError, ValueError) as exc:
                errors.append(f"demand[{index}].route_share: {exc}")

    for index, signal in enumerate(scenario.get("signals", [])):
        node_id = signal.get("node_id")
        signal_nodes = {node["id"] for node in network["nodes"] if node["type"] == "signalized"}
        if node_id not in signal_nodes:
            errors.append(f"signals[{index}] must reference a signalized node")
        durations = [signal.get(key) for key in ("green_s", "yellow_s", "red_s")]
        if any(not _finite_number(value) or value < 0 for value in durations):
            errors.append(f"signals[{index}] phase durations must be finite and non-negative")
        elif not _finite_number(signal.get("cycle_s")) or abs(sum(durations) - signal["cycle_s"]) > 1e-9:
            errors.append(f"signals[{index}] cycle_s must equal green_s + yellow_s + red_s")
        if _finite_number(signal.get("yellow_s")) and signal["yellow_s"] != 2.0:
            errors.append(f"signals[{index}].yellow_s must be 2.0 seconds in schema version 1.0")
        controlled_edges = signal.get("controlled_edges")
        if controlled_edges is not None:
            if not isinstance(controlled_edges, list) or not controlled_edges:
                errors.append(f"signals[{index}].controlled_edges must be a non-empty array")
            else:
                incoming_edges = {
                    edge["id"]
                    for edge in network["edges"]
                    if edge["to_node"] == node_id
                }
                if not all(isinstance(edge_id, str) and edge_id in incoming_edges for edge_id in controlled_edges):
                    errors.append(f"signals[{index}].controlled_edges must reference incoming edges at node {node_id}")
    return errors


def signal_phase_at(signal: dict[str, float], time_s: float) -> str:
    """Return green, yellow, or red; yellow is closed to new junction entry."""
    cycle = signal["cycle_s"]
    elapsed = (time_s + signal.get("offset_s", 0.0)) % cycle
    if elapsed < signal["green_s"]:
        return "green"
    if elapsed < signal["green_s"] + signal["yellow_s"]:
        return "yellow"
    return "red"


def may_enter_junction(phase: str, *, already_past_stop_line: bool) -> bool:
    return already_past_stop_line or phase == "green"


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
