require "PZMonitoringBot/PZMB_Config"
require "PZMonitoringBot/PZMB_Export"
require "ISUI/ISTextBox"
require "ISUI/ISModalDialog"

PZMB = PZMB or {}
PZMB.UI = PZMB.UI or {}

local UI = PZMB.UI

local function tr(key, ...)
    return getText(key, ...)
end

local function say(message)
    local player = getPlayer()
    if player then player:Say(message) end
    print("[pz monitoring bot] " .. message)
end

local function zoneLabel(zone)
    return string.format(
        "%s (%d, %d, %d; %s %d)",
        tostring(zone.name or tr("UI_PZMB_Base")),
        tonumber(zone.x) or 0,
        tonumber(zone.y) or 0,
        tonumber(zone.z) or 0,
        tr("UI_PZMB_Radius"),
        tonumber(zone.radius) or PZMB.Config.defaultRadius
    )
end

local function currentBase()
    local player = getPlayer()
    if not player then return nil end
    return PZMB.Config.findContainingBase(
        math.floor(player:getX()),
        math.floor(player:getY()),
        math.floor(player:getZ())
    )
end

function UI.setBaseHere()
    local ok, zone, created = PZMB.Config.setBaseHere(PZMB.Config.defaultRadius)
    if not ok then
        say(tr("UI_PZMB_MsgSetBaseNoPlayer"))
        return
    end
    if created then
        say(tr("UI_PZMB_MsgBaseSaved", tostring(zone.name), tostring(zone.radius)))
    else
        say(tr("UI_PZMB_MsgAlreadyInside", tostring(zone.name)))
    end
end

function UI.onRenameSubmitted(_, button, zoneId)
    if not button or button.internal ~= "OK" then return end
    local modal = button.parent
    local newName = modal and modal.entry and modal.entry:getText() or ""
    if PZMB.Config.renameBase(zoneId, newName) then
        say(tr("UI_PZMB_MsgRenamed", tostring(newName)))
    else
        say(tr("UI_PZMB_MsgRenameFailed"))
    end
end

function UI.openRenameDialog(zone)
    if not zone then return end
    local modal = ISTextBox:new(
        0, 0, 360, 150,
        tr("UI_PZMB_RenamePrompt"),
        tostring(zone.name or ""),
        UI, UI.onRenameSubmitted, 0, zone.id
    )
    modal:initialise()
    modal:addToUIManager()
    modal.moveWithMouse = true
end

function UI.onDeleteConfirmed(_, button, zoneId, zoneName)
    if not button or button.internal ~= "YES" then return end
    if PZMB.Config.removeBase(zoneId) then
        say(tr("UI_PZMB_MsgDeleted", tostring(zoneName)))
    else
        say(tr("UI_PZMB_MsgDeleteFailed"))
    end
end

function UI.confirmDeleteBase(zone)
    if not zone then return end
    local modal = ISModalDialog:new(
        0, 0, 390, 150,
        tr("UI_PZMB_DeleteConfirm", tostring(zone.name)),
        true, UI, UI.onDeleteConfirmed, 0, zone.id, zone.name
    )
    modal:initialise()
    modal:addToUIManager()
    modal.moveWithMouse = true
end

function UI.scanBase(zone)
    if not zone then return end
    PZMB.Scanner.baseIndexesBuilt[zone.id] = nil
    local squares = PZMB.Scanner.scanBaseLoadedSquares(zone.id)
    if squares == 0 then
        say(tr("UI_PZMB_MsgZoneNotLoaded", tostring(zone.name)))
        return
    end
    PZMB.Scanner.refreshKnownBaseContainers()
    local ok, err = PZMB.Export.write("manual_base_scan")
    if ok then
        say(tr("UI_PZMB_MsgBaseUpdated", tostring(zone.name)))
    else
        say(tr("UI_PZMB_MsgSnapshotFailed", tostring(err)))
    end
end

function UI.rememberOpenContainer()
    local ok, err = pcall(PZMB.Scanner.observeSelectedContainer, true)
    if not ok then
        say(tr("UI_PZMB_MsgRememberFailed", tostring(err)))
        return
    end
    local id = PZMB.Scanner.lastSelectedContainerId
    local snapshot = id and PZMB.Scanner.knownContainers[id] or nil
    if snapshot then
        say(tr("UI_PZMB_MsgContainerRemembered", tostring(snapshot.displayName or snapshot.containerType or id)))
    else
        say(tr("UI_PZMB_MsgOpenContainerFirst"))
    end
end

function UI.exportNow()
    PZMB.Scanner.observeSelectedContainer(false)
    local scanned = PZMB.Scanner.scanBaseLoadedSquares()
    if scanned == 0 then PZMB.Scanner.refreshKnownContainers() end
    local ok, err = PZMB.Export.write("manual")
    if ok then
        say(tr("UI_PZMB_MsgRecordsUpdated"))
    else
        say(tr("UI_PZMB_MsgRecordsFailed", tostring(err)))
    end
end

local function addBaseActions(parentMenu, zone)
    local option = parentMenu:addOption(zoneLabel(zone), zone, nil)
    local actions = ISContextMenu:getNew(parentMenu)
    parentMenu:addSubMenu(option, actions)
    actions:addOption(tr("UI_PZMB_Rename"), zone, UI.openRenameDialog)
    actions:addOption(tr("UI_PZMB_UpdateBase"), zone, UI.scanBase)
    actions:addOption(tr("UI_PZMB_DeleteBase"), zone, UI.confirmDeleteBase)
end

function UI.onWorldContextMenu(playerNum, context, worldObjects)
    if playerNum ~= 0 then return end

    local root = context:addOption(tr("UI_PZMB_Organizer"), worldObjects, nil)
    local menu = ISContextMenu:getNew(context)
    context:addSubMenu(root, menu)

    local here = currentBase()
    if here then
        local current = menu:addOption(tr("UI_PZMB_CurrentBase", tostring(here.name)), here, nil)
        local currentMenu = ISContextMenu:getNew(menu)
        menu:addSubMenu(current, currentMenu)
        currentMenu:addOption(tr("UI_PZMB_Rename"), here, UI.openRenameDialog)
        currentMenu:addOption(tr("UI_PZMB_UpdateBase"), here, UI.scanBase)
        currentMenu:addOption(tr("UI_PZMB_DeleteBase"), here, UI.confirmDeleteBase)
    else
        menu:addOption(
            tr("UI_PZMB_SetBaseHere", tostring(PZMB.Config.defaultRadius)),
            worldObjects, UI.setBaseHere
        )
    end

    local zones = PZMB.Config.currentZones()
    local basesRoot = menu:addOption(tr("UI_PZMB_MyBases", tostring(#zones)), zones, nil)
    local basesMenu = ISContextMenu:getNew(menu)
    menu:addSubMenu(basesRoot, basesMenu)
    if #zones == 0 then
        local empty = basesMenu:addOption(tr("UI_PZMB_NoBases"), zones, nil)
        empty.notAvailable = true
    else
        for _, zone in ipairs(zones) do addBaseActions(basesMenu, zone) end
    end

    menu:addOption(tr("UI_PZMB_RememberContainer"), worldObjects, UI.rememberOpenContainer)
    menu:addOption(tr("UI_PZMB_UpdateAll"), worldObjects, UI.exportNow)
end

Events.OnFillWorldObjectContextMenu.Add(UI.onWorldContextMenu)

return UI
