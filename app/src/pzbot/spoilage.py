"""Actionable food-storage and spoilage alerts."""

from __future__ import annotations

from typing import Any, Iterable


NEVER_ROTS = 1_000_000_000
COLD_TYPES = {"fridge", "refrigerator", "freezer"}
FREEZER_TYPES = {"freezer"}


def _storage(item: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source") or {}
    container_type = str(source.get("containerType") or "").lower()
    if container_type in FREEZER_TYPES:
        return {
            "kind": "freezer",
            "coldStorageDetected": True,
            "powerStatus": "not_monitored_v1",
            "appropriate": True,
        }
    if container_type in COLD_TYPES or "fridge" in container_type:
        return {
            "kind": "fridge",
            "coldStorageDetected": True,
            "powerStatus": "not_monitored_v1",
            "appropriate": True,
        }
    return {
        "kind": "unrefrigerated",
        "coldStorageDetected": False,
        "powerStatus": "not_applicable",
        "appropriate": False,
    }


def _remaining_hours(threshold: Any, age: Any, multiplier: float = 1.0) -> float | None:
    if not isinstance(threshold, (int, float)) or threshold >= NEVER_ROTS:
        return None
    if not isinstance(age, (int, float)) or multiplier <= 0:
        return None
    return round(max(0.0, float(threshold) - float(age)) * 24.0 / multiplier, 2)


def _severity(hours_to_stale: float | None, hours_to_rotten: float | None) -> str:
    if hours_to_rotten is not None and hours_to_rotten <= 0:
        return "critical"
    if hours_to_stale is not None and hours_to_stale <= 12:
        return "critical"
    if hours_to_stale is not None and hours_to_stale <= 24:
        return "high"
    if hours_to_rotten is not None and hours_to_rotten <= 72:
        return "medium"
    return "low"


def build_spoilage_alerts(
    items: Iterable[dict[str, Any]],
    *,
    food_rot_speed_multiplier: float = 1.0,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for item in items:
        if item.get("itemType") != "food":
            continue
        off_age_max = item.get("offAgeMax")
        if not isinstance(off_age_max, (int, float)) or off_age_max >= NEVER_ROTS:
            continue

        storage = _storage(item)
        age = item.get("age")
        hours_to_stale = _remaining_hours(
            item.get("offAge"),
            age,
            food_rot_speed_multiplier,
        )
        hours_to_rotten = _remaining_hours(
            off_age_max,
            age,
            food_rot_speed_multiplier,
        )
        freezing_time = float(item.get("freezingTime") or (100 if item.get("frozen") else 0))
        hours_to_thaw = (
            round(max(0.0, min(100.0, freezing_time)) / 100.0 * 1.5, 2)
            if freezing_time > 0 and storage["kind"] != "freezer"
            else None
        )

        common = {
            "itemId": item.get("itemId"),
            "fullType": item.get("fullType"),
            "name_ru": item.get("name_ru"),
            "location": (item.get("source") or {}).get("path"),
            "freshness": item.get("freshness"),
            "frozen": bool(item.get("frozen")),
            "freezingTime": item.get("freezingTime"),
            "storage": storage,
            "estimatedGameHoursToStale": hours_to_stale,
            "estimatedGameHoursToRotten": hours_to_rotten,
            "estimateConfidence": "medium",
            "assumptions": {
                "foodRotSpeedMultiplier": food_rot_speed_multiplier,
                "ageUnit": "game_days",
                "roomTemperatureAfterThaw": True,
                "sandboxSettingsParsed": False,
            },
        }

        if not storage["appropriate"]:
            alerts.append(
                {
                    "alertId": f"food-storage:{item.get('itemId')}",
                    "kind": "perishable_in_unsuitable_storage",
                    "severity": _severity(hours_to_stale, hours_to_rotten),
                    "messageCode": "move_to_fridge_or_freezer",
                    **common,
                }
            )

        if hours_to_thaw is not None:
            alerts.append(
                {
                    "alertId": f"food-thaw:{item.get('itemId')}",
                    "kind": "frozen_food_thawing_outside_freezer",
                    "severity": "high" if hours_to_thaw <= 1 else "medium",
                    "estimatedGameHoursToFullyThaw": hours_to_thaw,
                    "messageCode": "return_to_freezer",
                    **common,
                }
            )

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    alerts.sort(
        key=lambda alert: (
            order.get(str(alert.get("severity")), 9),
            alert.get("estimatedGameHoursToRotten")
            if alert.get("estimatedGameHoursToRotten") is not None
            else float("inf"),
            str(alert.get("itemId")),
        )
    )
    return alerts

