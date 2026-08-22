require "PZMonitoringBot/PZMB_Config"

PZMB = PZMB or {}
PZMB.Vehicles = PZMB.Vehicles or {}

local Vehicles = PZMB.Vehicles
Vehicles.fileName = "pzmb_vehicles.txt"
Vehicles.records = Vehicles.records or {}

local function safeCall(object, methodName, defaultValue, ...)
    if not object then return defaultValue end
    local method = object[methodName]
    if not method then return defaultValue end
    local ok, value = pcall(method, object, ...)
    if not ok or value == nil then return defaultValue end
    return value
end

local function escape(value)
    value = tostring(value or "")
    value = value:gsub("%%", "%%25")
    value = value:gsub("|", "%%7C")
    value = value:gsub("\r", "%%0D")
    value = value:gsub("\n", "%%0A")
    return value
end

local function unescape(value)
    value = tostring(value or "")
    value = value:gsub("%%0A", "\n")
    value = value:gsub("%%0D", "\r")
    value = value:gsub("%%7C", "|")
    value = value:gsub("%%25", "%%")
    return value
end

local function split(line)
    local values = {}
    for value in (line .. "|"):gmatch("(.-)|") do values[#values + 1] = value end
    return values
end

local function vehicleId(vehicle)
    if not vehicle then return nil end
    local value = safeCall(vehicle, "getId", nil)
    if value == nil then return nil end
    return tostring(value)
end

local function vehicleNames(vehicle)
    local script = safeCall(vehicle, "getScript", nil)
    local scriptName = tostring(safeCall(script, "getName", "unknown"))
    local modelName = tostring(safeCall(script, "getCarModelName", scriptName))
    local localized = getTextOrNull("IGUI_VehicleName" .. modelName)
        or getTextOrNull("IGUI_VehicleName" .. scriptName)
        or modelName
    return tostring(localized), tostring(safeCall(script, "getFullType", scriptName)), scriptName
end

local function vehicleSqlId(vehicle)
    local value = tonumber(safeCall(vehicle, "getSqlId", -1)) or -1
    if value < 0 then return nil end
    return value
end

local function vehicleKeyId(vehicle)
    local value = tonumber(safeCall(vehicle, "getKeyId", -1)) or -1
    if value < 0 then return nil end
    return value
end

local function normalizeRecord(values)
    if #values < 10 then return nil, nil end
    local key = unescape(values[1])
    local id = unescape(values[2])
    if key == "" or id == "" then return nil, nil end
    return key, {
        vehicleId = id,
        keyId = tonumber(values[3]) or -1,
        name = unescape(values[4]),
        displayName = unescape(values[5]),
        scriptFullType = unescape(values[6]),
        scriptName = unescape(values[7]),
        x = tonumber(values[8]),
        y = tonumber(values[9]),
        z = tonumber(values[10]),
        sqlId = tonumber(values[11]),
    }
end

function Vehicles.currentSaveKey()
    return PZMB.Config.currentSaveKey()
end

function Vehicles.load()
    Vehicles.records = {}
    local reader = getFileReader(Vehicles.fileName, true)
    if reader then
        local line = reader:readLine()
        while line do
            if line ~= "" and line:sub(1, 1) ~= "#" then
                local key, record = normalizeRecord(split(line))
                if key and record then
                    Vehicles.records[key] = Vehicles.records[key] or {}
                    Vehicles.records[key][#Vehicles.records[key] + 1] = record
                end
            end
            line = reader:readLine()
        end
        reader:close()
    end
    Vehicles.applyCurrentSave()
end

function Vehicles.save()
    local writer = getFileWriter(Vehicles.fileName, true, false)
    if not writer then error("cannot write " .. Vehicles.fileName) end
    writer:write("# save|vehicleId|keyId|name|displayName|scriptFullType|scriptName|x|y|z|sqlId\r\n")
    local keys = {}
    for key, _ in pairs(Vehicles.records) do keys[#keys + 1] = key end
    table.sort(keys)
    for _, key in ipairs(keys) do
        local records = Vehicles.records[key] or {}
        table.sort(records, function(left, right)
            return tostring(left.vehicleId) < tostring(right.vehicleId)
        end)
        for _, record in ipairs(records) do
            writer:write(table.concat({
                escape(key), escape(record.vehicleId), tostring(record.keyId or -1),
                escape(record.name), escape(record.displayName), escape(record.scriptFullType),
                escape(record.scriptName), tostring(record.x or 0), tostring(record.y or 0),
                tostring(record.z or 0), tostring(record.sqlId or -1),
            }, "|"))
            writer:write("\r\n")
        end
    end
    writer:close()
end

function Vehicles.currentRecords()
    return Vehicles.records[Vehicles.currentSaveKey()] or {}
end

function Vehicles.applyCurrentSave()
    if PZMB.Scanner and PZMB.Scanner.setOwnedVehicles then
        PZMB.Scanner.setOwnedVehicles(Vehicles.currentRecords())
    end
end

function Vehicles.findById(id)
    id = tostring(id or "")
    for _, record in ipairs(Vehicles.currentRecords()) do
        if tostring(record.vehicleId) == id then return record end
    end
    return nil
end

function Vehicles.findBySqlId(sqlId)
    sqlId = tonumber(sqlId)
    if not sqlId or sqlId < 0 then return nil end
    for _, record in ipairs(Vehicles.currentRecords()) do
        if tonumber(record.sqlId) == sqlId then return record end
    end
    return nil
end

function Vehicles.findByKeyId(keyId)
    keyId = tonumber(keyId)
    if not keyId or keyId < 0 then return nil end
    for _, record in ipairs(Vehicles.currentRecords()) do
        if tonumber(record.keyId) == keyId then return record end
    end
    return nil
end

function Vehicles.findByVehicle(vehicle)
    if not vehicle then return nil end
    local record = Vehicles.findBySqlId(vehicleSqlId(vehicle))
    if record then return record end
    record = Vehicles.findByKeyId(vehicleKeyId(vehicle))
    if record then return record end

    -- getId() is a session-local network id in Build 42 and may be reused
    -- after restart. Use it only when the saved vehicle signature agrees.
    record = Vehicles.findById(vehicleId(vehicle))
    if not record then return nil end
    local _, scriptFullType = vehicleNames(vehicle)
    local recordKeyId = tonumber(record.keyId) or -1
    local liveKeyId = vehicleKeyId(vehicle) or -1
    if record.scriptFullType ~= scriptFullType then return nil end
    if recordKeyId >= 0 and liveKeyId >= 0 and recordKeyId ~= liveKeyId then return nil end
    return record
end

function Vehicles.bindIdentity(vehicle, record)
    record = record or Vehicles.findByVehicle(vehicle)
    if not vehicle or not record then return false end
    local changed = false
    local id = vehicleId(vehicle)
    local sqlId = vehicleSqlId(vehicle)
    if id and tostring(record.vehicleId) ~= id then
        record.vehicleId = id
        changed = true
    end
    if sqlId and tonumber(record.sqlId) ~= sqlId then
        record.sqlId = sqlId
        changed = true
    end
    local x = safeCall(vehicle, "getX", record.x)
    local y = safeCall(vehicle, "getY", record.y)
    local z = safeCall(vehicle, "getZ", record.z)
    if record.x ~= x or record.y ~= y or record.z ~= z then
        record.x, record.y, record.z = x, y, z
        changed = true
    end
    if changed then
        Vehicles.save()
        Vehicles.applyCurrentSave()
    end
    return changed
end

local function containerHasKeyId(container, keyId, seen)
    if not container then return false end
    seen = seen or {}
    local marker = tostring(container)
    if seen[marker] then return false end
    seen[marker] = true

    -- Build 42.20.3 only checks the direct contents here. Keep the fast path,
    -- then explicitly descend into key rings and any other nested containers.
    if safeCall(container, "haveThisKeyId", false, keyId) == true then return true end

    local items = safeCall(container, "getItems", nil)
    local count = tonumber(safeCall(items, "size", 0)) or 0
    for index = 0, count - 1 do
        local item = safeCall(items, "get", nil, index)
        local itemKeyId = tonumber(safeCall(item, "getKeyId", -1)) or -1
        if itemKeyId == keyId then return true end

        local nested = nil
        if item and instanceof(item, "InventoryContainer") then
            nested = safeCall(item, "getInventory", nil)
        end
        if nested and containerHasKeyId(nested, keyId, seen) then return true end
    end
    return false
end

function Vehicles.playerHasKey(vehicle, player)
    player = player or getPlayer()
    if not player or not vehicle then return false end
    local inventory = safeCall(player, "getInventory", nil)
    local keyId = tonumber(safeCall(vehicle, "getKeyId", -1)) or -1
    if keyId < 0 then return false end
    return containerHasKeyId(inventory, keyId, {})
end

function Vehicles.register(vehicle)
    local id = vehicleId(vehicle)
    if not id then return false, nil, "invalid_vehicle" end
    local existing = Vehicles.findByVehicle(vehicle)
    if existing then return true, existing, false end
    if not Vehicles.playerHasKey(vehicle) then return false, nil, "missing_key" end

    local key = Vehicles.currentSaveKey()
    local records = Vehicles.records[key] or {}
    local displayName, scriptFullType, scriptName = vehicleNames(vehicle)
    local record = {
        vehicleId = id,
        keyId = tonumber(safeCall(vehicle, "getKeyId", -1)) or -1,
        sqlId = vehicleSqlId(vehicle),
        name = getText("UI_PZMB_VehicleDefaultName", displayName, tostring(#records + 1)),
        displayName = displayName,
        scriptFullType = scriptFullType,
        scriptName = scriptName,
        x = safeCall(vehicle, "getX", 0),
        y = safeCall(vehicle, "getY", 0),
        z = safeCall(vehicle, "getZ", 0),
    }
    records[#records + 1] = record
    Vehicles.records[key] = records
    Vehicles.save()
    Vehicles.applyCurrentSave()
    return true, record, true
end

function Vehicles.rename(id, newName)
    newName = tostring(newName or ""):gsub("^%s+", ""):gsub("%s+$", "")
    if newName == "" then return false end
    local record = Vehicles.findById(id)
    if not record then return false end
    record.name = newName
    Vehicles.save()
    Vehicles.applyCurrentSave()
    return true
end

function Vehicles.remove(id)
    local key = Vehicles.currentSaveKey()
    local records = Vehicles.records[key] or {}
    id = tostring(id or "")
    for index, record in ipairs(records) do
        if tostring(record.vehicleId) == id then
            table.remove(records, index)
            if #records == 0 then Vehicles.records[key] = nil end
            Vehicles.save()
            Vehicles.applyCurrentSave()
            return true
        end
    end
    return false
end

function Vehicles.updatePosition(vehicle)
    local record = Vehicles.findByVehicle(vehicle)
    if not record then return false end
    Vehicles.bindIdentity(vehicle, record)
    return true
end

function Vehicles.vehicleId(vehicle)
    return vehicleId(vehicle)
end

return Vehicles
