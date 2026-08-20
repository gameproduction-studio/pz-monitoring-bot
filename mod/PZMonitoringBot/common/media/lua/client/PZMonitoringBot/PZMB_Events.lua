require "PZMonitoringBot/PZMB_Json"
require "PZMonitoringBot/PZMB_Scanner"
require "PZMonitoringBot/PZMB_Config"
require "PZMonitoringBot/PZMB_Export"
require "PZMonitoringBot/PZMB_UI"

PZMB = PZMB or {}
PZMB.Runtime = PZMB.Runtime or {
    dirty = false,
    frame = 0,
    lastExportWorldAgeHours = -1,
}

local Runtime = PZMB.Runtime

local function export(reason, scanBase)
    if scanBase then PZMB.Scanner.scanBaseLoadedSquares() end
    local ok = PZMB.Export.write(reason)
    if ok then
        Runtime.dirty = false
        Runtime.lastExportWorldAgeHours = getGameTime():getWorldAgeHours()
    end
end

local function onGameStart()
    PZMB.Config.load()
    PZMB.Config.applyCurrentSave()
    export("game_start", true)
end

local function onContainerUpdate()
    Runtime.dirty = true
end

local function onRefreshInventoryWindowContainers(inventoryPage, state)
    if state and state ~= "end" then return end
    PZMB.Scanner.observeInventoryWindow(inventoryPage)
    Runtime.dirty = true
end

local function onPlayerUpdate()
    Runtime.frame = Runtime.frame + 1
    if Runtime.frame % 30 == 0 then
        local opened = PZMB.Scanner.observeSelectedContainer()
        if opened then
            PZMB.Export.appendEvent(opened)
            Runtime.dirty = true
        end
    end
    if Runtime.dirty and Runtime.frame % 180 == 0 then
        export("runtime_change", false)
    end
end

local function everyTenMinutes()
    export("every_ten_game_minutes", true)
end

local function onPostSave()
    export("post_save", true)
end

Events.OnGameStart.Add(onGameStart)
Events.OnContainerUpdate.Add(onContainerUpdate)
Events.OnRefreshInventoryWindowContainers.Add(onRefreshInventoryWindowContainers)
Events.OnPlayerUpdate.Add(onPlayerUpdate)
Events.EveryTenMinutes.Add(everyTenMinutes)
Events.OnPostSave.Add(onPostSave)

return Runtime
