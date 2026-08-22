"""Instance-level state flattening and change detection."""

from __future__ import annotations

import datetime as dt
import math
from typing import Any, Iterable


FOOD_FIELDS = (
    "age",
    "lastAged",
    "freshness",
    "frozen",
    "freezingTime",
    "cooked",
    "burnt",
    "remainingFraction",
    "currentUses",
)


def _ids(item: dict[str, Any], source_path: str) -> list[str]:
    raw = item.get("itemIds")
    values = raw if isinstance(raw, list) else ([] if raw is None else [raw])
    quantity = max(int(item.get("quantity") or len(values) or 1), 1)
    result = [str(value) for value in values]
    while len(result) < quantity:
        result.append(f"synthetic:{item.get('fullType')}:{source_path}:{len(result)}")
    return result[:quantity]


def _walk_items(
    items: Iterable[dict[str, Any]],
    *,
    source: dict[str, Any],
    parent_ids: tuple[str, ...] = (),
) -> Iterable[dict[str, Any]]:
    for grouped in items:
        ids = _ids(grouped, str(source["path"]))
        for item_id in ids:
            instance = {key: value for key, value in grouped.items() if key != "contents"}
            instance.update(
                itemId=item_id,
                quantity=1,
                source=dict(source),
                parentItemIds=list(parent_ids),
            )
            yield instance
        contents = grouped.get("contents") or []
        if contents:
            nested_source = dict(source)
            nested_source["path"] = f"{source['path']}/item:{ids[0]}"
            nested_source["containerId"] = f"item:{ids[0]}"
            nested_source["containerKind"] = "portable"
            nested_source["containerDisplayName"] = (
                grouped.get("customName") or grouped.get("name_ru") or grouped.get("fullType")
            )
            nested_source["parentItemId"] = ids[0]
            yield from _walk_items(
                contents,
                source=nested_source,
                parent_ids=parent_ids + (ids[0],),
            )


def flatten_state(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    def add(instance: dict[str, Any]) -> None:
        item_id = instance["itemId"]
        if item_id in result:
            raise ValueError(
                f"Duplicate itemId {item_id}: "
                f"{result[item_id]['source']['path']} and {instance['source']['path']}"
            )
        result[item_id] = instance

    character = snapshot.get("character") or {}
    for instance in _walk_items(
        (character.get("inventory") or {}).get("items") or [],
        source={
            "scope": "character",
            "path": "character/mainInventory",
            "containerId": "character:mainInventory",
            "owned": True,
            "ownershipConfidence": "exact",
        },
    ):
        add(instance)

    world = snapshot.get("world") or {}
    for container in world.get("containers") or []:
        ownership = container.get("ownership") or {}
        source = {
            "scope": "world",
            "path": f"world/container:{container.get('containerId')}",
            "containerId": container.get("containerId"),
            "containerKind": container.get("kind"),
            "containerType": container.get("containerType"),
            "position": container.get("position"),
            "containerDisplayName": container.get("displayName"),
            "containerCustomName": container.get("customName"),
            "stale": bool((container.get("observation") or {}).get("stale"))
            if isinstance(container.get("observation"), dict) else False,
            "owned": bool(ownership.get("owned")),
            "ownershipConfidence": ownership.get("confidence", "none"),
        }
        worn_by_id = {
            str(record["itemId"]): record["location"]
            for record in container.get("worn") or []
            if record.get("itemId") is not None
        }
        attached_by_id = {
            str(record["itemId"]): record["location"]
            for record in container.get("attached") or []
            if record.get("itemId") is not None
        }
        for instance in _walk_items(container.get("items") or [], source=source):
            if instance["itemId"] in worn_by_id:
                instance["corpseWornLocation"] = worn_by_id[instance["itemId"]]
            if instance["itemId"] in attached_by_id:
                instance["corpseAttachedLocation"] = attached_by_id[instance["itemId"]]
            add(instance)

    for ground in world.get("groundItems") or []:
        ownership = ground.get("ownership") or {}
        for instance in _walk_items(
            [ground["item"]],
            source={
                "scope": "world",
                "path": f"world/ground:{ground.get('groundItemId')}",
                "groundItemId": ground.get("groundItemId"),
                "position": ground.get("position"),
                "owned": bool(ownership.get("owned")),
                "ownershipConfidence": ownership.get("confidence", "none"),
            },
        ):
            add(instance)

    for vehicle in world.get("vehicles") or []:
        for container in vehicle.get("containers") or []:
            ownership = container.get("ownership") or {}
            for instance in _walk_items(
                container.get("items") or [],
                source={
                    "scope": "vehicle",
                    "path": (
                        f"world/vehicle:{vehicle.get('vehicleId')}"
                        f"/container:{container.get('containerId')}"
                    ),
                    "vehicleId": vehicle.get("vehicleId"),
                    "containerId": container.get("containerId"),
                    "containerType": container.get("containerType"),
                    "containerDisplayName": (
                        container.get("displayName") or vehicle.get("name")
                    ),
                    "vehicleName": vehicle.get("name"),
                    "position": vehicle.get("position"),
                    "owned": bool(ownership.get("owned")),
                    "ownershipConfidence": ownership.get("confidence", "none"),
                },
            ):
                add(instance)
    return result


def condition_percent(item: dict[str, Any]) -> float | None:
    value = item.get("condition")
    maximum = item.get("conditionMax")
    if value is None or not maximum:
        return None
    return round(float(value) * 100.0 / float(maximum), 2)


def location_signature(item: dict[str, Any]) -> str:
    source = item.get("source") or {}
    hand = (
        "both"
        if item.get("primaryHand") and item.get("secondaryHand")
        else "primary"
        if item.get("primaryHand")
        else "secondary"
        if item.get("secondaryHand")
        else ""
    )
    worn = ",".join(str(value) for value in item.get("equippedLocations") or [])
    attached = str(item.get("attachedLocation") or "")
    corpse_worn = str(item.get("corpseWornLocation") or "")
    corpse_attached = str(item.get("corpseAttachedLocation") or "")
    return (
        f"{source.get('path')}|hand={hand}|worn={worn}"
        f"|attached={attached}"
        f"|corpseWorn={corpse_worn}|corpseAttached={corpse_attached}"
    )


def _changed(old: Any, new: Any) -> bool:
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return not math.isclose(float(old), float(new), rel_tol=1e-6, abs_tol=1e-6)
    return old != new


def compare_states(
    old_snapshot: dict[str, Any] | None,
    new_snapshot: dict[str, Any],
    *,
    timestamp: str | None = None,
) -> list[dict[str, Any]]:
    timestamp = timestamp or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    new_save = (new_snapshot.get("save") or {}).get("id")
    old_save = (old_snapshot.get("save") or {}).get("id") if old_snapshot else None
    if old_snapshot is not None and old_save != new_save:
        return [
            {
                "time": timestamp,
                "kind": "save_switched",
                "fromSaveId": old_save,
                "toSaveId": new_save,
            }
        ]

    before = flatten_state(old_snapshot) if old_snapshot else {}
    after = flatten_state(new_snapshot)
    events: list[dict[str, Any]] = []

    def emit(kind: str, item: dict[str, Any], **extra: Any) -> None:
        events.append(
            {
                "time": timestamp,
                "kind": kind,
                "saveId": new_save,
                "itemId": item["itemId"],
                "fullType": item.get("fullType"),
                "name_ru": item.get("name_ru"),
                **extra,
            }
        )

    for item_id in sorted(after.keys() - before.keys()):
        emit(
            "incoming",
            after[item_id],
            quantityDelta=1,
            to=location_signature(after[item_id]),
            interpretation="appeared_in_monitored_state",
            acquisitionConfirmed=False,
        )
    for item_id in sorted(before.keys() - after.keys()):
        emit(
            "outgoing",
            before[item_id],
            quantityDelta=-1,
            **{"from": location_signature(before[item_id])},
            interpretation="disappeared_from_monitored_state",
            consumptionConfirmed=False,
        )

    for item_id in sorted(before.keys() & after.keys()):
        old = before[item_id]
        new = after[item_id]
        old_location = location_signature(old)
        new_location = location_signature(new)
        if old_location != new_location:
            emit("move", new, quantityDelta=0, **{"from": old_location}, to=new_location)

        old_owned = bool((old.get("source") or {}).get("owned"))
        new_owned = bool((new.get("source") or {}).get("owned"))
        if old_owned != new_owned:
            emit("ownership_change", new, old=old_owned, new=new_owned)

        old_condition = condition_percent(old)
        new_condition = condition_percent(new)
        if _changed(old_condition, new_condition):
            emit("condition_change", new, old=old_condition, new=new_condition)

        changes = {
            field: {"old": old.get(field), "new": new.get(field)}
            for field in FOOD_FIELDS
            if _changed(old.get(field), new.get(field))
        }
        if changes and (old.get("itemType") == "food" or new.get("itemType") == "food"):
            if old.get("freshness") != "rotten" and new.get("freshness") == "rotten":
                kind = "food_rotted"
            elif old.get("frozen") and not new.get("frozen"):
                kind = "food_thawed"
            elif not old.get("frozen") and new.get("frozen"):
                kind = "food_frozen"
            elif "remainingFraction" in changes or "currentUses" in changes:
                kind = "food_quantity_decreased"
            else:
                kind = "food_state_change"
            emit(kind, new, changes=changes)

        old_ammo = int(old.get("currentAmmoCount") or 0)
        new_ammo = int(new.get("currentAmmoCount") or 0)
        if old_ammo != new_ammo:
            emit(
                "weapon_ammo_change",
                new,
                old=old_ammo,
                new=new_ammo,
                ammoDelta=new_ammo - old_ammo,
            )

    loose_delta = sum(
        1 for item in after.values() if item.get("fullType") == "Base.ShotgunShells"
    ) - sum(
        1 for item in before.values() if item.get("fullType") == "Base.ShotgunShells"
    )
    for event in events:
        if event["kind"] != "weapon_ammo_change":
            continue
        delta = event["ammoDelta"]
        event["classification"] = (
            "loaded"
            if delta > 0 and loose_delta <= -delta
            else "unloaded"
            if delta < 0 and loose_delta >= -delta
            else "removed_from_weapon_source_uncertain"
            if delta < 0
            else "source_uncertain"
        )

    before_vehicles = {
        str(vehicle.get("vehicleId")): vehicle
        for vehicle in ((old_snapshot or {}).get("world") or {}).get("vehicles") or []
    }
    after_vehicles = {
        str(vehicle.get("vehicleId")): vehicle
        for vehicle in (new_snapshot.get("world") or {}).get("vehicles") or []
    }

    def emit_vehicle(kind: str, vehicle: dict[str, Any], **extra: Any) -> None:
        events.append(
            {
                "time": timestamp,
                "kind": kind,
                "saveId": new_save,
                "vehicleId": str(vehicle.get("vehicleId")),
                "vehicleName": vehicle.get("name"),
                "scriptFullType": vehicle.get("scriptFullType"),
                **extra,
            }
        )

    for vehicle_id in sorted(after_vehicles.keys() - before_vehicles.keys()):
        emit_vehicle("vehicle_claimed", after_vehicles[vehicle_id])
    for vehicle_id in sorted(before_vehicles.keys() - after_vehicles.keys()):
        emit_vehicle("vehicle_removed", before_vehicles[vehicle_id])

    for vehicle_id in sorted(before_vehicles.keys() & after_vehicles.keys()):
        old_vehicle = before_vehicles[vehicle_id]
        new_vehicle = after_vehicles[vehicle_id]
        old_fuel = (old_vehicle.get("fuel") or {}).get("fraction")
        new_fuel = (new_vehicle.get("fuel") or {}).get("fraction")
        if _changed(old_fuel, new_fuel):
            emit_vehicle(
                "vehicle_fuel_change",
                new_vehicle,
                oldFraction=old_fuel,
                newFraction=new_fuel,
                oldPercent=round(float(old_fuel) * 100, 2) if old_fuel is not None else None,
                newPercent=round(float(new_fuel) * 100, 2) if new_fuel is not None else None,
            )
        if _changed(old_vehicle.get("batteryCharge"), new_vehicle.get("batteryCharge")):
            emit_vehicle(
                "vehicle_battery_change",
                new_vehicle,
                old=old_vehicle.get("batteryCharge"),
                new=new_vehicle.get("batteryCharge"),
            )
        if _changed(old_vehicle.get("overallCondition"), new_vehicle.get("overallCondition")):
            emit_vehicle(
                "vehicle_condition_change",
                new_vehicle,
                old=old_vehicle.get("overallCondition"),
                new=new_vehicle.get("overallCondition"),
            )
        if old_vehicle.get("position") != new_vehicle.get("position"):
            emit_vehicle(
                "vehicle_moved",
                new_vehicle,
                oldPosition=old_vehicle.get("position"),
                newPosition=new_vehicle.get("position"),
            )

        old_parts = {
            str(part.get("partId")): part for part in old_vehicle.get("parts") or []
        }
        new_parts = {
            str(part.get("partId")): part for part in new_vehicle.get("parts") or []
        }
        for part_id in sorted(old_parts.keys() & new_parts.keys()):
            old_condition = old_parts[part_id].get("condition")
            new_condition = new_parts[part_id].get("condition")
            if _changed(old_condition, new_condition):
                emit_vehicle(
                    "vehicle_part_condition_change",
                    new_vehicle,
                    partId=part_id,
                    partName=new_parts[part_id].get("nameLocalized"),
                    old=old_condition,
                    new=new_condition,
                )
    return events

