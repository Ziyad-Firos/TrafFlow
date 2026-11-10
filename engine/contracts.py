"""Typed JSON-shaped contracts shared by the pure-Python engine."""

from typing import NotRequired, TypedDict


class Node(TypedDict):
    id: str
    x: float
    y: float
    type: str


class Edge(TypedDict):
    id: str
    from_node: str
    to_node: str
    length: float
    lanes: int
    speed_limit: float
    polyline: list[list[float]]
    type: str


class Connection(TypedDict):
    from_edge: str
    to_edge: str
    lanes: list[int | None]


class Network(TypedDict):
    schema_version: str
    id: str
    nodes: list[Node]
    edges: list[Edge]
    connections: list[Connection]
    geo_anchor: None


class Demand(TypedDict):
    origin_node: str
    destination_node: str
    vehicles_per_hour: float
    start_s: float
    end_s: float
    vehicle_type: str
    route_share: NotRequired[dict[str, float]]


class Signal(TypedDict):
    node_id: str
    cycle_s: float
    green_s: float
    yellow_s: float
    red_s: float
    offset_s: float
    controlled_edges: NotRequired[list[str]]


class Scenario(TypedDict):
    schema_version: str
    network_id: str
    network_options: dict[str, bool]
    duration_s: float
    dt_s: float
    record_interval_s: float
    seed: int
    demand: list[Demand]
    signals: list[Signal]
    vehicle_types: dict[str, dict[str, float]]
    events: list[dict[str, object]]
