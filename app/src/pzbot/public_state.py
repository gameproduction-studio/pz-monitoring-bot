from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any

from .diff import flatten, location_signature

PUBLIC_FIELDS = (
    "itemId", "fullType", "name_ru", "customName", "quantity", "condition",
    "conditionMax", "itemType", "currentAmmoCount", "freshness", "frozen",
    "freezingTime", "cooked", "burnt", "remainingFraction", "currentUses",
    "recordedMediaId", "recordedMediaIndex", "parentItemIds",
)


def build_public_state(snapshot: dict[str, Any], events: list[dict[str, Any]], snapshot_count: int) -> dict[str, Any]:
    instances = flatten(snapshot)
    items = []
    for item in instances.values():
        public = {field: item.get(field) for field in PUBLIC_FIELDS if item.get(field) is not None}
        public["location"] = location_signature(item)
        items.append(public)
    items.sort(key=lambda value: (value.get("location", ""), value.get("fullType", ""), value.get("itemId", "")))
    counts = Counter(item.get("fullType") for item in items)
    player = snapshot.get("player") or {}
    return {
        "schema": "project-the-bot-monitoring/public-state/v1",
        "updatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "game": {"worldVersion": snapshot.get("worldVersion"), "build": "42.20.2"},
        "player": {key: player.get(key) for key in ("firstName", "lastName", "displayName") if player.get(key)},
        "summary": {
            "physicalItems": len(items),
            "distinctFullTypes": len(counts),
            "snapshotCount": snapshot_count,
            "eventCount": len(events),
        },
        "countsByFullType": dict(sorted(counts.items())),
        "items": items,
        "recentChanges": events[-200:],
    }

