"""Small deterministic collectors for per-step simulation metrics."""

from dataclasses import dataclass


@dataclass(slots=True)
class RunMetrics:
    cumulative_distance_m: float = 0.0
    speed_integral_m: float = 0.0
    j1_discharge_count: int = 0
    overlap_checks: int = 0
    overlap_violations: int = 0

    def record_step(
        self,
        *,
        distance_m: float,
        speed_integral_m: float,
        j1_crossings: int,
        overlap_checks: int,
        overlap_violations: int,
    ) -> None:
        self.cumulative_distance_m += distance_m
        self.speed_integral_m += speed_integral_m
        self.j1_discharge_count += j1_crossings
        self.overlap_checks += overlap_checks
        self.overlap_violations += overlap_violations

    def summary(self) -> dict[str, float | int]:
        return {
            "cumulative_distance_m": self.cumulative_distance_m,
            "speed_integral_m": self.speed_integral_m,
            "j1_discharge_count": self.j1_discharge_count,
            "overlap_checks": self.overlap_checks,
            "overlap_violations": self.overlap_violations,
        }
