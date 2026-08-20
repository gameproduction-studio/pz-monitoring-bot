require "PZMonitoringBot/PZMB_Config"
require "PZMonitoringBot/PZMB_Export"

PZMB = PZMB or {}
PZMB.UI = PZMB.UI or {}

local UI = PZMB.UI

local function say(message)
    local player = getPlayer()
    if player then player:Say(message) end
    print("[pz monitoring bot] " .. message)
end

function UI.setBaseHere()
    if PZMB.Config.setBaseHere(PZMB.Config.defaultRadius, "Main base") then
        PZMB.Scanner.scanBaseLoadedSquares()
        PZMB.Export.write("base_set")
        say("Monitoring base set here, radius " .. tostring(PZMB.Config.defaultRadius) .. " tiles.")
    else
        say("Could not set monitoring base: no active player.")
    end
end

function UI.clearBase()
    PZMB.Config.clearBase()
    PZMB.Export.write("base_cleared")
    say("Monitoring base cleared.")
end

function UI.exportNow()
    PZMB.Scanner.scanBaseLoadedSquares()
    local ok, err = PZMB.Export.write("manual")
    if ok then say("Monitoring snapshot exported.") else say("Export failed: " .. tostring(err)) end
end

function UI.onWorldContextMenu(playerNum, context, worldObjects)
    if playerNum ~= 0 then return end
    local root = context:addOption("pz monitoring bot", worldObjects, nil)
    local menu = ISContextMenu:getNew(context)
    context:addSubMenu(root, menu)
    menu:addOption("Set base here (30 tiles)", worldObjects, UI.setBaseHere)
    menu:addOption("Export current state now", worldObjects, UI.exportNow)
    if PZMB.Scanner.baseZone then
        menu:addOption("Clear base", worldObjects, UI.clearBase)
    end
end

Events.OnFillWorldObjectContextMenu.Add(UI.onWorldContextMenu)

return UI
