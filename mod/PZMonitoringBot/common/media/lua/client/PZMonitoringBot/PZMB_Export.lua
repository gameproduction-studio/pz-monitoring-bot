require "PZMonitoringBot/PZMB_Json"
require "PZMonitoringBot/PZMB_Scanner"

PZMB = PZMB or {}
PZMB.Export = PZMB.Export or {}

local Export = PZMB.Export
Export.sequence = Export.sequence or 0
Export.lastError = nil
Export.lastReason = nil
Export.currentStateFile = "pzmb_current_state.json"
Export.statusFile = "pzmb_status.json"
-- The game sandbox rejects the .jsonl extension in Build 42.20.3.
-- The relay publishes this JSON-lines stream as live/changes.jsonl.
Export.eventsFile = "pzmb_changes.txt"
Export.eventsEnabled = true
Export.eventsErrorLogged = false

local function nowMillis()
    if getTimestampMs then return getTimestampMs() end
    return math.floor(os.time() * 1000)
end

local function counts(state)
    local itemCount = 0
    local function walk(items)
        for _, item in ipairs(items or {}) do
            itemCount = itemCount + 1
            if item.container then walk(item.container.items) end
        end
    end
    walk(state.character.inventory.items)
    for _, container in ipairs(state.world.containers or {}) do
        walk(container.items)
    end
    for _, vehicle in ipairs(state.world.vehicles or {}) do
        for _, container in ipairs(vehicle.containers or {}) do walk(container.items) end
    end
    return itemCount, #(state.world.containers or {}), #(state.world.vehicles or {})
end

function Export.status(ok, reason, state, err)
    local itemCount, containerCount, vehicleCount = 0, 0, 0
    if state then itemCount, containerCount, vehicleCount = counts(state) end
    return {
        schema = "pz-monitoring-bot/mod-status/v1",
        schemaVersion = "0.4.0",
        ok = ok,
        parsingSuccessful = ok,
        sequence = Export.sequence,
        writtenAtEpochMs = nowMillis(),
        reason = reason,
        error = err,
        save = state and state.save or nil,
        game = state and state.game or nil,
        counts = {
            itemInstances = itemCount,
            containers = containerCount,
            vehicles = vehicleCount,
        },
        readOnlyGameState = true,
    }
end

function Export.write(reason)
    reason = reason or "manual"
    local ok, result = pcall(function()
        local state = PZMB.Scanner.currentState()
        Export.sequence = Export.sequence + 1
        state.export = {
            sequence = Export.sequence,
            reason = reason,
            writtenAtEpochMs = nowMillis(),
        }
        PZMB.Json.writeFile(Export.currentStateFile, state)
        PZMB.Json.writeFile(Export.statusFile, Export.status(true, reason, state, nil))
        Export.lastError = nil
        Export.lastReason = reason
        return state
    end)
    if not ok then
        Export.lastError = tostring(result)
        pcall(PZMB.Json.writeFile, Export.statusFile, Export.status(false, reason, nil, Export.lastError))
        print("[pz monitoring bot] export failed: " .. Export.lastError)
        return false, Export.lastError
    end
    return true, result
end

function Export.appendEvent(event)
    if not event or not Export.eventsEnabled then return false end
    event.exportedAtEpochMs = nowMillis()
    local ok, err = pcall(PZMB.Json.appendLine, Export.eventsFile, event)
    if not ok then
        Export.eventsEnabled = false
        if not Export.eventsErrorLogged then
            print("[pz monitoring bot] event journal disabled for this session: " .. tostring(err))
            Export.eventsErrorLogged = true
        end
        return false
    end
    return true
end

return Export
