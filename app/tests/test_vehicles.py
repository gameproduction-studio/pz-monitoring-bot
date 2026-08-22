from __future__ import annotations

import copy
from pathlib import Path

from pzbot.assistant_views import build_assistant_views
from pzbot.mod_telemetry import normalize_mod_snapshot
from pzbot.state_diff import compare_states, flatten_state

from test_mod_telemetry import runtime_item, runtime_state


def vehicle_container(items):
    return {
        "containerId": "vehicle:77:TruckBed",
        "kind": "vehicle",
        "containerType": "TruckBed",
        "displayName": "Багажник",
        "position": {"x": 20, "y": 30, "z": 0},
        "vehicleId": "77",
        "vehicleName": "Фургон",
        "ownership": {
            "owned": True,
            "reason": "registered_vehicle",
            "vehicleId": "77",
        },
        "observation": "registered_vehicle_refresh",
        "lastSeenWorldAgeHours": 100,
        "items": items,
    }


def vehicle(items=None, *, fuel=0.24, condition=65, part_condition=35):
    return {
        "vehicleId": "77",
        "keyId": 1234,
        "name": "Фургон",
        "displayName": "Franklin Valuline",
        "scriptFullType": "Base.Van",
        "position": {"x": 20, "y": 30, "z": 0},
        "ownership": {
            "owned": True,
            "reason": "registered_with_matching_key",
            "confidence": "exact",
        },
        "observation": "registered_vehicle_refresh",
        "lastSeenWorldAgeHours": 100,
        "fuel": {"amount": fuel * 40, "capacity": 40, "fraction": fuel},
        "batteryCharge": 0.8,
        "overallCondition": condition,
        "engine": {"quality": 80, "working": True},
        "parts": [
            {
                "partId": "Muffler",
                "nameLocalized": "Глушитель",
                "condition": part_condition,
                "installed": True,
            }
        ],
        "containers": [vehicle_container(items or [])],
    }


def with_vehicle(state, entry, *, registered=True):
    state = copy.deepcopy(state)
    state["world"]["vehicles"] = [entry] if entry else []
    state["ownedVehicles"] = (
        [{"vehicleId": "77", "keyId": 1234, "name": "Фургон"}]
        if registered
        else []
    )
    return state


def test_registered_vehicle_cargo_is_owned_and_uses_instance_ids():
    wrench = runtime_item(900, "Base.Wrench", "Гаечный ключ")
    snapshot = normalize_mod_snapshot(with_vehicle(runtime_state(), vehicle([wrench])))
    flat = flatten_state(snapshot)
    assert flat["900"]["source"]["scope"] == "vehicle"
    assert flat["900"]["source"]["owned"] is True
    assert flat["900"]["source"]["vehicleName"] == "Фургон"


def test_vehicle_unloaded_is_carried_forward_as_stale_without_false_expense():
    wrench = runtime_item(901, "Base.Wrench", "Гаечный ключ")
    first = normalize_mod_snapshot(with_vehicle(runtime_state(), vehicle([wrench])))
    second = normalize_mod_snapshot(
        with_vehicle(runtime_state(sequence=2), None), previous=first
    )
    assert second["world"]["vehicles"][0]["observation"]["stale"] is True
    assert compare_states(first, second) == []
    assert "901" in flatten_state(second)
    vehicle_view = build_assistant_views(second)["vehicles"]["owned"][0]
    assert vehicle_view["lastSeenAtWorldAgeHours"] == 100
    assert vehicle_view["hoursSinceLastSeen"] == 0.0


def test_vehicle_removal_does_not_carry_old_snapshot():
    first = normalize_mod_snapshot(with_vehicle(runtime_state(), vehicle()))
    second = normalize_mod_snapshot(
        with_vehicle(runtime_state(sequence=2), None, registered=False), previous=first
    )
    assert second["world"]["vehicles"] == []
    assert [event["kind"] for event in compare_states(first, second)] == [
        "vehicle_removed"
    ]


def test_vehicle_fuel_part_and_move_events_and_chat_alerts():
    first = normalize_mod_snapshot(with_vehicle(runtime_state(), vehicle(fuel=0.5, part_condition=70)))
    changed = vehicle(fuel=0.24, condition=55, part_condition=35)
    changed["position"] = {"x": 25, "y": 31, "z": 0}
    second = normalize_mod_snapshot(
        with_vehicle(runtime_state(sequence=2), changed), previous=first
    )
    kinds = {event["kind"] for event in compare_states(first, second)}
    assert {
        "vehicle_fuel_change",
        "vehicle_condition_change",
        "vehicle_part_condition_change",
        "vehicle_moved",
    } <= kinds
    vehicle_view = build_assistant_views(second)["vehicles"]["owned"][0]
    assert vehicle_view["fuel"]["percent"] == 24.0
    assert {alert["kind"] for alert in vehicle_view["alerts"]} == {
        "vehicle_low_fuel",
        "vehicle_weak_parts",
    }


def test_reused_runtime_vehicle_id_cannot_impersonate_registered_vehicle():
    raw = runtime_state()
    impostor = vehicle()
    impostor["keyId"] = 9999
    impostor["scriptFullType"] = "Base.PickUpTruck"
    raw["world"]["vehicles"] = [impostor]
    raw["ownedVehicles"] = [
        {
            "vehicleId": "77",
            "keyId": 1234,
            "scriptFullType": "Base.Van",
            "name": "Фургон",
        }
    ]
    snapshot = normalize_mod_snapshot(raw)
    assert snapshot["world"]["vehicles"] == []


def test_lua_vehicle_registry_is_event_driven_and_key_gated():
    root = Path(__file__).parents[2]
    lua_root = root / "mod/PZMonitoringBot/common/media/lua/client/PZMonitoringBot"
    vehicles = (lua_root / "PZMB_Vehicles.lua").read_text(encoding="utf-8")
    scanner = (lua_root / "PZMB_Scanner.lua").read_text(encoding="utf-8")
    ui = (lua_root / "PZMB_UI.lua").read_text(encoding="utf-8")
    events = (lua_root / "PZMB_Events.lua").read_text(encoding="utf-8")

    assert 'Vehicles.fileName = "pzmb_vehicles.txt"' in vehicles
    assert 'safeCall(vehicle, "getSqlId", -1)' in vehicles
    assert 'function Vehicles.findBySqlId(sqlId)' in vehicles
    assert 'function Vehicles.findByKeyId(keyId)' in vehicles
    assert 'function Vehicles.bindIdentity(vehicle, record)' in vehicles
    assert 'return Vehicles.findById(vehicleId(vehicle))' not in vehicles
    assert 'local stableId = sqlId >= 0' in scanner
    assert 'trackingId = trackingId' in scanner
    assert "local function containerHasKeyId(container, keyId, seen)" in vehicles
    assert 'safeCall(container, "haveThisKeyId", false, keyId)' in vehicles
    assert 'safeCall(item, "getKeyId", -1)' in vehicles
    assert 'instanceof(item, "InventoryContainer")' in vehicles
    assert "containerHasKeyId(nested, keyId, seen)" in vehicles
    assert "return containerHasKeyId(inventory, keyId, {})" in vehicles
    assert "function Scanner.vehicleSnapshot(vehicle, observation)" in scanner
    assert "function Scanner.refreshOwnedVehicles()" in scanner
    assert "IsoObjectPicker.Instance.PickVehicle" in ui
    assert 'tr("UI_PZMB_MyVehicles"' in ui
    assert "Events.OnPlayerUpdate" not in events
    assert "Events.EveryOneMinute" not in events
