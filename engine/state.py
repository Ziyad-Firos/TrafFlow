"""Vehicle and lane state types for the pure-Python engine."""

from dataclasses import dataclass
from typing import TypeAlias


Lane: TypeAlias = list[int]
LanesByEdge: TypeAlias = dict[str, list[Lane]]


@dataclass(slots=True)
class Vehicle:
    """Mutable vehicle state; driver parameters remain in vehicle-type config."""

    id: int
    edge_id: str
    lane: int
    s: float
    v: float
    length: float
    route: list[str]
