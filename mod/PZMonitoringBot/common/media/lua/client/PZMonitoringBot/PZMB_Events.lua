require "PZMonitoringBot/PZMB_Json"
require "PZMonitoringBot/PZMB_Scanner"
require "PZMonitoringBot/PZMB_Config"
require "PZMonitoringBot/PZMB_Vehicles"
require "PZMonitoringBot/PZMB_Export"
require "PZMonitoringBot/PZMB_UI"

PZMB = PZMB or {}
PZMB.Runtime = PZMB.Runtime or {}

local Runtime = PZMB.Runtime
Runtime.analysisWait = nil
Runtime.analysisTickRegistered = false

local function nowMillis()
    if getTimestampMs then return getTimestampMs() end
    return math.floor(os.time() * 1000)
end

local onAnalysisTick

local function stopAnalysisWait()
    Runtime.analysisWait = nil
    if Runtime.analysisTickRegistered then
        Events.OnTick.Remove(onAnalysisTick)
        Runtime.analysisTickRegistered = false
    end
end

onAnalysisTick = function()
    local wait = Runtime.analysisWait
    if not wait then
        stopAnalysisWait()
        return
    end
    local now = nowMillis()
    if now - (wait.lastCheckEpochMs or 0) < 1000 then return end
    wait.lastCheckEpochMs = now
    local response = PZMB.Export.readCalculationResponse()
    if response and response.requestId == wait.requestId then
        local callback = wait.callback
        stopAnalysisWait()
        if callback then callback(response.ok, response.message) end
        return
    end
    if now - wait.startedAtEpochMs >= 180000 then
        local callback = wait.callback
        stopAnalysisWait()
        if callback then callback(false, "timeout") end
    end
end

function Runtime.waitForAnalysis(requestId, callback)
    Runtime.analysisWait = {
        requestId = requestId,
        callback = callback,
        startedAtEpochMs = nowMillis(),
        lastCheckEpochMs = 0,
    }
    if not Runtime.analysisTickRegistered then
        Events.OnTick.Add(onAnalysisTick)
        Runtime.analysisTickRegistered = true
    end
end

local function onGameStart()
    PZMB.Config.load()
    PZMB.Config.applyCurrentSave()
    PZMB.Vehicles.load()
end

-- No permanent polling, scanning, or serialization. OnTick exists only while
-- an explicit calculation request is pending, reads one tiny line per second,
-- and removes itself immediately after completion or timeout.
Events.OnGameStart.Add(onGameStart)

return Runtime