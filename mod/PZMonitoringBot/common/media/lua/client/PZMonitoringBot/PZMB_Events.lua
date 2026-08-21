require "PZMonitoringBot/PZMB_Json"
require "PZMonitoringBot/PZMB_Scanner"
require "PZMonitoringBot/PZMB_Config"
require "PZMonitoringBot/PZMB_Export"
require "PZMonitoringBot/PZMB_UI"

PZMB = PZMB or {}
PZMB.Runtime = PZMB.Runtime or {
    dirty = false,
    lastExportWorldAgeHours = -1,
}

local Runtime = PZMB.Runtime

local function export(reason, refreshWorld)
    if refreshWorld then
        local scanned = PZMB.Scanner.scanBaseLoadedSquares()
        if scanned == 0 then PZMB.Scanner.refreshKnownContainers() end
    end
    local ok = PZMB.Export.write(reason)
    if ok then
        Runtime.dirty = false
        Runtime.lastExportWorldAgeHours = getGameTime():getWorldAgeHours()
    end
end

local function onGameStart()
    PZMB.Config.load()
    PZMB.Config.applyCurrentSave()
    Runtime.dirty = true
end


local function onPostSave()
    PZMB.Scanner.observeSelectedContainer(false)
    export("post_save", true)
end

Events.OnGameStart.Add(onGameStart)
Events.OnPostSave.Add(onPostSave)

return Runtime
