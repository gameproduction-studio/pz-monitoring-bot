"""Build 42.20.2 static-corpse reader.

The layout is derived from the installed IsoDeadBody, IsoMovingObject,
SurvivorDesc, HumanVisual, AnimalVisual, AnimalGene and AnimalAllele classes.
The caller supplies the already verified item/container parser.
"""

from __future__ import annotations

from typing import Any

from .pz_save_scanner import (
    ParseError,
    Reader,
    parse_container,
    parse_lua_table,
    skip_item_visual,
)


def _skip_survivor_desc(reader: Reader) -> dict[str, Any]:
    result = {
        "descriptorId": reader.i32(),
        "forename": reader.string(),
        "surname": reader.string(),
        "torso": reader.string(),
        "gender": "female" if reader.i32() == 1 else "male",
        "profession": reader.string(),
    }
    if reader.i32() == 1:
        extra_count = reader.i32()
        if not 0 <= extra_count <= 1000:
            raise ParseError(f"invalid survivor descriptor extra count {extra_count}")
        result["extras"] = [reader.string() for _ in range(extra_count)]
    perk_count = reader.i32()
    if not 0 <= perk_count <= 1000:
        raise ParseError(f"invalid survivor descriptor perk count {perk_count}")
    result["perks"] = [
        {"perk": reader.string(), "level": reader.i32()} for _ in range(perk_count)
    ]
    result["voicePrefix"] = reader.string()
    result["voicePitch"] = reader.f32()
    result["voiceType"] = reader.i32()
    return result


def _skip_human_visual(reader: Reader) -> None:
    flags = reader.u8()
    for bit in (4, 2, 8):
        if flags & bit:
            reader.raw(3)
    reader.raw(3)
    for bit in (0x40, 0x10, 0x20):
        if flags & bit:
            reader.string()
    for _ in range(3):
        reader.raw(reader.u8())
    visual_count = reader.u8()
    for _ in range(visual_count):
        skip_item_visual(reader)
    reader.string()
    natural_flags = reader.u8()
    if natural_flags & 4:
        reader.raw(3)
    if natural_flags & 2:
        reader.raw(3)


def _skip_animal_allele(reader: Reader) -> None:
    reader.string()
    reader.raw(8)
    reader.u8()
    reader.string()


def _skip_animal_genetics(reader: Reader) -> None:
    gene_count = reader.u8()
    for _ in range(gene_count):
        reader.i32()
        reader.string()
        _skip_animal_allele(reader)
        _skip_animal_allele(reader)
    disorder_count = reader.u8()
    for _ in range(disorder_count):
        reader.string()


def _instance_ids(items: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for item in items:
        raw = item.get("itemIds") or []
        quantity = max(int(item.get("quantity") or len(raw) or 1), 1)
        ids = [str(value) for value in raw]
        while len(ids) < quantity:
            ids.append(f"synthetic:{item.get('fullType')}:{len(result)}")
        result.extend(ids[:quantity])
    return result


def _equipment_records(reader: Reader, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    item_ids = _instance_ids(items)

    def read_group(count: int) -> list[dict[str, Any]]:
        records = []
        for _ in range(count):
            location = reader.string()
            index = reader.i16()
            record: dict[str, Any] = {"location": location, "inventoryIndex": index}
            if 0 <= index < len(item_ids):
                record["itemId"] = item_ids[index]
            records.append(record)
        return records

    worn = read_group(reader.u8())
    attached = read_group(reader.u8())
    return worn, attached


def read_dead_body(
    reader: Reader,
    *,
    item_types: dict[int, str],
    definitions: dict[str, dict[str, Any]],
    x: int,
    y: int,
    z: int,
    corpse_index: int,
) -> dict[str, Any]:
    serialized = reader.u8()
    class_id = reader.u8()
    if not serialized or class_id != 11:
        raise ParseError(
            f"invalid static moving object serialized={serialized} class={class_id}"
        )

    moving: dict[str, Any] = {
        "offsetX": reader.f32(),
        "offsetY": reader.f32(),
        "savedX": reader.f32(),
        "savedY": reader.f32(),
        "savedZ": reader.f32(),
        "direction": reader.i32(),
    }
    if reader.u8():
        moving["lua"] = parse_lua_table(reader)

    female = bool(reader.u8())
    was_zombie = bool(reader.u8())
    is_animal = bool(reader.u8())
    animal: dict[str, Any] | None = None
    if is_animal:
        animal = {"type": reader.string(), "size": reader.f32()}
        _skip_animal_genetics(reader)
        animal.update(
            customName=reader.string(),
            corpseItem=reader.string(),
            weight=reader.f32(),
            inventoryIcon=reader.string(),
        )
        reader.raw(12)

    object_id = reader.i16()
    object_id_type = reader.u8()
    is_server_save = bool(reader.u8())
    persistent_outfit_id = reader.i32()
    descriptor = _skip_survivor_desc(reader) if reader.u8() else None

    visual_type = reader.u8()
    if visual_type == 0:
        _skip_human_visual(reader)
    elif visual_type == 1:
        reader.string()
        reader.u8()
    else:
        raise ParseError(f"invalid corpse visual type {visual_type}")

    corpse: dict[str, Any] = {
        "corpseId": (
            f"corpse:{object_id}"
            if object_id >= 0
            else f"corpse:{x}:{y}:{z}:{corpse_index}"
        ),
        "objectId": object_id,
        "objectIdType": object_id_type,
        "position": {"x": x, "y": y, "z": z},
        "female": female,
        "wasZombie": was_zombie,
        "isAnimal": is_animal,
        "animal": animal,
        "persistentOutfitId": persistent_outfit_id,
        "descriptor": descriptor,
        "moving": moving,
        "serverSave": is_server_save,
    }

    if reader.u8():
        saved_container_id = reader.i32()
        parsed = parse_container(reader, item_types, definitions)
        worn, attached = _equipment_records(reader, parsed["items"])
        corpse["inventory"] = {
            "containerId": corpse["corpseId"],
            "kind": "corpse",
            "position": corpse["position"],
            "savedContainerId": saved_container_id,
            "containerType": parsed["type"],
            "capacity": parsed["capacity"],
            "explored": parsed["explored"],
            "hasBeenLooted": parsed["hasBeenLooted"],
            "worn": worn,
            "attached": attached,
            "items": parsed["items"],
        }
    else:
        corpse["inventory"] = None

    corpse.update(
        deathTime=reader.f32(),
        reanimateTime=reader.f32(),
        flags=reader.u8(),
        wasSkeleton=bool(reader.u8()),
        angle=reader.f32(),
        zombieRotStageAtDeath=reader.u8(),
        animalRotStageAtDeath=reader.u8(),
        rottenTexture=reader.string(),
        skeletonInventoryIcon=reader.string(),
        crawling=bool(reader.u8()),
        fakeDead=bool(reader.u8()),
    )
    ragdoll = bool(reader.u8())
    corpse["ragdollFall"] = ragdoll
    if ragdoll:
        bone_count = reader.i32()
        if not 0 <= bone_count <= 1000:
            raise ParseError(f"invalid corpse ragdoll bone count {bone_count}")
        reader.raw(bone_count * 44)
    return corpse

