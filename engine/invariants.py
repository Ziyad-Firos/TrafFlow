"""Pure state invariant checks for simulation vehicles and lanes."""

from dataclasses import dataclass
from itertools import combinations
from typing import Mapping, Sequence

from engine.state import Vehicle


@dataclass(frozen=True, slots=True)
class OverlapViolation:
    follower_id: int
    leader_id: int
    overlap_m: float


def check_no_overlap(
    vehicles: Mapping[int, Vehicle],
    lanes: Mapping[str, Sequence[Sequence[int]]],
) -> list[OverlapViolation]:
    """Report strict bumper overlaps without changing either input mapping.

    Vehicle IDs in each lane are expected to be ordered by increasing ``s``.
    The checker compares every pair, so it also catches a malformed ordering
    without sorting or otherwise mutating the lane state.
    """
    violations: list[OverlapViolation] = []
    for edge_id in sorted(lanes):
        for lane_ids in lanes[edge_id]:
            lane_vehicles = [vehicles[vehicle_id] for vehicle_id in lane_ids]
            for first, second in combinations(lane_vehicles, 2):
                if first.s > second.s:
                    leader, follower = first, second
                elif second.s > first.s:
                    leader, follower = second, first
                else:
                    # Equal front positions are ordered by ID for deterministic
                    # reporting; positive vehicle length makes this an overlap.
                    leader, follower = (first, second) if first.id > second.id else (second, first)
                overlap_m = follower.s - (leader.s - leader.length)
                if overlap_m > 0.0:
                    violations.append(
                        OverlapViolation(
                            follower_id=follower.id,
                            leader_id=leader.id,
                            overlap_m=overlap_m,
                        )
                    )
    return violations
