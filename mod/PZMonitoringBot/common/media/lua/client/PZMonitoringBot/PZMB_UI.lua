require "PZMonitoringBot/PZMB_Config"
require "PZMonitoringBot/PZMB_Vehicles"
require "PZMonitoringBot/PZMB_Export"
require "ISUI/ISTextBox"
require "Vehicles/ISUI/ISVehicleMenu"
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

local function vehicleLabel(record)
    return string.format(
        "%s (%s; %d, %d, %d)",
        tostring(record.name or record.displayName or tr("UI_PZMB_Vehicle")),
        tostring(record.displayName or record.scriptName or "?"),
        math.floor(tonumber(record.x) or 0),
        math.floor(tonumber(record.y) or 0),
        math.floor(tonumber(record.z) or 0)
    )
end

local function vehicleUnderCursor(player)
    if not player then return nil end
    local current = player:getVehicle()
    if current then return current end
    if IsoObjectPicker and IsoObjectPicker.Instance then
        local ok, vehicle = pcall(
            IsoObjectPicker.Instance.PickVehicle,
            IsoObjectPicker.Instance,
            getMouseXScaled(), getMouseYScaled()
        )
        if ok then return vehicle end
    end
    return nil
end

function UI.claimVehicle(vehicle)
    local ok, record, result = PZMB.Vehicles.register(vehicle)
    if not ok then
        if result == "missing_key" then
            say(tr("UI_PZMB_MsgVehicleKeyRequired"))
        else
            say(tr("UI_PZMB_MsgVehicleSaveFailed"))
        end
        return
    end
    PZMB.Scanner.observeVehicle(vehicle, "vehicle_registered")
    local exported, err = PZMB.Export.write("vehicle_registered")
    if not exported then
        say(tr("UI_PZMB_MsgSnapshotFailed", tostring(err)))
        return
    end
    if result then
        say(tr("UI_PZMB_MsgVehicleSaved", tostring(record.name)))
    else
        say(tr("UI_PZMB_MsgVehicleAlreadySaved", tostring(record.name)))
    end
end

function UI.onRenameVehicleSubmitted(_, button, vehicleId)
    if not button or button.internal ~= "OK" then return end
    local modal = button.parent
    local newName = modal and modal.entry and modal.entry:getText() or ""
    if PZMB.Vehicles.rename(vehicleId, newName) then
        say(tr("UI_PZMB_MsgVehicleRenamed", tostring(newName)))
    else
        say(tr("UI_PZMB_MsgRenameFailed"))
    end
end

function UI.openRenameVehicleDialog(record)
    if not record then return end
    local modal = ISTextBox:new(
        0, 0, 390, 150,
        tr("UI_PZMB_RenameVehiclePrompt"),
        tostring(record.name or ""),
        UI, UI.onRenameVehicleSubmitted, 0, record.vehicleId
    )
    modal:initialise()
    modal:addToUIManager()
    modal.moveWithMouse = true
end

function UI.onDeleteVehicleConfirmed(_, button, vehicleId, vehicleName)
    if not button or button.internal ~= "YES" then return end
    if PZMB.Vehicles.remove(vehicleId) then
        PZMB.Export.write("vehicle_removed")
        say(tr("UI_PZMB_MsgVehicleDeleted", tostring(vehicleName)))
    else
        say(tr("UI_PZMB_MsgVehicleDeleteFailed"))
    end
end

function UI.confirmDeleteVehicle(record)
    if not record then return end
    local modal = ISModalDialog:new(
        0, 0, 420, 150,
        tr("UI_PZMB_DeleteVehicleConfirm", tostring(record.name)),
        true, UI, UI.onDeleteVehicleConfirmed, 0, record.vehicleId, record.name
    )
    modal:initialise()
    modal:addToUIManager()
    modal.moveWithMouse = true
end

function UI.updateVehicle(record)
    if not record then return end
    PZMB.Scanner.refreshOwnedVehicles()
    local vehicle = PZMB.Scanner.vehicleRefs[tostring(record.vehicleId)]
    if not vehicle then
        say(tr("UI_PZMB_MsgVehicleNotLoaded", tostring(record.name)))
        return
    end
    local snapshot = PZMB.Scanner.observeVehicle(vehicle, "manual_vehicle_scan")
    if not snapshot then
        say(tr("UI_PZMB_MsgVehicleUpdateFailed", tostring(record.name)))
        return
    end
    PZMB.Vehicles.updatePosition(vehicle)
    PZMB.Vehicles.save()
    local ok, err = PZMB.Export.write("manual_vehicle_scan")
    if ok then
        say(tr("UI_PZMB_MsgVehicleUpdated", tostring(record.name)))
    else
        say(tr("UI_PZMB_MsgSnapshotFailed", tostring(err)))
    end
end

local function addVehicleActions(parentMenu, record)
    local option = parentMenu:addOption(vehicleLabel(record), record, nil)
    local actions = ISContextMenu:getNew(parentMenu)
    parentMenu:addSubMenu(option, actions)
    actions:addOption(tr("UI_PZMB_RenameVehicle"), record, UI.openRenameVehicleDialog)
    actions:addOption(tr("UI_PZMB_UpdateVehicle"), record, UI.updateVehicle)
    actions:addOption(tr("UI_PZMB_DeleteVehicle"), record, UI.confirmDeleteVehicle)
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
    if PZMB.Scanner.isPlayerNearAnyBase(15) then
        local scanned = PZMB.Scanner.scanBaseLoadedSquares()
        if scanned == 0 then PZMB.Scanner.refreshKnownBaseContainers() end
    end
    PZMB.Scanner.refreshOwnedVehicles()
    PZMB.Vehicles.save()
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

    local player = getSpecificPlayer(playerNum)
    local targetVehicle = vehicleUnderCursor(player)
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


    if targetVehicle then
        local vehicleId = PZMB.Vehicles.vehicleId(targetVehicle)
        local record = PZMB.Vehicles.findById(vehicleId)
        if record then
            local currentVehicle = menu:addOption(
                tr("UI_PZMB_CurrentVehicle", tostring(record.name)), record, nil
            )
            local currentVehicleMenu = ISContextMenu:getNew(menu)
            menu:addSubMenu(currentVehicle, currentVehicleMenu)
            currentVehicleMenu:addOption(tr("UI_PZMB_RenameVehicle"), record, UI.openRenameVehicleDialog)
            currentVehicleMenu:addOption(tr("UI_PZMB_UpdateVehicle"), record, UI.updateVehicle)
            currentVehicleMenu:addOption(tr("UI_PZMB_DeleteVehicle"), record, UI.confirmDeleteVehicle)
        elseif PZMB.Vehicles.playerHasKey(targetVehicle, player) then
            menu:addOption(tr("UI_PZMB_ClaimVehicle"), targetVehicle, UI.claimVehicle)
        else
            local noKey = menu:addOption(tr("UI_PZMB_ClaimVehicleNoKey"), targetVehicle, nil)
            noKey.notAvailable = true
        end
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


    local vehicleRecords = PZMB.Vehicles.currentRecords()
    local vehiclesRoot = menu:addOption(
        tr("UI_PZMB_MyVehicles", tostring(#vehicleRecords)), vehicleRecords, nil
    )
    local vehiclesMenu = ISContextMenu:getNew(menu)
    menu:addSubMenu(vehiclesRoot, vehiclesMenu)
    if #vehicleRecords == 0 then
        local emptyVehicles = vehiclesMenu:addOption(tr("UI_PZMB_NoVehicles"), vehicleRecords, nil)
        emptyVehicles.notAvailable = true
    else
        for _, record in ipairs(vehicleRecords) do addVehicleActions(vehiclesMenu, record) end
    end
    menu:addOption(tr("UI_PZMB_UpdateAll"), worldObjects, UI.exportNow)
end

Events.OnFillWorldObjectContextMenu.Add(UI.onWorldContextMenu)

return UI
