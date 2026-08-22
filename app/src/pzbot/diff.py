from __future__ import annotations

import datetime as dt
import math
from typing import Any, Iterable

MATERIAL_FOOD_FIELDS = (
    "freshness",
    "frozen",
    "freezingTime",
    "cooked",
    "burnt",
    "remainingFraction",
    "currentUses",
)


def _item_ids(item: dict[str, Any]) -> list[str]:
    raw = item.get("itemIds")
    values = raw if isinstance(raw, list) else ([] if raw is None else [raw])
    quantity = max(int(item.get("quantity") or len(values) or 1), 1)
    result = [str(value) for value in values]
    while len(result) < quantity:
        result.append(f"synthetic:{item.get('fullType')}:{item.get('location')}:{len(result)}")
    return result[:quantity]


def walk_instances(items: Iterable[dict[str, Any]], parents: tuple[str, ...] = ()) -> Iterable[dict[str, Any]]:
    for grouped in items:
        ids = _item_ids(grouped)
        for item_id in ids:
            instance = {key: value for key, value in grouped.items() if key != "contents"}
            instance.update(itemId=item_id, quantity=1, parentItemIds=list(parents))
            yield instance
        contents = grouped.get("contents") or []
        if contents:
            yield from walk_instances(contents, parents + (ids[0],))


def flatten(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in walk_instances(snapshot.get("inventory", {}).get("items", [])):
        if item["itemId"] in result:
            raise ValueError(f"Duplicate itemId: {item['itemId']}")
        result[item["itemId"]] = item
    return result


def condition_percent(item: dict[str, Any]) -> float | None:
    value, maximum = item.get("condition"), item.get("conditionMax")
    if value is None or not maximum:
        return None
    return round(float(value) * 100.0 / float(maximum), 2)


def location_signature(item: dict[str, Any]) -> str:
    path = str(item.get("location") or "mainInventory")
    worn = ",".join(str(value) for value in item.get("equippedLocations") or [])
    hand = "both" if item.get("primaryHand") and item.get("secondaryHand") else "primary" if item.get("primaryHand") else "secondary" if item.get("secondaryHand") else ""
    return f"{path}|hand={hand}|worn={worn}"


def _changed(old: Any, new: Any) -> bool:
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return not math.isclose(float(old), float(new), rel_tol=1e-6, abs_tol=1e-6)
    return old != new


def compare(old_snapshot: dict[str, Any] | None, new_snapshot: dict[str, Any], timestamp: str | None = None) -> list[dict[str, Any]]:
    before = flatten(old_snapshot) if old_snapshot else {}
    after = flatten(new_snapshot)
    timestamp = timestamp or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    events: list[dict[str, Any]] = []

    def emit(kind: str, item: dict[str, Any], **extra: Any) -> None:
        events.append({"time": timestamp, "kind": kind, "itemId": item["itemId"], "fullType": item.get("fullType"), "name_ru": item.get("name_ru"), **extra})

    for item_id in sorted(after.keys() - before.keys()):
        emit("incoming", after[item_id], quantityDelta=1, to=location_signature(after[item_id]), interpretation="appeared_in_monitored_state", acquisitionConfirmed=False)
    for item_id in sorted(before.keys() - after.keys()):
        emit("outgoing", before[item_id], quantityDelta=-1, from_=location_signature(before[item_id]), interpretation="disappeared_from_monitored_state", consumptionConfirmed=False)
    for item_id in sorted(before.keys() & after.keys()):
        old, new = before[item_id], after[item_id]
        old_location, new_location = location_signature(old), location_signature(new)
        if old_location != new_location:
            emit("move", new, quantityDelta=0, from_=old_location, to=new_location)
        old_condition, new_condition = condition_percent(old), condition_percent(new)
        if _changed(old_condition, new_condition):
            emit("condition_change", new, old=old_condition, new=new_condition)
        food_changes = {field: {"old": old.get(field), "new": new.get(field)} for field in MATERIAL_FOOD_FIELDS if _changed(old.get(field), new.get(field)) and not (field == "remainingFraction" and isinstance(old.get(field), (int, float)) and float(old[field]) > 1.0)}
        if food_changes and (old.get("itemType") == "food" or new.get("itemType") == "food"):
            if old.get("freshness") != "rotten" and new.get("freshness") == "rotten":
                kind = "food_rotted"
            elif old.get("frozen") and not new.get("frozen"):
                kind = "food_thawed"
            elif not old.get("frozen") and new.get("frozen"):
                kind = "food_frozen"
            elif "remainingFraction" in food_changes or "currentUses" in food_changes:
                kind = "food_quantity_decreased"
            else:
                kind = "food_state_change"
            emit(kind, new, changes=food_changes)
        old_ammo, new_ammo = int(old.get("currentAmmoCount") or 0), int(new.get("currentAmmoCount") or 0)
        if old_ammo != new_ammo:
            emit("weapon_ammo_change", new, old=old_ammo, new=new_ammo, ammoDelta=new_ammo - old_ammo)

    loose_delta = sum(1 for item in after.values() if item.get("fullType") == "Base.ShotgunShells") - sum(1 for item in before.values() if item.get("fullType") == "Base.ShotgunShells")
    for event in events:
        if event["kind"] != "weapon_ammo_change":
            continue
        delta = event["ammoDelta"]
        event["classification"] = "loaded" if delta > 0 and loose_delta <= -delta else "unloaded" if delta < 0 and loose_delta >= -delta else "removed_from_weapon_source_uncertain" if delta < 0 else "source_uncertain"
    return events
