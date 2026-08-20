#!/usr/bin/env python3
"""Read-only Project Zomboid Build 42 player inventory scanner.

This parser is intentionally limited to the Build 42.20.2 save layout verified
against the locally installed projectzomboid.jar. It never opens a save for
writing.
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import re
import sqlite3
import struct
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote


LOG = logging.getLogger("pz_inventory_scan")
WORLD_VERSION = 249


class ParseError(RuntimeError):
    pass


@dataclass
class Reader:
    data: bytes
    pos: int = 0

    def require(self, size: int) -> None:
        if size < 0 or self.pos + size > len(self.data):
            raise ParseError(f"buffer overrun at {self.pos}, need {size}")

    def u8(self) -> int:
        self.require(1)
        value = self.data[self.pos]
        self.pos += 1
        return value

    def i8(self) -> int:
        value = self.u8()
        return value - 256 if value >= 128 else value

    def u16(self) -> int:
        self.require(2)
        value = struct.unpack_from(">H", self.data, self.pos)[0]
        self.pos += 2
        return value

    def i16(self) -> int:
        self.require(2)
        value = struct.unpack_from(">h", self.data, self.pos)[0]
        self.pos += 2
        return value

    def i32(self) -> int:
        self.require(4)
        value = struct.unpack_from(">i", self.data, self.pos)[0]
        self.pos += 4
        return value

    def f32(self) -> float:
        self.require(4)
        value = struct.unpack_from(">f", self.data, self.pos)[0]
        self.pos += 4
        return value

    def f64(self) -> float:
        self.require(8)
        value = struct.unpack_from(">d", self.data, self.pos)[0]
        self.pos += 8
        return value

    def raw(self, size: int) -> bytes:
        self.require(size)
        value = self.data[self.pos : self.pos + size]
        self.pos += size
        return value

    def string(self) -> str:
        size = self.u16()
        return self.raw(size).decode("utf-8")


def find_game_dir(explicit: str | None) -> pathlib.Path:
    candidates = []
    if explicit:
        candidates.append(pathlib.Path(explicit))
    candidates.extend(
        [
            pathlib.Path(r"D:\SteamLibrary\steamapps\common\ProjectZomboid"),
            pathlib.Path(r"C:\Program Files (x86)\Steam\steamapps\common\ProjectZomboid"),
            pathlib.Path(r"C:\Program Files\Steam\steamapps\common\ProjectZomboid"),
        ]
    )
    for candidate in candidates:
        if (candidate / "projectzomboid.jar").is_file() and (candidate / "media").is_dir():
            return candidate
    raise FileNotFoundError("Project Zomboid installation directory not found")


def find_save_dir(explicit: str | None) -> pathlib.Path:
    if explicit:
        path = pathlib.Path(explicit)
        if (path / "players.db").is_file():
            return path
        raise FileNotFoundError(f"players.db not found in {path}")

    root = pathlib.Path.home() / "Zomboid"
    latest = root / "latestSave.ini"
    if latest.is_file():
        lines = [line.strip() for line in latest.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        if len(lines) >= 2:
            candidate = root / "Saves" / lines[1] / lines[0]
            if (candidate / "players.db").is_file():
                return candidate

    databases = list((root / "Saves").glob("*/*/players.db"))
    if not databases:
        raise FileNotFoundError("No Project Zomboid players.db found")
    return max(databases, key=lambda path: path.stat().st_mtime).parent


def read_player_snapshot(db_path: pathlib.Path) -> tuple[bytes, int, dict[str, Any]]:
    uri = "file:" + quote(db_path.resolve().as_posix()) + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as connection:
        connection.execute("PRAGMA query_only=ON")
        row = connection.execute(
            "SELECT id, name, x, y, z, worldversion, data, isDead "
            "FROM localPlayers WHERE isDead = 0 ORDER BY id LIMIT 1"
        ).fetchone()
    if row is None:
        raise ParseError("No living local player found")
    player_id, db_name, x, y, z, world_version, blob, is_dead = row
    return bytes(blob), int(world_version), {
        "playerDbId": player_id,
        "databaseNameRaw": db_name,
        "position": {"x": x, "y": y, "z": z},
        "isDead": bool(is_dead),
    }


def parse_world_dictionary(path: pathlib.Path) -> tuple[dict[int, str], dict[str, int]]:
    text = path.read_text(encoding="utf-8")
    pairs = [
        (int(registry_id), full_type)
        for registry_id, full_type in re.findall(
            r'registryID = (\d+),\s+fulltype = "([^"]+)"', text
        )
    ]
    if not pairs:
        raise ParseError(f"No item registry entries in {path}")
    by_id = dict(pairs)
    return by_id, {full_type: registry_id for registry_id, full_type in pairs}


def parse_item_definitions(game_dir: pathlib.Path) -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    item_dir = game_dir / "media" / "scripts" / "generated" / "items"
    block_re = re.compile(r"\bitem\s+([A-Za-z0-9_]+)\s*\{(.*?)\n\s*\}", re.S)
    field_re = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*?),?\s*$", re.M)
    for path in item_dir.glob("*.txt"):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for item_name, body in block_re.findall(text):
            fields: dict[str, Any] = {}
            for key, raw_value in field_re.findall(body):
                value = raw_value.strip().rstrip(",")
                if re.fullmatch(r"[-+]?\d+", value):
                    fields[key] = int(value)
                elif re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)", value):
                    fields[key] = float(value)
                elif value.lower() in ("true", "false"):
                    fields[key] = value.lower() == "true"
                else:
                    fields[key] = value
            definitions[f"Base.{item_name}"] = fields
    return definitions


def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def parse_recorded_media(path: pathlib.Path) -> list[str]:
    reader = Reader(path.read_bytes())
    version = reader.i32()
    count = reader.i32()
    if version not in (1, 2) or not 0 <= count <= 100000:
        raise ParseError("Unexpected recorded_media.bin header")
    return [reader.string() for _ in range(count)]


def parse_lua_value(reader: Reader, value_type: int) -> Any:
    if value_type == 0:
        return reader.string()
    if value_type == 1:
        return reader.f64()
    if value_type == 2:
        return parse_lua_table(reader)
    if value_type == 3:
        return bool(reader.u8())
    raise ParseError(f"Unknown Lua table value type {value_type} at {reader.pos}")


def parse_lua_table(reader: Reader) -> dict[Any, Any]:
    count = reader.i32()
    if not 0 <= count <= 10000:
        raise ParseError(f"Invalid Lua table size {count}")
    result: dict[Any, Any] = {}
    for _ in range(count):
        key = parse_lua_value(reader, reader.u8())
        value = parse_lua_value(reader, reader.u8())
        result[key] = value
    return result


def skip_item_visual(reader: Reader) -> dict[str, Any]:
    flags = reader.u8()
    result = {
        "fullType": reader.string(),
        "alternateModelName": reader.string(),
        "clothingItemName": reader.string(),
    }
    if flags & 1:
        result["tintRgb"] = list(reader.raw(3))
    if flags & 2:
        result["baseTexture"] = reader.i8()
    if flags & 4:
        result["textureChoice"] = reader.i8()
    if flags & 8:
        result["hue"] = reader.f32()
    if flags & 0x10:
        result["decal"] = reader.string()
    for _ in range(6):
        reader.raw(reader.u8())
    return result


def parse_base_item(reader: Reader, record_end: int) -> dict[str, Any]:
    item_id = reader.i32()
    header = reader.u8()
    result: dict[str, Any] = {
        "itemId": item_id,
        "currentUses": 1,
        "conditionSaved": None,
        "lua": {},
        "recordedMediaIndex": None,
        "currentAmmoCount": 0,
    }
    if header & 1:
        result["currentUses"] = reader.i32()
    if header & 4:
        result["conditionSaved"] = reader.u8()
    if header & 8:
        result["visual"] = skip_item_visual(reader)
    if header & 16:
        result["customColorRgba"] = list(reader.raw(4))
    if header & 32:
        result["itemCapacity"] = reader.f32()
    if header & 64:
        bits = reader.i32() & 0xFFFFFFFF
        result["baseFlags"] = f"0x{bits:08x}"
        if bits & 1:
            result["lua"] = parse_lua_table(reader)
        result["activated"] = bool(bits & 2)
        if bits & 4:
            result["haveBeenRepaired"] = reader.i16()
        if bits & 8:
            result["savedName"] = reader.string()
        if bits & 16:
            reader.raw(reader.i32())
        if bits & 32:
            result["extraItemRegistryIds"] = [reader.i16() for _ in range(reader.i32())]
        result["customNameFlag"] = bool(bits & 64)
        if bits & 128:
            result["actualWeight"] = reader.f32()
        if bits & 256:
            result["keyId"] = reader.i32()
        if bits & 1024:
            result["remoteControlId"] = reader.i32()
            result["remoteRange"] = reader.i32()
        if bits & 2048:
            result["colorRgb"] = list(reader.raw(3))
        if bits & 4096:
            result["worker"] = reader.string()
        if bits & 8192:
            result["wetCooldown"] = reader.f32()
        result["favorite"] = bool(bits & 16384)
        if bits & 32768:
            result["stashMap"] = reader.string()
        result["infected"] = bool(bits & 65536)
        if bits & 131072:
            result["currentAmmoCount"] = reader.i32()
        if bits & 262144:
            result["attachedSlot"] = reader.i32()
        if bits & 524288:
            result["attachedSlotType"] = reader.string()
        if bits & 0x100000:
            result["attachedToModel"] = reader.string()
        if bits & 0x200000:
            result["maxCapacity"] = reader.i32()
        if bits & 0x400000:
            result["recordedMediaIndex"] = reader.i16()
        if bits & 0x1000000:
            result["worldScale"] = reader.f32()
        result["initialised"] = bool(bits & 0x2000000)
        unsupported = bits & (0x4000000 | 0x8000000 | 0x10000000 | 0x20000000 | 0x40000000)
        if unsupported:
            result["unsupportedBaseFlags"] = f"0x{unsupported:08x}"
            reader.pos = record_end
    return result


def parse_food(reader: Reader) -> dict[str, Any]:
    result: dict[str, Any] = {
        "age": reader.f32(),
        "lastAged": reader.f32(),
        "cooked": False,
        "burnt": False,
        "frozen": False,
    }
    header = reader.u8()
    if header & 1:
        result.update(
            calories=reader.f32(), proteins=reader.f32(), lipids=reader.f32(), carbohydrates=reader.f32()
        )
    if header & 2:
        result["hungerChange"] = reader.f32()
    if header & 4:
        result["baseHunger"] = reader.f32()
    if header & 8:
        result["unhappyChange"] = reader.f32()
    if header & 16:
        result["boredomChange"] = reader.f32()
    if header & 32:
        result["thirstChange"] = reader.f32()
    if header & 64:
        bits = reader.i32() & 0xFFFFFFFF
        if bits & 1:
            result["heat"] = reader.f32()
        if bits & 2:
            result["lastCookMinute"] = reader.i32()
        if bits & 4:
            result["cookingTime"] = reader.f32()
        result["cooked"] = bool(bits & 8)
        result["burnt"] = bool(bits & 16)
        result["isCookable"] = bool(bits & 32)
        result["dangerousUncooked"] = bool(bits & 64)
        if bits & 128:
            result["poisonDetectionLevel"] = reader.i8()
        if bits & 256:
            result["spices"] = [reader.string() for _ in range(reader.u8())]
        if bits & 512:
            result["poisonPower"] = reader.i8()
        if bits & 1024:
            result["chef"] = reader.string()
        if bits & 2048:
            result["offAge"] = reader.i32()
        if bits & 4096:
            result["offAgeMax"] = reader.i32()
        if bits & 8192:
            result["painReduction"] = reader.f32()
        if bits & 16384:
            result["fluReduction"] = reader.i32()
        if bits & 32768:
            result["foodSicknessChange"] = reader.i32()
        result["poison"] = bool(bits & 65536)
        if bits & 131072:
            result["useForPoison"] = reader.i16()
        if bits & 262144:
            result["freezingTime"] = reader.f32()
        result["frozen"] = bool(bits & 524288)
        if bits & 0x100000:
            result["lastFrozenUpdate"] = reader.f32()
        if bits & 0x200000:
            result["rottenTime"] = reader.f32()
        if bits & 0x400000:
            result["compostTime"] = reader.f32()
        result["cookedInMicrowave"] = bool(bits & 0x800000)
        if bits & 0x1000000:
            result["fatigueChange"] = reader.f32()
        if bits & 0x2000000:
            result["enduranceChange"] = reader.f32()
        if bits & 0x4000000:
            result["milkQty"] = reader.i32()
            result["milkType"] = reader.string()
        if bits & 0x8000000:
            raise ParseError("Fertilized egg genome parsing not implemented")
        if bits & 0x10000000:
            result["stressChange"] = reader.f32()
    base_hunger = result.get("baseHunger")
    hunger_change = result.get("hungerChange")
    if isinstance(base_hunger, (int, float)) and base_hunger != 0 and isinstance(hunger_change, (int, float)):
        result["remainingFraction"] = hunger_change / base_hunger
    off_age = result.get("offAge")
    off_age_max = result.get("offAgeMax")
    if isinstance(off_age, int) and isinstance(off_age_max, int):
        age = result["age"]
        result["freshness"] = "fresh" if age < off_age else ("rotten" if age >= off_age_max else "stale")
    return result


def parse_weapon(reader: Reader) -> dict[str, Any]:
    bits = reader.i32() & 0xFFFFFFFF
    result: dict[str, Any] = {
        "containsMagazine": bool(bits & 524288),
        "roundChambered": bool(bits & 0x100000),
        "jammed": bool(bits & 0x200000),
    }
    float_flags = [1, 2]
    for flag, name, kind in [
        (1, "maxRange", "f"), (2, "minRangeRanged", "f"), (4, "clipSize", "i"),
        (8, "minDamage", "f"), (16, "maxDamage", "f"), (32, "recoilDelay", "i"),
        (64, "aimingTime", "i"), (128, "reloadTime", "i"), (256, "hitChance", "i"),
        (512, "minAngle", "f"),
    ]:
        if bits & flag:
            result[name] = reader.f32() if kind == "f" else reader.i32()
    if bits & 1024:
        count = reader.u8()
        result["weaponPartCount"] = count
        raise ParseError("Weapon parts parsing not implemented")
    if bits & 2048:
        result["fireMode"] = reader.string()
    if bits & 4096:
        result["cyclicRateMultiplier"] = reader.f32()
    if bits & 65536:
        result["explosionTimer"] = reader.i32()
    if bits & 131072:
        result["maxAngle"] = reader.f32()
    if bits & 262144:
        result["bloodLevel"] = reader.f32()
    if bits & 0x400000:
        result["weaponSprite"] = reader.string()
    if bits & 0x800000:
        result["minSightRange"] = reader.f32()
    if bits & 0x1000000:
        result["maxSightRange"] = reader.f32()
    return result


def parse_clothing(reader: Reader) -> dict[str, Any]:
    bits = reader.u8()
    result: dict[str, Any] = {}
    if bits & 1:
        result["spriteName"] = reader.string()
    if bits & 2:
        result["dirtiness"] = reader.f32()
    if bits & 4:
        result["bloodLevel"] = reader.f32()
    if bits & 8:
        result["wetness"] = reader.f32()
    if bits & 16:
        result["lastWetnessUpdate"] = reader.f32()
    if bits & 32:
        result["patchCount"] = reader.u8()
        raise ParseError("Clothing patch parsing not implemented")
    return result


def classify_item(full_type: str, definitions: dict[str, dict[str, Any]]) -> str:
    item_type = str(definitions.get(full_type, {}).get("ItemType", "")).lower()
    return item_type.split(":", 1)[-1] if item_type else "unknown"


def parse_item_record(
    blob: bytes,
    start: int,
    by_id: dict[int, str],
    definitions: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    reader = Reader(blob, start)
    identical = reader.i32()
    data_length = reader.i32()
    data_start = reader.pos
    record_end = data_start + data_length
    if not 1 <= identical <= 100000 or record_end > len(blob):
        raise ParseError(f"Invalid item record at {start}")
    registry_id = reader.i16()
    save_type = reader.u8()
    if registry_id not in by_id or save_type != 255:
        raise ParseError(f"Invalid registry/save type at {start}")
    full_type = by_id[registry_id]
    base = parse_base_item(reader, record_end)
    kind = classify_item(full_type, definitions)
    subtype: dict[str, Any] = {}
    nested: dict[str, Any] | None = None
    if reader.pos < record_end and not base.get("unsupportedBaseFlags"):
        try:
            if kind == "food":
                subtype = parse_food(reader)
            elif kind == "weapon":
                subtype = parse_weapon(reader)
            elif kind == "clothing":
                subtype = parse_clothing(reader)
            elif kind == "container":
                container_id = reader.i32()
                weight_reduction = reader.i32()
                nested = parse_container(reader, by_id, definitions)
                subtype = {"containerId": container_id, "weightReduction": weight_reduction}
        except ParseError as exc:
            subtype["parseWarning"] = str(exc)
    duplicate_ids = [reader_value for reader_value in struct.unpack_from(
        ">" + "i" * (identical - 1), blob, record_end
    )] if identical > 1 else []
    next_pos = record_end + (identical - 1) * 4
    definition = definitions.get(full_type, {})
    condition_max = int(definition.get("ConditionMax", 10))
    condition = base["conditionSaved"] if base["conditionSaved"] is not None else condition_max
    item = {
        "fullType": full_type,
        "registryId": registry_id,
        "quantity": identical,
        "itemIds": [base["itemId"], *duplicate_ids],
        "itemType": kind,
        "condition": condition,
        "conditionMax": condition_max,
        "conditionSource": "saved" if base["conditionSaved"] is not None else "script-default",
        "currentUses": base["currentUses"],
        "customName": base.get("lua", {}).get("customName") or base.get("savedName"),
        "metadata": base.get("lua", {}),
        "recordedMediaIndex": base.get("recordedMediaIndex"),
        "currentAmmoCount": base.get("currentAmmoCount", 0),
        **subtype,
    }
    if nested is not None:
        item["contents"] = nested["items"]
        item["containerType"] = nested["type"]
        item["containerCapacity"] = nested["capacity"]
    return item, next_pos


def parse_container(
    reader: Reader,
    by_id: dict[int, str],
    definitions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    container_type = reader.string()
    explored = bool(reader.u8())
    group_count = reader.i16()
    if not 0 <= group_count <= 10000:
        raise ParseError(f"Invalid container group count {group_count}")
    items = []
    for _ in range(group_count):
        item, reader.pos = parse_item_record(reader.data, reader.pos, by_id, definitions)
        items.append(item)
    has_been_looted = bool(reader.u8())
    capacity = reader.i32()
    return {
        "type": container_type,
        "explored": explored,
        "groupCount": group_count,
        "hasBeenLooted": has_been_looted,
        "capacity": capacity,
        "items": items,
        "end": reader.pos,
    }


def find_player_inventory(
    blob: bytes,
    by_id: dict[int, str],
    definitions: dict[str, dict[str, Any]],
) -> tuple[int, dict[str, Any]]:
    candidates = []
    for offset in range(0, len(blob) - 8):
        reader = Reader(blob, offset)
        try:
            length = struct.unpack_from(">H", blob, offset)[0]
            if not 0 <= length <= 64:
                continue
            candidate = parse_container(reader, by_id, definitions)
            if candidate["groupCount"] > 0 and candidate["end"] <= len(blob):
                candidates.append((offset, candidate))
        except (ParseError, UnicodeDecodeError, struct.error):
            continue
    if not candidates:
        raise ParseError("No valid player inventory container found")
    candidates.sort(key=lambda value: (value[1]["groupCount"], value[1]["end"] - value[0]), reverse=True)
    return candidates[0]


def expanded_top_level(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        result.extend([item] * item["quantity"])
    return result


def find_equipment(blob: bytes, start: int, expanded_items: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = []
    for offset in range(start, len(blob) - 5):
        reader = Reader(blob, offset)
        try:
            count = reader.u8()
            if not 1 <= count <= 64:
                continue
            worn = []
            for _ in range(count):
                location = reader.string()
                index = reader.i16()
                if not location.startswith("base:") or not 0 <= index < len(expanded_items):
                    raise ParseError("invalid worn item entry")
                worn.append((location, index))
            primary = reader.i16()
            secondary = reader.i16()
            if primary < -1 or primary >= len(expanded_items) or secondary < -1 or secondary >= len(expanded_items):
                continue
            candidates.append((offset, worn, primary, secondary))
        except (ParseError, UnicodeDecodeError):
            continue
    if not candidates:
        return {"worn": [], "primaryHandIndex": None, "secondaryHandIndex": None}
    offset, worn, primary, secondary = max(candidates, key=lambda value: len(value[1]))
    for location, index in worn:
        expanded_items[index].setdefault("equippedLocations", []).append(location)
    if primary >= 0:
        expanded_items[primary]["primaryHand"] = True
    if secondary >= 0:
        expanded_items[secondary]["secondaryHand"] = True
    return {
        "offset": offset,
        "worn": [{"location": location, "inventoryIndex": index} for location, index in worn],
        "primaryHandIndex": primary,
        "secondaryHandIndex": secondary,
    }


def decorate_items(
    items: list[dict[str, Any]],
    ru_names: dict[str, str],
    media_ids: list[str],
    media_ru: dict[str, str],
    container_path: list[str] | None = None,
) -> None:
    container_path = container_path or ["mainInventory"]
    for item in items:
        item["name_ru"] = ru_names.get(item["fullType"])
        item["location"] = "/".join(container_path)
        media_index = item.get("recordedMediaIndex")
        if isinstance(media_index, int) and 0 <= media_index < len(media_ids):
            media_id = media_ids[media_index]
            item["recordedMediaId"] = media_id
            item["recordedMediaNameRu"] = media_ru.get("RM_" + media_id)
        if item["fullType"] == "Base.ShotgunShellsBox":
            item["nominalContentsFromInstalledRecipe"] = {
                "fullType": "Base.ShotgunShells",
                "quantity": 25,
                "note": "Derived from OpenBoxOfShotgunShells; not stored as nested items in the save",
            }
        if "contents" in item:
            label = item.get("customName") or item.get("name_ru") or item["fullType"]
            decorate_items(item["contents"], ru_names, media_ids, media_ru, [*container_path, str(label)])


def main() -> int:
    parser = argparse.ArgumentParser(description="Read Project Zomboid Build 42 inventory as JSON")
    parser.add_argument("--save", help="Explicit save directory")
    parser.add_argument("--game", help="Explicit ProjectZomboid installation directory")
    parser.add_argument("--output", help="Write JSON to this file instead of stdout")
    parser.add_argument("--compact", action="store_true", help="Compact JSON")
    parser.add_argument("--log", help="Log file path")
    args = parser.parse_args()

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if args.log:
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)

    try:
        save_dir = find_save_dir(args.save)
        game_dir = find_game_dir(args.game)
        LOG.info("save=%s", save_dir)
        LOG.info("game=%s", game_dir)
        blob, world_version, player = read_player_snapshot(save_dir / "players.db")
        if world_version != WORLD_VERSION:
            LOG.warning("Parser verified for worldVersion %s; save reports %s", WORLD_VERSION, world_version)
        by_id, _ = parse_world_dictionary(save_dir / "WorldDictionaryReadable.lua")
        definitions = parse_item_definitions(game_dir)
        inventory_offset, inventory = find_player_inventory(blob, by_id, definitions)
        top_expanded = expanded_top_level(inventory["items"])
        equipment = find_equipment(blob, inventory["end"], top_expanded)

        translate_dir = game_dir / "media" / "lua" / "shared" / "Translate" / "RU"
        ru_names = load_json(translate_dir / "ItemName.json")
        media_ru = load_json(translate_dir / "Recorded_Media.json")
        media_ids = parse_recorded_media(save_dir / "recorded_media.bin")
        decorate_items(inventory["items"], ru_names, media_ids, media_ru)

        result = {
            "schema": "pz-inventory-scan/1",
            "readOnly": True,
            "savePath": str(save_dir.resolve()),
            "gamePath": str(game_dir.resolve()),
            "worldVersion": world_version,
            "player": player,
            "inventoryOffset": inventory_offset,
            "inventory": inventory,
            "equipment": equipment,
        }
        text = json.dumps(
            result,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            separators=(",", ":") if args.compact else None,
        ) + "\n"
        if args.output:
            pathlib.Path(args.output).write_text(text, encoding="utf-8")
            LOG.info("wrote=%s", args.output)
        else:
            sys.stdout.write(text)
        return 0
    except Exception:
        LOG.exception("Inventory scan failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

