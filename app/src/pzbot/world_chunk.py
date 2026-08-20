"""Read-only parser for Build 42.20.2 world chunk containers.

The format implemented here is derived from the locally installed Build
42.20.2 classes (worldVersion 249).  Unknown object subclasses fail the
individual chunk instead of guessing a byte offset.  Callers can therefore
publish an explicit coverage report and never silently return corrupted data.
"""

from __future__ import annotations

import pathlib
import re
import struct
from dataclasses import dataclass, field
from typing import Any

from .corpse import read_dead_body
from .pz_save_scanner import (
    ParseError,
    Reader,
    decorate_items,
    parse_container,
    parse_item_definitions,
    parse_world_dictionary,
)


WORLD_VERSION = 249

OBJECT_NAMES = {
    0: "IsoObject",
    1: "Player",
    2: "Survivor",
    3: "Zombie",
    4: "Pushable",
    5: "WheelieBin",
    6: "WorldInventoryItem",
    7: "Jukebox",
    8: "Curtain",
    9: "Radio",
    10: "Television",
    11: "DeadBody",
    12: "Barbecue",
    13: "ClothingDryer",
    14: "ClothingWasher",
    15: "Fireplace",
    16: "Stove",
    17: "Door",
    18: "Thumpable",
    19: "IsoTrap",
    20: "IsoBrokenGlass",
    21: "IsoCarBatteryCharger",
    22: "IsoGenerator",
    23: "IsoCompost",
    24: "Mannequin",
    26: "Window",
    27: "Barricade",
    28: "Tree",
    29: "LightSwitch",
    30: "ZombieGiblets",
    31: "MolotovCocktail",
    32: "Fire",
    33: "Vehicle",
    34: "CombinationWasherDryer",
    35: "StackedWasherDryer",
    36: "Animal",
    37: "FeedingTrough",
    38: "IsoHutch",
    39: "IsoAnimalTrack",
    40: "ButcherHook",
    41: "IsoWindowFrame",
}


@dataclass
class ChunkResult:
    path: pathlib.Path
    wx: int
    wy: int
    world_version: int
    containers: list[dict[str, Any]] = field(default_factory=list)
    ground_items: list[dict[str, Any]] = field(default_factory=list)
    corpses: list[dict[str, Any]] = field(default_factory=list)
    object_counts: dict[str, int] = field(default_factory=dict)
    bytes_consumed: int = 0


def _i64(reader: Reader) -> int:
    reader.require(8)
    value = struct.unpack_from(">q", reader.data, reader.pos)[0]
    reader.pos += 8
    return value


def _u64(reader: Reader) -> int:
    reader.require(8)
    value = struct.unpack_from(">Q", reader.data, reader.pos)[0]
    reader.pos += 8
    return value


def _skip_entity(reader: Reader) -> None:
    component_count = reader.u8()
    for _ in range(component_count):
        block_length = reader.i32()
        if block_length < 2:
            raise ParseError(f"invalid entity component block length {block_length} at {reader.pos - 4}")
        reader.raw(block_length)


def _skip_erosion_category(reader: Reader) -> None:
    region = reader.u8()
    category = reader.u8()
    reader.u8()  # display season
    flags = reader.u8()
    if flags & 0x80:
        reader.u8()  # stage > 4

    extra_fixed = {
        (0, 0): 4,  # NatureTrees
        (0, 1): 4,  # NatureBush
        (0, 2): 3,  # NaturePlants
        (0, 3): 5,  # NatureGeneric
        (1, 0): 9,  # StreetCracks
        (3, 0): 1,  # Flowerbed
    }
    if (region, category) in extra_fixed:
        reader.raw(extra_fixed[(region, category)])
        return
    if (region, category) == (2, 0):  # WallVines
        reader.raw(8)
        has_top = reader.u8()
        if has_top:
            reader.raw(7)
        return
    if (region, category) == (2, 1):  # WallCracks
        reader.raw(11)
        has_top = reader.u8()
        if has_top:
            reader.raw(11)
        return
    raise ParseError(f"unknown erosion category {region}/{category} at {reader.pos}")


def _skip_square_erosion(reader: Reader) -> None:
    flags = reader.u8()
    if not (flags & 1):
        return
    reader.raw(3)  # noiseMain, soil, magicNum
    count = 0
    for bit, value in ((4, 1), (8, 2), (16, 3), (32, 4)):
        if flags & bit:
            count = value
            break
    if flags & 64:
        count = reader.u8()
    for _ in range(count):
        _skip_erosion_category(reader)


def _skip_chunk_erosion(reader: Reader) -> None:
    if reader.u8():
        reader.raw(17)


def _read_base_object(
    reader: Reader,
    *,
    definitions: dict[str, dict[str, Any]],
    item_types: dict[int, str],
    x: int,
    y: int,
    z: int,
    class_id: int,
    containers: list[dict[str, Any]],
) -> dict[str, Any]:
    sprite_id = reader.i32()
    header = reader.u8()
    object_info: dict[str, Any] = {
        "objectClassId": class_id,
        "objectClass": OBJECT_NAMES.get(class_id, f"Unknown({class_id})"),
        "spriteId": sprite_id,
    }

    if header & 1:
        count = 1 if header & 2 else reader.u8()
        for _ in range(count):
            reader.i32()  # attached sprite id
            flags = reader.u8()
            if flags & 2:
                reader.raw(15)  # xyz floats + rgb packed bytes
            if flags & 16:
                reader.f32()
    if header & 4:
        flags = reader.u8()
        if flags & 4:
            reader.u8()
        elif flags & 8:
            object_info["objectName"] = reader.string()
        if flags & 16:
            reader.i32()
        elif flags & 32:
            object_info["spriteName"] = reader.string()
    if header & 8:
        reader.raw(3)
    if not (header & 64):
        return object_info

    bits = reader.u16()
    if bits & 1:
        reader.raw(reader.u8() * 8)  # IsoWallBloodSplat
    if bits & 2:
        count = reader.u8()
        for index in range(count):
            parsed = parse_container(reader, item_types, definitions)
            containers.append(
                {
                    "containerId": f"world:{x}:{y}:{z}:{sprite_id}:{index}",
                    "kind": "stationary",
                    "position": {"x": x, "y": y, "z": z},
                    "object": dict(object_info),
                    "containerIndex": index,
                    "containerType": parsed["type"],
                    "capacity": parsed["capacity"],
                    "explored": parsed["explored"],
                    "hasBeenLooted": parsed["hasBeenLooted"],
                    "items": parsed["items"],
                }
            )
    if bits & 4:
        from .pz_save_scanner import parse_lua_table

        parse_lua_table(reader)
    if bits & 16:
        reader.i32()
    if bits & 64:
        reader.f32()
    if bits & 128:
        reader.f32()
    if bits & 256:
        if bits & 512:
            reader.string()
        else:
            reader.i32()
    if bits & 1024:
        reader.raw(4)
    if bits & 4096:
        _skip_entity(reader)
    if bits & 8192:
        reader.string()
    return object_info


def _skip_thumpable(reader: Reader) -> None:
    from .pz_save_scanner import parse_lua_table

    bits = _u64(reader)
    for flag in (8, 16, 32, 64, 128):
        if bits & flag:
            reader.i32()
    if bits & 0x100000:
        reader.f32()
    if bits & 0x200000:
        parse_lua_table(reader)
    if bits & 0x400000:
        parse_lua_table(reader)
    for flag in (0x4000000, 0x8000000, 0x10000000, 0x20000000):
        if bits & flag:
            reader.i32()
    if bits & 0x40000000:
        reader.i16()
    if bits & 0x80000000:
        reader.f32()
    if bits & 0x100000000:
        reader.f32()
    if bits & 0x200000000:
        reader.i32()
    if bits & 0x2000000000:
        reader.i32()
    if bits & 0x4000000000:
        reader.string()
    if bits & 0x8000000000:
        reader.f32()
    if bits & 0x40000000000:
        parse_lua_table(reader)


def _skip_device_data(reader: Reader) -> None:
    reader.string()
    reader.raw(1 + 4 + 4 + 1 + 4 + 4 + 4)
    reader.raw(4 + 4 + 4 + 2 + 4 + 4 + 4)
    if reader.u8():
        reader.i32()
        entries = reader.i32()
        if not 0 <= entries <= 1000:
            raise ParseError(f"invalid device preset count {entries}")
        for _ in range(entries):
            reader.string()
            reader.i32()
    reader.raw(2 + 1)
    if reader.u8():
        reader.string()
    reader.u8()


def _read_world_item(
    reader: Reader,
    *,
    item_types: dict[int, str],
    definitions: dict[str, dict[str, Any]],
    x: int,
    y: int,
    z: int,
) -> dict[str, Any]:
    offsets = [reader.f32() for _ in range(5)]
    data_length = reader.i32()
    data_start = reader.pos
    data_end = data_start + data_length
    if data_length < 3 or data_end > len(reader.data):
        raise ParseError(f"invalid world item length {data_length} at {data_start - 4}")

    # Reuse the verified item parser by adding the identical-count prefix used
    # by ItemContainer/CompressIdenticalItems.
    from .pz_save_scanner import parse_item_record

    synthetic = b"\x00\x00\x00\x01" + reader.data[data_start - 4 : data_end]
    item, _ = parse_item_record(synthetic, 0, item_types, definitions)
    reader.pos = data_end
    reader.f64()
    bits = reader.u8()
    if bits & 2:
        _skip_entity(reader)
    return {
        "groundItemId": f"ground:{x}:{y}:{z}:{item['itemIds'][0]}",
        "position": {"x": x, "y": y, "z": z},
        "offset": {"x": offsets[0], "y": offsets[1], "z": offsets[2]},
        "item": item,
    }


def _read_object(
    reader: Reader,
    *,
    item_types: dict[int, str],
    definitions: dict[str, dict[str, Any]],
    x: int,
    y: int,
    z: int,
    containers: list[dict[str, Any]],
    ground_items: list[dict[str, Any]],
) -> str | None:
    serialized = reader.u8()
    if not serialized:
        return None
    class_id = reader.u8()
    class_name = OBJECT_NAMES.get(class_id, f"Unknown({class_id})")

    if class_id == 6:
        ground_items.append(
            _read_world_item(
                reader,
                item_types=item_types,
                definitions=definitions,
                x=x,
                y=y,
                z=z,
            )
        )
        return class_name

    _read_base_object(
        reader,
        definitions=definitions,
        item_types=item_types,
        x=x,
        y=y,
        z=z,
        class_id=class_id,
        containers=containers,
    )

    if class_id == 0:
        return class_name
    if class_id in (9, 10):
        if reader.u8():
            _skip_device_data(reader)
    elif class_id == 8:
        reader.raw(14)
    elif class_id == 13:
        reader.u8()
    elif class_id == 14:
        reader.raw(5)
    elif class_id == 34:
        reader.raw(7)
    elif class_id == 16:
        reader.raw(11)
    elif class_id == 12:
        reader.raw(14)
        for _ in range(2):
            if reader.u8():
                reader.i32()
    elif class_id == 15:
        reader.raw(13)
    elif class_id == 17:
        reader.raw(25)
    elif class_id == 18:
        _skip_thumpable(reader)
    elif class_id == 22:
        reader.raw(14)
    elif class_id == 23:
        reader.raw(16)
    elif class_id == 20:
        pass
    elif class_id == 26:
        reader.raw(10)
        for _ in range(4):
            if reader.u8():
                reader.i32()
        reader.i32()
    elif class_id == 29:
        reader.u8()
        _i64(reader)
        reader.u8()
        can_modify = reader.u8()
        if can_modify:
            reader.raw(2)
            if reader.u8():
                reader.string()
            reader.raw(20)
        _i64(reader)
        reader.i32()
    elif class_id == 28:
        reader.raw(2)
    elif class_id == 41:
        reader.u8()
    else:
        raise ParseError(f"unsupported object class {class_id} ({class_name}) at {reader.pos}")
    return class_name


def _read_square(
    reader: Reader,
    *,
    item_types: dict[int, str],
    definitions: dict[str, dict[str, Any]],
    x: int,
    y: int,
    z: int,
    result: ChunkResult,
) -> None:
    square_start = reader.pos
    _skip_square_erosion(reader)
    erosion_end = reader.pos
    header = reader.u8()
    if header & 1:
        count = 1
        if header & 2:
            count = 2
        elif header & 4:
            count = 3
        elif header & 8:
            count = reader.u16()
        square_trace: list[str] = []
        for object_index in range(count):
            object_start = reader.pos
            reader.u8()  # special/world flags
            try:
                name = _read_object(
                    reader,
                    item_types=item_types,
                    definitions=definitions,
                    x=x,
                    y=y,
                    z=z,
                    containers=result.containers,
                    ground_items=result.ground_items,
                )
            except ParseError as exc:
                raise ParseError(
                    f"{exc}; square={x},{y},{z} object={object_index + 1}/{count} "
                    f"start={object_start} squareStart={square_start} erosionEnd={erosion_end} "
                    f"header={header} prior={square_trace}"
                ) from exc
            if name:
                square_trace.append(name)
                result.object_counts[name] = result.object_counts.get(name, 0) + 1
    if header & 64:
        from .pz_save_scanner import parse_lua_table

        bits = reader.u8()
        if bits & 1:
            body_count = reader.u16()
            for corpse_index in range(body_count):
                corpse = read_dead_body(
                    reader,
                    item_types=item_types,
                    definitions=definitions,
                    x=x,
                    y=y,
                    z=z,
                    corpse_index=corpse_index,
                )
                result.corpses.append(corpse)
                if corpse["inventory"] is not None:
                    result.containers.append(corpse["inventory"])
                result.object_counts["DeadBody"] = result.object_counts.get("DeadBody", 0) + 1
        if bits & 2:
            parse_lua_table(reader)
        if bits & 8:
            reader.raw(12)
    reader.u8()  # visibility bits


def parse_chunk(
    path: pathlib.Path,
    *,
    item_types: dict[int, str],
    definitions: dict[str, dict[str, Any]],
) -> ChunkResult:
    match = re.search(r"[\\/]map[\\/](\-?\d+)[\\/](\-?\d+)\.bin$", str(path))
    if not match:
        raise ParseError(f"cannot derive chunk coordinates from {path}")
    wx, wy = map(int, match.groups())
    reader = Reader(path.read_bytes())
    debug_save = reader.u8()
    if debug_save:
        raise ParseError("debug chunk saves are not supported")
    world_version = reader.i32()
    if world_version != WORLD_VERSION:
        raise ParseError(f"worldVersion {world_version}, expected {WORLD_VERSION}")
    declared_length = reader.i32()
    _i64(reader)  # CRC64 value checked by the game; input remains read-only
    if declared_length > len(reader.data):
        raise ParseError(f"declared chunk length {declared_length} exceeds file size {len(reader.data)}")

    reader.u8()  # blendingDoneFull
    blend_flags = reader.u8()
    blending_partial = reader.u8()
    if blend_flags != 0x0F and blending_partial:
        reader.raw(4)
    reader.u8()  # attachmentsDoneFull
    reader.u8()  # attachmentsState flags
    attachment_count = reader.u16()
    reader.raw(attachment_count * 12)

    max_level = reader.i32()
    min_level = reader.i32()
    blood_count = reader.i32()
    if blood_count < 0:
        raise ParseError(f"invalid floor blood count {blood_count}")
    reader.raw(blood_count * 9)

    result = ChunkResult(path=path, wx=wx, wy=wy, world_version=world_version)
    for local_x in range(8):
        for local_y in range(8):
            flags_pos = reader.pos
            flags = _u64(reader)
            allowed_flags = sum(1 << (z + 32) for z in range(min_level, max_level + 1))
            if flags & ~allowed_flags:
                raise ParseError(
                    f"invalid square flags {flags:#x} at {flags_pos} for "
                    f"chunk={wx},{wy} local={local_x},{local_y}"
                )
            for z in range(min_level, max_level + 1):
                if flags & (1 << (z + 32)):
                    _read_square(
                        reader,
                        item_types=item_types,
                        definitions=definitions,
                        x=wx * 8 + local_x,
                        y=wy * 8 + local_y,
                        z=z,
                        result=result,
                    )

    _skip_chunk_erosion(reader)
    generator_count = reader.u16()
    reader.raw(generator_count * 9)
    vehicle_count = reader.u16()
    if vehicle_count:
        raise ParseError(f"legacy embedded vehicle count {vehicle_count} is unsupported")
    reader.i32()  # loot respawn hour
    room_count = reader.u16()
    reader.raw(room_count * 8)
    result.bytes_consumed = reader.pos
    if reader.pos != len(reader.data):
        raise ParseError(f"chunk ended at {reader.pos}, file has {len(reader.data)} bytes")
    return result


def scan_world_chunks(
    save_dir: pathlib.Path,
    game_dir: pathlib.Path,
    *,
    paths: list[pathlib.Path] | None = None,
) -> dict[str, Any]:
    item_types, _ = parse_world_dictionary(save_dir / "WorldDictionaryReadable.lua")
    definitions = parse_item_definitions(game_dir)
    translate_dir = game_dir / "media" / "lua" / "shared" / "Translate" / "RU"
    import json

    ru_names = json.loads((translate_dir / "ItemName.json").read_text(encoding="utf-8-sig"))
    media_ru = json.loads((translate_dir / "Recorded_Media.json").read_text(encoding="utf-8-sig"))
    media_ids: list[str] = []
    from .pz_save_scanner import parse_recorded_media

    recorded_media = save_dir / "recorded_media.bin"
    if recorded_media.is_file():
        media_ids = parse_recorded_media(recorded_media)

    chunk_paths = paths or sorted((save_dir / "map").glob("*/*.bin"))
    chunks: list[dict[str, Any]] = []
    containers: list[dict[str, Any]] = []
    ground_items: list[dict[str, Any]] = []
    corpses: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for path in chunk_paths:
        try:
            parsed = parse_chunk(path, item_types=item_types, definitions=definitions)
            for container in parsed.containers:
                decorate_items(container["items"], ru_names, media_ids, media_ru)
            for ground in parsed.ground_items:
                decorate_items([ground["item"]], ru_names, media_ids, media_ru)
            containers.extend(parsed.containers)
            ground_items.extend(parsed.ground_items)
            corpses.extend(parsed.corpses)
            chunks.append(
                {
                    "wx": parsed.wx,
                    "wy": parsed.wy,
                    "bytes": parsed.bytes_consumed,
                    "objectCounts": parsed.object_counts,
                    "containerCount": len(parsed.containers),
                    "groundItemCount": len(parsed.ground_items),
                    "corpseCount": len(parsed.corpses),
                }
            )
        except Exception as exc:
            failures.append({"file": path.name, "parent": path.parent.name, "error": str(exc)})
    return {
        "schema": "project-the-bot-monitoring/world-chunks/v1",
        "worldVersion": WORLD_VERSION,
        "coverage": {
            "candidateChunks": len(chunk_paths),
            "parsedChunks": len(chunks),
            "failedChunks": len(failures),
            "complete": not failures,
        },
        "chunks": chunks,
        "failures": failures,
        "containers": containers,
        "groundItems": ground_items,
        "corpses": corpses,
    }
