import hashlib
import json
from typing import Any


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    if isinstance(value, float):
        rounded = round(value, 6)
        return 0.0 if rounded == 0 else rounded
    return value


def input_hash(*, network: dict[str, Any], scenario: dict[str, Any], seed: int, engine_version: str) -> str:
    payload = {
        "network_json": network,
        "scenario_json": scenario,
        "seed": seed,
        "engine_version": engine_version,
    }
    canonical = json.dumps(_canonicalize(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
