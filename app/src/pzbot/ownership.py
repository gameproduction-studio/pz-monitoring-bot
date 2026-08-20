"""Ownership rules for observed Project Zomboid world storage."""

from __future__ import annotations

import math
from typing import Any, Iterable


def position_in_zone(position: dict[str, Any], zone: dict[str, Any]) -> bool:
    x = float(position.get("x", 0))
    y = float(position.get("y", 0))
    z = float(position.get("z", 0))
    if zone.get("z_min") is not None and z < float(zone["z_min"]):
        return False
    if zone.get("z_max") is not None and z > float(zone["z_max"]):
        return False
    shape = str(zone.get("shape", "circle"))
    if shape == "circle":
        dx = x - float(zone["x"])
        dy = y - float(zone["y"])
        return math.hypot(dx, dy) <= float(zone.get("radius", 30))
    if shape == "rectangle":
        return (
            float(zone["x_min"]) <= x <= float(zone["x_max"])
            and float(zone["y_min"]) <= y <= float(zone["y_max"])
        )
    raise ValueError(f"Unsupported base-zone shape: {shape}")


def matching_zones(
    position: dict[str, Any],
    zones: Iterable[dict[str, Any]],
    save_id: str,
) -> list[dict[str, Any]]:
    return [
        zone
        for zone in zones
        if (not zone.get("save_id") or zone.get("save_id") == save_id)
        and position_in_zone(position, zone)
    ]


def classify_container(
    container: dict[str, Any],
    *,
    zones: Iterable[dict[str, Any]],
    save_id: str,
    explicitly_opened: set[str] | None = None,
    manual_owned: set[str] | None = None,
) -> dict[str, Any]:
    container_id = str(container.get("containerId"))
    position = container.get("position") or {}
    zone_hits = matching_zones(position, zones, save_id)
    reasons: list[dict[str, Any]] = []
    confidence = "none"

    if zone_hits:
        reasons.extend(
            {
                "type": "inside_base_zone",
                "zone": zone.get("name") or zone.get("id") or "base",
                "confidence": "exact",
            }
            for zone in zone_hits
        )
        confidence = "exact"

    if container_id in (manual_owned or set()):
        reasons.append({"type": "manual", "confidence": "exact"})
        confidence = "exact"

    if container_id in (explicitly_opened or set()):
        reasons.append({"type": "opened_event", "confidence": "exact"})
        confidence = "exact"
    elif container.get("hasBeenLooted"):
        reasons.append(
            {
                "type": "transfer_from_container",
                "confidence": "high",
                "note": "The save records that an item was transferred out.",
            }
        )
        if confidence == "none":
            confidence = "high"
    elif container.get("explored"):
        reasons.append(
            {
                "type": "opened_inferred",
                "confidence": "medium",
                "note": (
                    "Build 42 sets explored when a container is opened, but a few "
                    "game systems can set the same flag without a manual open."
                ),
            }
        )
        if confidence == "none":
            confidence = "medium"

    return {
        "owned": bool(reasons),
        "confidence": confidence,
        "reasons": reasons,
        "classification": "owned" if reasons else "world_observed",
    }


def classify_ground_item(
    item: dict[str, Any],
    *,
    zones: Iterable[dict[str, Any]],
    save_id: str,
) -> dict[str, Any]:
    zone_hits = matching_zones(item.get("position") or {}, zones, save_id)
    return {
        "owned": bool(zone_hits),
        "confidence": "exact" if zone_hits else "none",
        "classification": "owned" if zone_hits else "world_observed",
        "reasons": [
            {
                "type": "inside_base_zone",
                "zone": zone.get("name") or zone.get("id") or "base",
                "confidence": "exact",
            }
            for zone in zone_hits
        ],
    }


def apply_ownership(
    world: dict[str, Any],
    *,
    zones: Iterable[dict[str, Any]],
    save_id: str,
    explicitly_opened: set[str] | None = None,
    manual_owned: set[str] | None = None,
) -> dict[str, Any]:
    zones = list(zones)
    for container in world.get("containers") or []:
        container["ownership"] = classify_container(
            container,
            zones=zones,
            save_id=save_id,
            explicitly_opened=explicitly_opened,
            manual_owned=manual_owned,
        )
    for ground in world.get("groundItems") or []:
        ground["ownership"] = classify_ground_item(
            ground,
            zones=zones,
            save_id=save_id,
        )
    return world

