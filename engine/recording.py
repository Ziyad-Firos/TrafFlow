"""Deterministic columnar state sampling for the browser player."""

from dataclasses import dataclass, field
import math
from typing import Mapping

from engine.state import Vehicle


FrameColumns = dict[str, list[float | int | str]]


@dataclass(slots=True)
class FrameRecorder:
    dt_s: float
    record_interval_s: float
    frames: FrameColumns = field(default_factory=lambda: {
        "t": [], "id": [], "edge": [], "s": [], "lane": [], "v": [],
    })
    record_every_steps: int = field(init=False)

    def __post_init__(self) -> None:
        if not math.isfinite(self.dt_s) or self.dt_s <= 0.0:
            raise ValueError("dt_s must be finite and positive")
        if not math.isfinite(self.record_interval_s) or self.record_interval_s <= 0.0:
            raise ValueError("record_interval_s must be finite and positive")
        # Round to the nearest step; records keep the actual step time and are
        # never interpolated by the engine.
        self.record_every_steps = max(1, math.floor(self.record_interval_s / self.dt_s + 0.5))

    def record_if_due(
        self,
        *,
        step_index: int,
        time_s: float,
        vehicles: Mapping[int, Vehicle],
    ) -> bool:
        if step_index % self.record_every_steps:
            return False
        t = round(time_s, 6)
        for vehicle_id in sorted(vehicles):
            vehicle = vehicles[vehicle_id]
            self.frames["t"].append(t)
            self.frames["id"].append(vehicle.id)
            self.frames["edge"].append(vehicle.edge_id)
            self.frames["s"].append(round(vehicle.s, 6))
            self.frames["lane"].append(vehicle.lane)
            self.frames["v"].append(round(vehicle.v, 6))
        return True
