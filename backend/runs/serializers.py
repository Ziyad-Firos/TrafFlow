from typing import Any

from rest_framework import serializers

from engine.network import load_preset_network
from engine.scenario import validate_scenario


class RunCreateSerializer(serializers.Serializer):
    scenario_json = serializers.DictField()
    seed = serializers.IntegerField(min_value=0, max_value=2**31 - 1)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        scenario = attrs["scenario_json"]
        network_id = scenario.get("network_id")
        if network_id != "iisc_two_junctions_v1":
            raise serializers.ValidationError({"scenario_json": {"network_id": "Unknown network preset."}})
        network_options = scenario.get("network_options", {})
        if not isinstance(network_options, dict):
            raise serializers.ValidationError({"scenario_json": {"network_options": "Must be an object."}})
        flyover_enabled = network_options.get("flyover_enabled", True)
        if not isinstance(flyover_enabled, bool):
            raise serializers.ValidationError({"scenario_json": {"network_options.flyover_enabled": "Must be a boolean."}})
        network = load_preset_network(flyover_enabled=flyover_enabled)
        scenario["seed"] = attrs["seed"]
        errors = validate_scenario(scenario, network)
        if errors:
            raise serializers.ValidationError({"scenario_json": errors})
        if scenario["duration_s"] > 600:
            raise serializers.ValidationError({"scenario_json": "duration_s cannot exceed 600 seconds."})
        return attrs
