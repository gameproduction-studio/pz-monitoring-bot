require "PZMonitoringBot/PZMB_Json"
require "PZMonitoringBot/PZMB_Scanner"
require "PZMonitoringBot/PZMB_Config"
require "PZMonitoringBot/PZMB_Vehicles"
require "PZMonitoringBot/PZMB_Export"
require "PZMonitoringBot/PZMB_UI"
require "TimedActions/ISInventoryTransferAction"
require "TimedActions/ISBaseTimedAction"

PZMB = PZMB or {}
PZMB.Runtime = PZMB.Runtime or {
    dirty = false,
    pendingReason = nil,
    dirtySinceEpochMs = 0,
    lastExportEpochMs = 0,
    lastExportWorldAgeHours = -1,
    debounceMs = 2500,
    minimumIntervalMs = 5000,
}

local Runtime = PZMB.Runtime

local function nowMillis()
    if getTimestampMs then return getTimestampMs() end
    return os.time() * 1000
end

function Runtime.markDirty(reason)
    Runtime.dirty = true
    Runtime.pendingReason = reason or Runtime.pendingReason or "tracked_state_changed"
    Runtime.dirtySinceEpochMs = nowMillis()
end

local function refreshTrackedWorld()
    if PZMB.Scanner.isPlayerNearAnyBase(15) then
        local scanned = PZMB.Scanner.scanBaseLoadedSquares()
        if scanned == 0 then PZMB.Scanner.refreshKnownBaseContainers() end
    end
    PZMB.Scanner.refreshOwnedVehicles()
    PZMB.Vehicles.save()
end

local function export(reason, refreshWorld)
    if refreshWorld then refreshTrackedWorld() end
    local ok = PZMB.Export.write(reason)
    if ok then
        Runtime.dirty = false
        Runtime.pendingReason = nil
        Runtime.lastExportEpochMs = nowMillis()
        Runtime.lastExportWorldAgeHours = getGameTime():getWorldAgeHours()
    end
end

local function onGameStart()
    PZMB.Config.load()
    PZMB.Config.applyCurrentSave()
    PZMB.Vehicles.load()
    Runtime.markDirty("game_started")
end

local function onContainerUpdate()
    Runtime.markDirty("container_changed")
end

local function onTick()
    if not Runtime.dirty then return end
    local now = nowMillis()
    if now - Runtime.dirtySinceEpochMs < Runtime.debounceMs then return end
    if now - Runtime.lastExportEpochMs < Runtime.minimumIntervalMs then return end
    export(Runtime.pendingReason or "tracked_state_changed", true)
end

local function onPostSave()
    export("post_save", true)
end

-- Build 42 does not emit OnContainerUpdate for ordinary item transfers.
-- This wrapper marks the state dirty only when a transfer action completes.
-- The OnTick handler below checks timestamps only and never scans while clean.
if ISBaseTimedAction and not ISBaseTimedAction.pzmbOriginalPerform then
    ISBaseTimedAction.pzmbOriginalPerform = ISBaseTimedAction.perform
    function ISBaseTimedAction:perform()
        local result = ISBaseTimedAction.pzmbOriginalPerform(self)
        Runtime.markDirty("timed_action_completed")
        return result
    end
end
if ISInventoryTransferAction and not ISInventoryTransferAction.pzmbOriginalPerform then
    ISInventoryTransferAction.pzmbOriginalPerform = ISInventoryTransferAction.perform
    function ISInventoryTransferAction:perform()
        local result = ISInventoryTransferAction.pzmbOriginalPerform(self)
        Runtime.markDirty("inventory_transfer")
        return result
    end
end

Events.OnGameStart.Add(onGameStart)
Events.OnPostSave.Add(onPostSave)
Events.OnContainerUpdate.Add(onContainerUpdate)
Events.OnTick.Add(onTick)

return Runtime