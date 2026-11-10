"""Snapshot movement and edge-transition application for the engine."""

from collections.abc import Mapping
from typing import Any

from engine.dynamics import idm_acceleration, symplectic_euler_step
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
    time_s: float = 0.0,
    signals: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    """Advance one snapshot step, resolving transitions in ascending vehicle ID order."""
    edges = {edge["id"]: edge for edge in network["edges"]}
    connections = {
        (connection["from_edge"], connection["to_edge"]): connection["lanes"]
        for connection in network["connections"]
    }
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

    def route_next(vehicle: Vehicle) -> str | None:
        route_index = vehicle.route.index(vehicle.edge_id)
        return vehicle.route[route_index + 1] if route_index + 1 < len(vehicle.route) else None

    start_of_step_straddlers: list[tuple[str, int, float]] = []
    for existing in vehicles.values():
        current_edge = edges[existing.edge_id]
        next_edge_id = route_next(existing)
        if next_edge_id is not None and existing.s > current_edge["length"]:
            mapped_lane = connections[(existing.edge_id, next_edge_id)][existing.lane]
            if mapped_lane is not None:
                front_on_next = existing.s - current_edge["length"]
                start_of_step_straddlers.append(
                    (next_edge_id, mapped_lane, front_on_next - existing.length)
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
        for straddler_edge, straddler_lane, straddler_rear in start_of_step_straddlers:
            if straddler_edge == next_edge_id and straddler_lane == next_lane:
                rear_positions.append(straddler_rear)
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
                available = entry_head_gap(next_edge_id, next_lane, {})
                entry_blocked = available < type_config["s0_m"] + vehicle.length

                signal = signal_for_edge(vehicle.edge_id)
                signal_blocked = (
                    signal is not None and not signal_open_at_step_start(signal)
                )

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

    # Reservations live only for this step. Their keys include the vehicle ID
    # for diagnostics; physical capacity uses each reserved front and length.
    reservations: dict[tuple[str, int, int], tuple[float, float]] = {}
    for vehicle_id in sorted(vehicles):
        vehicle = vehicles[vehicle_id]
        edge = edges[vehicle.edge_id]
        type_config = vehicle_types[vehicle_type_ids[vehicle_id]]
        v_new, s_new = pending[vehicle_id]
        next_edge_id = route_next(vehicle)
        blocked = False

        # Once the rear has cleared, finish the bookkeeping transition. The
        # crossing was admitted when the front first passed the edge end.
        if vehicle.s > edge["length"] and next_edge_id is not None:
            if s_new - vehicle.length >= edge["length"]:
                next_lane = connections[(vehicle.edge_id, next_edge_id)][vehicle.lane]
                vehicle.edge_id = next_edge_id
                vehicle.lane = next_lane
                vehicle.s = s_new - edge["length"]
            else:
                vehicle.s = s_new
            vehicle.v = v_new
            continue

        if s_new > edge["length"] and next_edge_id is not None:
            next_edge = edges[next_edge_id]
            next_lane = connections[(vehicle.edge_id, next_edge_id)][vehicle.lane]
            overflow = s_new - edge["length"]
            available = (
                entry_head_gap(next_edge_id, next_lane, reservations)
                if next_lane is not None
                else float("-inf")
            )
            signal = signal_for_edge(vehicle.edge_id)
            signal_open = signal is None or signal_open_at_step_start(signal)
            if (
                next_lane is not None
                and overflow + type_config["s0_m"] <= available
                and signal_open
            ):
                if use_reservations:
                    reservations[(next_edge_id, next_lane, vehicle_id)] = (overflow, vehicle.length)
                vehicle.s = s_new
                vehicle.v = v_new
                if vehicle.s - vehicle.length >= edge["length"]:
                    vehicle.edge_id = next_edge_id
                    vehicle.lane = next_lane
                    vehicle.s -= edge["length"]
                continue
            s_new = min(s_new, max(vehicle.s, edge["length"] - type_config["s0_m"]))
            blocked = True

        old_s = vehicle.s
        vehicle.s = max(old_s, s_new)
        if blocked:
            vehicle.v = (vehicle.s - old_s) / dt if dt > 0.0 else 0.0
        else:
            vehicle.v = v_new

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
