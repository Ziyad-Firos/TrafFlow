"""Arithmetic tests for IDM acceleration and one symplectic Euler step."""

import pytest

from engine.dynamics import idm_acceleration, symplectic_euler_step


PARAMS = {"v0": 13.9, "A": 1.5, "B": 2.0, "T": 1.5, "s0": 2.0}


def test_idm_stopped_vehicle_without_leader_accelerates_at_a_maximum_rate():
    assert idm_acceleration(0.0, None, None, **PARAMS) == pytest.approx(1.5, abs=1e-12)


def test_idm_at_speed_limit_without_leader_has_zero_acceleration():
    assert idm_acceleration(13.9, None, None, **PARAMS) == pytest.approx(0.0, abs=1e-12)


def test_idm_at_half_speed_without_leader_has_expected_free_flow_acceleration():
    assert idm_acceleration(6.95, None, None, **PARAMS) == pytest.approx(1.40625, abs=1e-12)


def test_idm_stopped_vehicle_at_standstill_gap_to_stopped_leader_has_zero_acceleration():
    acceleration = idm_acceleration(0.0, 0.0, 2.0, **PARAMS)

    assert acceleration == pytest.approx(0.0, abs=1e-12)


def test_idm_at_speed_limit_with_leader_uses_desired_gap_even_with_zero_delta_v():
    acceleration = idm_acceleration(13.9, 13.9, 15.5, **PARAMS)

    assert acceleration == pytest.approx(-3.25987, abs=1e-3)


def test_idm_moderate_speed_and_gap_matches_hand_calculation():
    acceleration = idm_acceleration(10.0, 10.0, 30.0, **PARAMS)

    assert acceleration == pytest.approx(0.616513, abs=1e-3)


def test_idm_without_leader_brakes_when_vehicle_exceeds_speed_limit():
    acceleration = idm_acceleration(15.0, None, None, **PARAMS)

    assert acceleration == pytest.approx(-0.534, abs=1e-3)


def test_idm_fast_closing_leader_produces_strong_negative_acceleration():
    acceleration = idm_acceleration(13.9, 5.0, 15.5, **PARAMS)

    assert acceleration == pytest.approx(-21.4, abs=0.05)


def test_symplectic_euler_accelerates_from_rest_using_new_speed_for_position():
    v_new, s_new = symplectic_euler_step(s=0.0, v=0.0, a=1.5, dt=0.1)

    assert v_new == pytest.approx(0.15, abs=1e-12)
    assert s_new == pytest.approx(0.015, abs=1e-12)


def test_symplectic_euler_at_speed_limit_keeps_speed_and_advances_position():
    v_new, s_new = symplectic_euler_step(s=0.0, v=13.9, a=0.0, dt=0.1)

    assert v_new == pytest.approx(13.9, abs=1e-12)
    assert s_new == pytest.approx(1.39, abs=1e-12)


def test_symplectic_euler_uses_idm_acceleration_against_same_speed_leader():
    acceleration = idm_acceleration(13.9, 13.9, 25.0, **PARAMS)
    v_new, s_new = symplectic_euler_step(s=0.0, v=13.9, a=acceleration, dt=0.1)

    assert v_new == pytest.approx(13.7747, abs=1e-3)
    assert s_new == pytest.approx(1.3775, abs=1e-3)
