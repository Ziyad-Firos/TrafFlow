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
            # Normal engine lanes are sorted by (front position, vehicle id).
            # In that case, adjacent vehicles are sufficient to prove the
            # entire lane is overlap-free. Keep the exhaustive path for
            # malformed ordering and for reporting every violation in an
            # invalid state, preserving the checker's diagnostic semantics.
            is_ordered = all(
                (left.s, left.id) <= (right.s, right.id)
                for left, right in zip(lane_vehicles, lane_vehicles[1:])
            )
            if is_ordered:
                has_adjacent_overlap = any(
                    follower.s > leader.s - leader.length
                    for follower, leader in zip(lane_vehicles, lane_vehicles[1:])
                )
                if not has_adjacent_overlap:
                    continue
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
