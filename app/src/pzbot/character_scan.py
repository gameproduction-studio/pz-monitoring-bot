"""Reusable character scan built on the verified Build 42 parser."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .pz_save_scanner import (
    WORLD_VERSION,
    decorate_items,
    expanded_top_level,
    find_equipment,
    find_player_inventory,
    load_json,
    parse_item_definitions,
    parse_recorded_media,
    parse_world_dictionary,
    read_player_snapshot,
)


def scan_character(save_dir: Path, game_dir: Path) -> dict[str, Any]:
    blob, world_version, player = read_player_snapshot(save_dir / "players.db")
    if world_version != WORLD_VERSION:
        raise RuntimeError(
            f"Unsupported worldVersion {world_version}; expected {WORLD_VERSION}"
        )

    by_id, _ = parse_world_dictionary(save_dir / "WorldDictionaryReadable.lua")
    definitions = parse_item_definitions(game_dir)
    inventory_offset, inventory = find_player_inventory(blob, by_id, definitions)
    top_expanded = expanded_top_level(inventory["items"])
    equipment = find_equipment(blob, inventory["end"], top_expanded)

    translate_dir = game_dir / "media" / "lua" / "shared" / "Translate" / "RU"
    ru_names = load_json(translate_dir / "ItemName.json")
    media_ru = load_json(translate_dir / "Recorded_Media.json")
    recorded_media = save_dir / "recorded_media.bin"
    media_ids = parse_recorded_media(recorded_media) if recorded_media.is_file() else []
    decorate_items(inventory["items"], ru_names, media_ids, media_ru)

    return {
        "schema": "pz-monitoring-bot/character/v1",
        "readOnly": True,
        "worldVersion": world_version,
        "player": player,
        "inventoryOffset": inventory_offset,
        "inventory": inventory,
        "equipment": equipment,
    }

