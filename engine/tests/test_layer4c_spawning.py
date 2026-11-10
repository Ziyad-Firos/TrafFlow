"""Poisson demand scheduling, route choice, and origin spawn insertion."""

import random
from engine.invariants import check_no_overlap
from engine.movement import step_network
from engine.network import load_preset_network, normalize_route_share
from engine.spawning import (
    SpawnRequest,
    SpawnState,
    attempt_due_spawns,
    choose_route,
    generate_spawn_schedule,
    routes_for_demand,
)
from engine.state import Vehicle


CAR = {"length_m": 4.5, "v0_mps": 13.9, "A_mps2": 1.5, "B_mps2": 2.0, "T_s": 1.5, "s0_m": 2.0}


def _small_network(lanes=3):
    return {
        "schema_version": "1.0",
        "id": "spawn_test",
        "geo_anchor": None,
        "nodes": [
            {"id": "W", "x": 0.0, "y": 0.0, "type": "plain"},
            {"id": "E", "x": 10000.0, "y": 0.0, "type": "plain"},
        ],
        "edges": [
            {"id": "edge", "from_node": "W", "to_node": "E", "length": 10000.0,
             "lanes": lanes, "speed_limit": 13.9, "polyline": [[0.0, 0.0], [10000.0, 0.0]], "type": "road"}
        ],
        "connections": [],
    }


def _scenario(*, rate, duration, seed=42, share=None):
    return {
        "schema_version": "1.0", "network_id": "spawn_test",
        "network_options": {"flyover_enabled": True}, "duration_s": duration,
        "dt_s": 0.1, "record_interval_s": 0.5, "seed": seed,
        "demand": [{"origin_node": "W", "destination_node": "E",
                    "vehicles_per_hour": rate, "start_s": 0.0, "end_s": duration,
                    "vehicle_type": "car", "route_share": share or {"through": 1.0}}],
        "signals": [], "vehicle_types": {"car": CAR}, "events": [],
    }


def _run_schedule(scenario, network, schedule):
    vehicles = {}
    lanes = {edge["id"]: [[] for _ in range(edge["lanes"])] for edge in network["edges"]}
    state = SpawnState(schedule=schedule)
    spawn_records = []
    step_count = round(scenario["duration_s"] / scenario["dt_s"])
    for step in range(step_count + 1):
        now = round(step * scenario["dt_s"], 10)
        spawn_records.extend(attempt_due_spawns(now, state, vehicles, lanes, network, scenario))
        if step < step_count:
            step_network(vehicles, lanes, network, {i: "car" for i in vehicles}, scenario["vehicle_types"],
                         dt=scenario["dt_s"], time_s=now, signals={})
            assert check_no_overlap(vehicles, lanes) == []
    return state, vehicles, lanes, spawn_records


def test_r1_poisson_count_has_expected_mean_and_three_sigma_band():
    scenario = _scenario(rate=1800.0, duration=600.0)
    schedule = generate_spawn_schedule(scenario, _small_network())
    # lambda*T = (1800/3600)*600 = 300; 3*sqrt(300)=51.96, hence 248..352.
    assert 248 <= len(schedule) <= 352


def test_r2_same_seed_schedule_and_spawn_records_are_byte_identical():
    scenario = _scenario(rate=1800.0, duration=60.0, seed=42)
    network = _small_network()
    first = _run_schedule(scenario, network, generate_spawn_schedule(scenario, network))[3]
    second = _run_schedule(scenario, network, generate_spawn_schedule(scenario, network))[3]
    first_bytes = repr([(r.arrival_time_s, r.spawned_at_s, r.route, r.lane) for r in first]).encode()
    second_bytes = repr([(r.arrival_time_s, r.spawned_at_s, r.route, r.lane) for r in second]).encode()
    assert first_bytes == second_bytes
    assert len(first) > 3


def test_r3_one_thousand_route_draws_match_binomial_three_sigma_bands():
    shares = {"through": 0.6, "flyover": 0.4}
    rng = random.Random(42)
    counts = {route: 0 for route in shares}
    for _ in range(1000):
        counts[choose_route(shares, rng)] += 1
    # Through: mean 600, sigma sqrt(240)=15.49, 3sigma=46.48; flyover is complementary.
    assert 554 <= counts["through"] <= 646
    assert 354 <= counts["flyover"] <= 446


def test_r4_disabled_flyover_redistributes_all_route_draws_to_through():
    network = load_preset_network(flyover_enabled=False)
    shares = normalize_route_share(
        {"through": 0.6, "flyover": 0.4},
        available_routes={"through"}, flyover_enabled=False,
    )
    rng = random.Random(42)
    chosen = [choose_route(shares, rng) for _ in range(1000)]
    assert chosen.count("flyover") == 0
    assert chosen.count("through") == 1000
    assert "f_e" not in {edge["id"] for edge in network["edges"]}


def test_r5_fixed_ten_arrivals_retry_until_lane_opens_and_conserve_requests():
    network = _small_network(lanes=3)
    scenario = _scenario(rate=3600.0, duration=15.0)
    route = ("edge",)
    schedule = [SpawnRequest(float(i), route, "car", "W", 0, i) for i in range(10)]
    state = SpawnState(schedule=schedule)
    blocker_ids = (99, 100, 101)
    vehicles = {
        vehicle_id: Vehicle(vehicle_id, "edge", lane, 0.0, 0.0, 4.5, ["edge"])
        for lane, vehicle_id in enumerate(blocker_ids)
    }
    lanes = {"edge": [[99], [100], [101]]}
    max_pending = 0

    for step in range(151):
        now = round(step * 0.1, 10)
        if now > 5.0:
            for vehicle_id in blocker_ids:
                vehicles.pop(vehicle_id, None)
            for lane in lanes["edge"]:
                lane[:] = [vehicle_id for vehicle_id in lane if vehicle_id not in blocker_ids]
        attempt_due_spawns(now, state, vehicles, lanes, network, scenario)
        arrived = sum(request.timestamp_s <= now for request in schedule)
        assert state.successful_spawns + len(state.pending) == arrived
        assert state.successful_spawns + len(state.pending) + (10 - arrived) == 10
        if now == 5.0:
            assert len(state.pending) == 6
        max_pending = max(max_pending, len(state.pending))
        if now < 15.0:
            step_network(vehicles, lanes, network, {i: "car" for i in vehicles}, scenario["vehicle_types"],
                         dt=0.1, time_s=now, signals={})
            for vehicle_id in blocker_ids:
                if vehicle_id in vehicles:
                    vehicles[vehicle_id].s = 0.0
                    vehicles[vehicle_id].v = 0.0
            assert check_no_overlap(vehicles, lanes) == []

    assert state.successful_spawns == 10
    assert max_pending >= 3
    assert max(record.spawned_at_s for record in state.records if record.arrival_time_s <= 5.0) <= 8.0


def test_r6_demo_demand_seventy_five_preset_spawns_fit_the_origin_envelope():
    network = load_preset_network(flyover_enabled=True)
    scenario = _scenario(rate=4500.0, duration=60.0, share={"through": 0.6, "flyover": 0.4})
    scenario["network_id"] = network["id"]
    scenario["signals"] = [
        {"node_id": "J1", "cycle_s": 80.0, "green_s": 54.0, "yellow_s": 2.0, "red_s": 24.0,
         "offset_s": 0.0, "controlled_edges": ["a_d1_j1", "a_d2_j1"]},
        {"node_id": "J2", "cycle_s": 80.0, "green_s": 54.0, "yellow_s": 2.0, "red_s": 24.0,
         "offset_s": 20.0, "controlled_edges": ["a_d2_j2", "a_e_j2"]},
    ]
    demand = scenario["demand"][0]
    route_options = routes_for_demand(demand, network, flyover_enabled=True)
    schedule = [SpawnRequest(i * 0.8, route_options["through" if i % 5 < 3 else "flyover"], "car", "W", 0, i)
                for i in range(75)]
    state, vehicles, lanes, records = _run_schedule(scenario, network, schedule)

    assert state.successful_spawns == 75
    assert len(records) == 75
    assert state.delayed_spawns == 0
    assert all(vehicle.route[0] == "a_w_d1" for vehicle in vehicles.values())
    assert all(vehicle.lane in (0, 1, 2) for vehicle in vehicles.values())
    assert all(record.speed_mps == 13.9 for record in records)
    assert {tuple(vehicle.route) for vehicle in vehicles.values()} == {
        route_options["through"], route_options["flyover"]
    }
    assert all(record.lane in (0, 1, 2) for record in records)


def test_r6b_overload_diagnostic_records_counts_without_tuning_away_delays():
    network = load_preset_network(flyover_enabled=True)
    scenario = _scenario(rate=6000.0, duration=60.0, share={"through": 0.6, "flyover": 0.4})
    scenario["network_id"] = network["id"]
    demand = scenario["demand"][0]
    route_options = routes_for_demand(demand, network, flyover_enabled=True)
    schedule = [SpawnRequest(i * 0.6, route_options["through" if i % 5 < 3 else "flyover"], "car", "W", 0, i)
                for i in range(100)]
    state, vehicles, lanes, records = _run_schedule(scenario, network, schedule)

    assert check_no_overlap(vehicles, lanes) == []
    assert state.successful_spawns + len(state.pending) == 100
    assert len({vehicle.id for vehicle in vehicles.values()}) == len(vehicles)
    assert all(vehicle.edge_id in {edge["id"] for edge in network["edges"]} for vehicle in vehicles.values())


def test_r7_vehicle_starts_at_v0_and_keeps_speed_on_first_free_flow_step():
    network = _small_network(lanes=1)
    scenario = _scenario(rate=3600.0, duration=1.0)
    request = SpawnRequest(0.0, ("edge",), "car", "W", 0, 0)
    state = SpawnState(schedule=[request])
    vehicles = {}
    lanes = {"edge": [[]]}
    attempt_due_spawns(0.0, state, vehicles, lanes, network, scenario)
    vehicle = vehicles[1]
    assert vehicle.v == 13.9
    step_network(vehicles, lanes, network, {1: "car"}, scenario["vehicle_types"], dt=0.1, signals={})
    assert vehicle.v == 13.9
