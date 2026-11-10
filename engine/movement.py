"""Snapshot movement and edge-transition application for the engine."""

from collections.abc import Mapping, MutableMapping
from typing import Any

from engine.dynamics import idm_acceleration, symplectic_euler_step
from engine.merges import Approach, MergeSlot, arbitrate_merge_slot
from engine.scenario import signal_phase_at
from engine.state import LanesByEdge, Vehicle


def step_network(
    vehicles: dict[int, Vehicle],
    lanes: LanesByEdge,
    network: dict[str, Any],
    vehicle_type_ids: Mapping[int, str],
    vehicle_types: Mapping[str, Mapping[str, float]],
    *,
    dt: float,
    use_reservations: bool = True,
    merge_state: MutableMapping[MergeSlot, Approach] | None = None,
    time_s: float = 0.0,
    signals: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    """Advance one snapshot step.

    Pass `merge_state` across calls for a persistent run. `None` initializes
    zipper state locally, which is convenient for single-step tests.
    """
    edges = {edge["id"]: edge for edge in network["edges"]}
    connections = {
        (connection["from_edge"], connection["to_edge"]): connection["lanes"]
        for connection in network["connections"]
    }
    approaches_by_slot: dict[MergeSlot, list[Approach]] = {}
    for connection in network["connections"]:
        source = connection["from_edge"]
        target = connection["to_edge"]
        for source_lane, target_lane in enumerate(connection["lanes"]):
            if target_lane is not None:
                slot = (target, target_lane)
                approaches_by_slot.setdefault(slot, []).append((source, source_lane))
    for slot, approaches in approaches_by_slot.items():
        approaches.sort()
    active_merge_state: MutableMapping[MergeSlot, Approach] = (
        {} if merge_state is None else merge_state
    )
    for slot, approaches in approaches_by_slot.items():
        if len(approaches) > 1:
            active_merge_state.setdefault(slot, approaches[-1])
    nodes = {node["id"]: node for node in network.get("nodes", [])}
    signal_configs = signals or {}

    def signal_for_edge(edge_id: str) -> Mapping[str, Any] | None:
        end_node = edges[edge_id].get("to_node")
        if end_node is None or nodes.get(end_node, {}).get("type") != "signalized":
            return None
        signal = signal_configs.get(end_node)
        if signal is None:
            return None
        controlled_edges = signal.get("controlled_edges")
        if controlled_edges is not None and edge_id not in controlled_edges:
            return None
        return signal

    def signal_open_at_step_start(signal: Mapping[str, Any]) -> bool:
        timing = {
            key: float(signal[key])
            for key in ("cycle_s", "green_s", "yellow_s", "red_s", "offset_s")
            if key in signal
        }
        return signal_phase_at(timing, time_s) == "green"

    signal_open_by_edge = {
        edge_id: (
            signal is None or signal_open_at_step_start(signal)
        )
        for edge_id in edges
        for signal in (signal_for_edge(edge_id),)
    }

    def route_next(vehicle: Vehicle) -> str | None:
        route_index = vehicle.route.index(vehicle.edge_id)
        return vehicle.route[route_index + 1] if route_index + 1 < len(vehicle.route) else None

    start_of_step_straddler_rears: dict[tuple[str, int], list[float]] = {}
    for existing in vehicles.values():
        current_edge = edges[existing.edge_id]
        next_edge_id = route_next(existing)
        if next_edge_id is not None and existing.s > current_edge["length"]:
            mapped_lane = connections[(existing.edge_id, next_edge_id)][existing.lane]
            if mapped_lane is not None:
                front_on_next = existing.s - current_edge["length"]
                slot = (next_edge_id, mapped_lane)
                start_of_step_straddler_rears.setdefault(slot, []).append(
                    front_on_next - existing.length
                )

    def entry_head_gap(
        next_edge_id: str,
        next_lane: int,
        reservations: Mapping[tuple[str, int, int], tuple[float, float]],
    ) -> float:
        rear_positions: list[float] = []
        target_lane = lanes[next_edge_id][next_lane]
        if target_lane:
            first = min((vehicles[item] for item in target_lane), key=lambda item: (item.s, item.id))
            rear_positions.append(first.s - first.length)
        # Use only the start-of-step snapshot here. Vehicles admitted earlier
        # this step are accounted for solely by explicit reservations.
        rear_positions.extend(start_of_step_straddler_rears.get((next_edge_id, next_lane), ()))
        if use_reservations:
            for (reserved_edge, reserved_lane, _), (position_front, length) in reservations.items():
                if reserved_edge == next_edge_id and reserved_lane == next_lane:
                    rear_positions.append(position_front - length)
        return min(rear_positions) if rear_positions else edges[next_edge_id]["length"]

    lane_position: dict[int, tuple[str, int, int]] = {}
    for edge_id, edge_lanes in lanes.items():
        for lane_index, lane_ids in enumerate(edge_lanes):
            for order_index, vehicle_id in enumerate(lane_ids):
                lane_position[vehicle_id] = (edge_id, lane_index, order_index)

    # Snapshot accelerations. A full downstream entry acts as a virtual stop-line leader.
    accelerations: dict[int, float] = {}
    snapshot_entry_gap_cache: dict[tuple[str, int], float] = {}
    for vehicle_id in sorted(vehicles):
        vehicle = vehicles[vehicle_id]
        edge = edges[vehicle.edge_id]
        type_config = vehicle_types[vehicle_type_ids[vehicle_id]]
        edge_lane = lanes[vehicle.edge_id][vehicle.lane]
        order_index = lane_position[vehicle_id][2]
        leader = vehicles[edge_lane[order_index + 1]] if order_index + 1 < len(edge_lane) else None
        leader_speed: float | None = leader.v if leader is not None else None
        gap: float | None = leader.s - leader.length - vehicle.s if leader is not None else None

        next_edge_id = route_next(vehicle)
        if next_edge_id is not None and vehicle.s <= edge["length"]:
            next_lane = connections[(vehicle.edge_id, next_edge_id)][vehicle.lane]
            if next_lane is not None:
                slot = (next_edge_id, next_lane)
                if slot not in snapshot_entry_gap_cache:
                    snapshot_entry_gap_cache[slot] = entry_head_gap(next_edge_id, next_lane, {})
                available = snapshot_entry_gap_cache[slot]
                entry_blocked = available < type_config["s0_m"] + vehicle.length

                signal_blocked = not signal_open_by_edge[vehicle.edge_id]

                if entry_blocked or signal_blocked:
                    stop_gap = max(1e-9, edge["length"] - vehicle.s)
                    if leader is None or stop_gap < (gap if gap is not None else float("inf")):
                        leader_speed, gap = 0.0, stop_gap

        accelerations[vehicle_id] = idm_acceleration(
            v=vehicle.v,
            v_leader_or_none=leader_speed,
            gap=gap,
            v0=edge["speed_limit"],
            A=type_config["A_mps2"],
            B=type_config["B_mps2"],
            T=type_config["T_s"],
            s0=type_config["s0_m"],
        )

    pending: dict[int, tuple[float, float]] = {}
    for vehicle_id in sorted(vehicles):
        vehicle = vehicles[vehicle_id]
        v_new, s_new = symplectic_euler_step(
            s=vehicle.s, v=vehicle.v, a=accelerations[vehicle_id], dt=dt
        )
        # Speeds cannot become negative; IDM acceleration itself remains unclamped.
        v_new = max(0.0, v_new)
        pending[vehicle_id] = (v_new, vehicle.s + v_new * dt)

    # Reservations expire each step. Existing straddlers retain occupancy via
    # the snapshot list above; new admissions reserve their downstream footprint.
    reservations: dict[tuple[str, int, int], tuple[float, float]] = {}
    merge_candidates: dict[MergeSlot, dict[Approach, list[int]]] = {}
    candidate_values: dict[int, tuple[float, float, str, int]] = {}

    def finish_rear_clear(vehicle: Vehicle, next_edge_id: str, s_new: float, v_new: float) -> None:
        current_edge_length = edges[vehicle.edge_id]["length"]
        next_lane = connections[(vehicle.edge_id, next_edge_id)][vehicle.lane]
        if s_new - vehicle.length >= current_edge_length:
            vehicle.edge_id = next_edge_id
            vehicle.lane = next_lane
            vehicle.s = s_new - current_edge_length
        else:
            vehicle.s = s_new
        vehicle.v = v_new

    def admission_allowed(vehicle: Vehicle, next_edge_id: str, next_lane: int, s_new: float) -> bool:
        edge = edges[vehicle.edge_id]
        type_config = vehicle_types[vehicle_type_ids[vehicle.id]]
        overflow = s_new - edge["length"]
        available = entry_head_gap(next_edge_id, next_lane, reservations)
        signal_open = signal_open_by_edge[vehicle.edge_id]
        return overflow + type_config["s0_m"] <= available and signal_open

    def admit(vehicle_id: int) -> None:
        vehicle = vehicles[vehicle_id]
        edge = edges[vehicle.edge_id]
        v_new, s_new, next_edge_id, next_lane = candidate_values[vehicle_id]
        overflow = s_new - edge["length"]
        if use_reservations:
            reservations[(next_edge_id, next_lane, vehicle_id)] = (overflow, vehicle.length)
        finish_rear_clear(vehicle, next_edge_id, s_new, v_new)

    def hold_at_stop_line(vehicle_id: int) -> None:
        vehicle = vehicles[vehicle_id]
        edge = edges[vehicle.edge_id]
        type_config = vehicle_types[vehicle_type_ids[vehicle_id]]
        _v_new, s_new, _next_edge_id, _next_lane = candidate_values[vehicle_id]
        old_s = vehicle.s
        vehicle.s = min(s_new, max(old_s, edge["length"] - type_config["s0_m"]))
        vehicle.v = (vehicle.s - old_s) / dt if dt > 0.0 else 0.0

    # Previously admitted straddlers finish their edge bookkeeping first. They
    # already own downstream space from an earlier step.
    for vehicle_id in sorted(vehicles):
        vehicle = vehicles[vehicle_id]
        edge = edges[vehicle.edge_id]
        next_edge_id = route_next(vehicle)
        v_new, s_new = pending[vehicle_id]
        if vehicle.s > edge["length"] and next_edge_id is not None:
            finish_rear_clear(vehicle, next_edge_id, s_new, v_new)
        elif s_new <= edge["length"] or next_edge_id is None:
            vehicle.s = max(vehicle.s, s_new)
            vehicle.v = v_new
        else:
            next_lane = connections[(vehicle.edge_id, next_edge_id)][vehicle.lane]
            if next_lane is None:
                vehicle.s = s_new
                vehicle.v = v_new
            else:
                candidate_values[vehicle_id] = (v_new, s_new, next_edge_id, next_lane)
                approach = (vehicle.edge_id, vehicle.lane)
                merge_candidates.setdefault((next_edge_id, next_lane), {}).setdefault(approach, []).append(vehicle_id)

    # Single-approach transitions retain ID ordering and use the same reservations.
    single_approach_candidates = sorted(
        vehicle_id
        for slot, waiters in merge_candidates.items()
        if len(approaches_by_slot[slot]) == 1
        for vehicle_ids in waiters.values()
        for vehicle_id in vehicle_ids
    )
    for vehicle_id in single_approach_candidates:
        _v_new, s_new, next_edge_id, next_lane = candidate_values[vehicle_id]
        if admission_allowed(vehicles[vehicle_id], next_edge_id, next_lane, s_new):
            admit(vehicle_id)
        else:
            hold_at_stop_line(vehicle_id)

    # Multi-approach slots use zipper order independently of vehicle-ID order.
    for slot in sorted(merge_candidates):
        approaches = approaches_by_slot[slot]
        if len(approaches) <= 1:
            continue
        slot_waiters = merge_candidates[slot]

        def can_reserve(vehicle_id: int) -> bool:
            _v_new, s_new, next_edge_id, next_lane = candidate_values[vehicle_id]
            return admission_allowed(vehicles[vehicle_id], next_edge_id, next_lane, s_new)

        selected = arbitrate_merge_slot(
            slot, approaches, active_merge_state, slot_waiters, can_reserve
        )
        selected_id = selected[1] if selected is not None else None
        for vehicle_ids in slot_waiters.values():
            for vehicle_id in vehicle_ids:
                if vehicle_id == selected_id:
                    admit(vehicle_id)
                else:
                    hold_at_stop_line(vehicle_id)

    rebuilt: LanesByEdge = {
        edge_id: [[] for _ in range(edge["lanes"])] for edge_id, edge in edges.items()
    }
    for vehicle in vehicles.values():
        rebuilt[vehicle.edge_id][vehicle.lane].append(vehicle.id)
    for edge_lanes in rebuilt.values():
        for lane_ids in edge_lanes:
            lane_ids.sort(key=lambda item: (vehicles[item].s, item))
    lanes.clear()
    lanes.update(rebuilt)
