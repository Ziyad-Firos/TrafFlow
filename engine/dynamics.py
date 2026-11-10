"""Car-following dynamics and single-step integration primitives."""

from math import sqrt


MAX_BRAKING_MPS2 = 8.0


def idm_acceleration(
    v: float,
    v_leader_or_none: float | None,
    gap: float | None,
    v0: float,
    A: float,
    B: float,
    T: float,
    s0: float,
) -> float:
    """Return IDM acceleration (delta=4), with a physical braking limit."""
    free_road_term = (v / v0) ** 4
    if v_leader_or_none is None:
        interaction_term = 0.0
    else:
        if gap is None:
            raise ValueError("gap is required when a leader is present")
        delta_v = v - v_leader_or_none
        desired_gap = s0 + v * T + (v * delta_v) / (2.0 * sqrt(A * B))
        interaction_term = (desired_gap / gap) ** 2
    raw_acceleration = A * (1.0 - free_road_term - interaction_term)
    return max(raw_acceleration, -MAX_BRAKING_MPS2)


def symplectic_euler_step(s: float, v: float, a: float, dt: float) -> tuple[float, float]:
    """Advance speed first, then position using that new speed."""
    v_new = v + a * dt
    s_new = s + v_new * dt
    return v_new, s_new
