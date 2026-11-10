"""Network preset loading, structural validation, and routing."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


_PRESET_PATH = Path(__file__).resolve().parent.parent / "schemas" / "presets" / "iisc_two_junctions_v1.json"
_NODE_TYPES = {"plain", "signalized", "merge"}
_EDGE_TYPES = {"road", "flyover", "ramp"}
_FLYOVER_EDGE_IDS = {"r_e_on", "f_e", "r_e_off", "r_w_on", "f_w", "r_w_off"}


def load_preset_network(*, flyover_enabled: bool = True) -> dict[str, Any]:
    """Load a fresh copy of the preset, optionally removing flyover facilities."""
    with _PRESET_PATH.open(encoding="utf-8") as source:
        network = json.load(source)
    if not flyover_enabled:
        network["edges"] = [
            edge for edge in network["edges"] if edge["id"] not in _FLYOVER_EDGE_IDS
        ]
        network["connections"] = [
            connection
            for connection in network["connections"]
            if connection["from_edge"] not in _FLYOVER_EDGE_IDS
            and connection["to_edge"] not in _FLYOVER_EDGE_IDS
        ]
    errors = validate_network(network)
    if errors:
        raise ValueError("Invalid preset network: " + "; ".join(errors))
    return network


def validate_network(network: dict[str, Any]) -> list[str]:
    """Return clear contract violations; an empty list means the network is valid."""
    errors: list[str] = []
    if network.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")
    if network.get("geo_anchor", object()) is not None:
        errors.append("geo_anchor must be null")

    nodes = network.get("nodes")
    edges = network.get("edges")
    connections = network.get("connections")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not isinstance(connections, list):
        return errors + ["nodes, edges, and connections must be arrays"]

    node_by_id: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"nodes[{index}] must be an object")
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            errors.append(f"nodes[{index}].id must be a non-empty string")
            continue
        if node_id in node_by_id:
            errors.append(f"duplicate node id: {node_id}")
        node_by_id[node_id] = node
        if node.get("type") not in _NODE_TYPES:
            errors.append(f"node {node_id} has invalid type")
        for coordinate in ("x", "y"):
            value = node.get(coordinate)
            if not _finite_number(value):
                errors.append(f"node {node_id}.{coordinate} must be a finite number")

    edge_by_id: dict[str, dict[str, Any]] = {}
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"edges[{index}] must be an object")
            continue
        edge_id = edge.get("id")
        if not isinstance(edge_id, str) or not edge_id:
            errors.append(f"edges[{index}].id must be a non-empty string")
            continue
        if edge_id in edge_by_id:
            errors.append(f"duplicate edge id: {edge_id}")
        edge_by_id[edge_id] = edge
        if edge.get("type") not in _EDGE_TYPES:
            errors.append(f"edge {edge_id} has invalid type")
        if edge.get("from_node") not in node_by_id or edge.get("to_node") not in node_by_id:
            errors.append(f"edge {edge_id} references an unknown node")
        if not isinstance(edge.get("lanes"), int) or edge["lanes"] <= 0:
            errors.append(f"edge {edge_id}.lanes must be a positive integer")
        for field in ("length", "speed_limit"):
            if not _finite_number(edge.get(field)) or edge[field] <= 0:
                errors.append(f"edge {edge_id}.{field} must be a positive finite number")
        points = edge.get("polyline")
        if not isinstance(points, list) or len(points) < 2:
            errors.append(f"edge {edge_id}.polyline must contain at least two points")
        else:
            if any(
                not isinstance(point, list)
                or len(point) != 2
                or not all(_finite_number(component) for component in point)
                for point in points
            ):
                errors.append(f"edge {edge_id}.polyline points must be finite [x, y] pairs")
            else:
                polyline_length = sum(
                    math.hypot(right[0] - left[0], right[1] - left[1])
                    for left, right in zip(points, points[1:])
                )
                if _finite_number(edge.get("length")) and abs(edge["length"] - polyline_length) > 0.01:
                    errors.append(f"edge {edge_id}.length differs from polyline length by more than 0.01 m")

    seen_connections: set[tuple[str, str]] = set()
    for index, connection in enumerate(connections):
        if not isinstance(connection, dict):
            errors.append(f"connections[{index}] must be an object")
            continue
        from_id, to_id = connection.get("from_edge"), connection.get("to_edge")
        if from_id not in edge_by_id or to_id not in edge_by_id:
            errors.append(f"connections[{index}] references an unknown edge")
            continue
        pair = (from_id, to_id)
        if pair in seen_connections:
            errors.append(f"duplicate connection: {from_id} -> {to_id}")
        seen_connections.add(pair)
        from_edge, to_edge = edge_by_id[from_id], edge_by_id[to_id]
        if from_edge["to_node"] != to_edge["from_node"]:
            errors.append(f"connection {from_id} -> {to_id} has mismatched endpoint nodes")
        mapping = connection.get("lanes")
        if not isinstance(mapping, list) or len(mapping) != from_edge.get("lanes"):
            errors.append(f"connection {from_id} -> {to_id} must map each incoming lane")
        elif any(
            lane is not None and (not isinstance(lane, int) or lane < 0 or lane >= to_edge.get("lanes", 0))
            for lane in mapping
        ):
            errors.append(f"connection {from_id} -> {to_id} maps to an invalid outgoing lane")
    return errors


def find_route(
    network: dict[str, Any],
    origin_node: str,
    destination_node: str,
    *,
    required_edge: str | None = None,
    forbidden_edges: set[str] | None = None,
) -> list[str] | None:
    """Find a minimum free-flow-time route, optionally requiring an edge."""
    forbidden = forbidden_edges or set()
    edge_by_id = {edge["id"]: edge for edge in network["edges"]}
    outgoing: dict[str, list[str]] = {}
    for connection in network["connections"]:
        if any(lane is not None for lane in connection["lanes"]):
            outgoing.setdefault(connection["from_edge"], []).append(connection["to_edge"])
    starts = [
        edge_id for edge_id, edge in edge_by_id.items()
        if edge["from_node"] == origin_node and edge_id not in forbidden
    ]
    queue: list[tuple[float, str, list[str], bool]] = [
        (edge_by_id[edge_id]["length"] / edge_by_id[edge_id]["speed_limit"], edge_id,
         [edge_id], edge_id == required_edge)
        for edge_id in starts
    ]
    best: dict[tuple[str, bool], float] = {}
    while queue:
        queue.sort(key=lambda item: (item[0], item[1], item[2]))
        cost, edge_id, path, has_required = queue.pop(0)
        state = (edge_id, has_required)
        if cost >= best.get(state, math.inf):
            continue
        best[state] = cost
        edge = edge_by_id[edge_id]
        if edge["to_node"] == destination_node and (required_edge is None or has_required):
            return path
        for next_id in sorted(outgoing.get(edge_id, [])):
            if next_id in forbidden:
                continue
            next_edge = edge_by_id[next_id]
            queue.append((
                cost + next_edge["length"] / next_edge["speed_limit"],
                next_id,
                path + [next_id],
                has_required or next_id == required_edge,
            ))
    return None


def normalize_route_share(
    route_share: dict[str, float],
    *,
    available_routes: set[str],
    flyover_enabled: bool,
) -> dict[str, float]:
    """Validate shares and redistribute disabled-flyover share proportionally."""
    if not isinstance(route_share, dict) or not route_share:
        raise ValueError("route_share must be a non-empty object")
    unknown = set(route_share) - {"through", "flyover"}
    if unknown:
        raise ValueError(f"route_share contains unavailable route: {sorted(unknown)[0]}")
    values = list(route_share.values())
    if any(not _finite_number(value) or value < 0 for value in values):
        raise ValueError("route_share values must be finite and non-negative")
    total = sum(values)
    if abs(total - 1.0) > 0.01:
        raise ValueError("route_share values must sum to 1 within 0.01")
    unavailable = set(route_share) - available_routes
    if unavailable and not (unavailable == {"flyover"} and not flyover_enabled):
        raise ValueError(f"route_share contains unavailable route: {sorted(unavailable)[0]}")
    if total <= 0:
        raise ValueError("route_share must have a positive total")
    normalized = {route: value / total for route, value in route_share.items()}
    available = {
        route: normalized.get(route, 0.0)
        for route in sorted(available_routes)
    }
    if not available:
        raise ValueError("route_share has no routes available for this scenario")
    remaining_total = sum(available.values())
    if remaining_total == 0:
        equal_share = 1.0 / len(available)
        return {route: equal_share for route in sorted(available)}
    return {route: share / remaining_total for route, share in sorted(available.items())}


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
