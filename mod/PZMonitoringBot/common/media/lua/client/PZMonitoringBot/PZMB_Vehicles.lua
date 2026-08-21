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
    writer:write("# save|vehicleId|keyId|name|displayName|scriptFullType|scriptName|x|y|z\r\n")
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
                tostring(record.z or 0),
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

function Vehicles.findByVehicle(vehicle)
    return Vehicles.findById(vehicleId(vehicle))
end

function Vehicles.playerHasKey(vehicle, player)
    player = player or getPlayer()
    if not player or not vehicle then return false end
    local inventory = safeCall(player, "getInventory", nil)
    local keyId = safeCall(vehicle, "getKeyId", -1)
    if keyId == nil or tonumber(keyId) == nil or tonumber(keyId) < 0 then return false end
    return safeCall(inventory, "haveThisKeyId", false, keyId) == true
end

function Vehicles.register(vehicle)
    local id = vehicleId(vehicle)
    if not id then return false, nil, "invalid_vehicle" end
    local existing = Vehicles.findById(id)
    if existing then return true, existing, false end
    if not Vehicles.playerHasKey(vehicle) then return false, nil, "missing_key" end

    local key = Vehicles.currentSaveKey()
    local records = Vehicles.records[key] or {}
    local displayName, scriptFullType, scriptName = vehicleNames(vehicle)
    local record = {
        vehicleId = id,
        keyId = tonumber(safeCall(vehicle, "getKeyId", -1)) or -1,
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
    record.x = safeCall(vehicle, "getX", record.x)
    record.y = safeCall(vehicle, "getY", record.y)
    record.z = safeCall(vehicle, "getZ", record.z)
    return true
end

function Vehicles.vehicleId(vehicle)
    return vehicleId(vehicle)
end

return Vehicles
