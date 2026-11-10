"""Run the five-minute demo and report runtime and result payload size.

Invoke from the repository root with: ``python -m engine.benchmark``.
"""

import gzip
import json
from collections import Counter
from pathlib import Path

from engine.network import load_preset_network
from engine.simulation import run_simulation


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    scenario = json.loads(
        (root / "schemas" / "scenarios" / "demo_v1.json").read_text(encoding="utf-8")
    )
    network = load_preset_network(
        flyover_enabled=bool(scenario["network_options"]["flyover_enabled"])
    )
    result = run_simulation(scenario, network)
    payload = result.to_json_bytes()
    compressed = gzip.compress(payload, compresslevel=9, mtime=0)
    rows_per_sample = Counter(result.frames["t"])
    report = {
        "engine_version": result.engine_version,
        "duration_s": result.duration_s,
        "steps": result.steps,
        "elapsed_s": round(result.elapsed_s, 6),
        "steps_per_second": round(result.steps_per_second, 2),
        "requested_vehicles": result.requested_count,
        "spawned_vehicles": result.spawned_count,
        "pending_vehicles": result.pending_count,
        "sampled_times_with_vehicles": len(rows_per_sample),
        "columnar_rows": len(result.frames["id"]),
        "max_vehicles_per_sample": max(rows_per_sample.values(), default=0),
        "json_bytes": len(payload),
        "gzip_bytes": len(compressed),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
