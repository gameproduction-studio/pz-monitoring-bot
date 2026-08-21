PZMB = PZMB or {}
PZMB.Config = PZMB.Config or {}

local Config = PZMB.Config
-- Build 42.20.3 rejects some non-whitelisted extensions in getFileWriter().
Config.fileName = "pzmb_bases.txt"
Config.defaultRadius = 30
Config.records = Config.records or {}

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

local function zoneId(x, y, z)
    return table.concat({ "base", tostring(x), tostring(y), tostring(z) }, ":")
end

local function defaultBaseName(number)
    if number then return getText("UI_PZMB_BaseNumber", tostring(number)) end
    return getText("UI_PZMB_Base")
end

local function normalizeZone(id, name, x, y, z, radius, minZ, maxZ)
    x, y, z = tonumber(x), tonumber(y), tonumber(z)
    if not x or not y or not z then return nil end
    return {
        id = unescape(id or "") ~= "" and unescape(id) or zoneId(x, y, z),
        name = unescape(name or "") ~= "" and unescape(name) or defaultBaseName(),
        shape = "circle",
        x = x,
        y = y,
        z = z,
        radius = tonumber(radius) or Config.defaultRadius,
        minZ = tonumber(minZ) or z - 2,
        maxZ = tonumber(maxZ) or z + 5,
    }
end

function Config.currentSaveKey()
    local world = getWorld()
    if not world then return "unknown:unknown" end
    return tostring(world:getGameMode()) .. ":" .. tostring(world:getWorld())
end

function Config.load()
    Config.records = {}
    local reader = getFileReader(Config.fileName, true)
    if not reader then return end
    local line = reader:readLine()
    while line do
        if line ~= "" and line:sub(1, 1) ~= "#" then
            local values = split(line)
            local key, zone
            if #values == 8 then
                key = unescape(values[1])
                local migratedName = unescape(values[2])
                if migratedName == "Main base" then migratedName = defaultBaseName(1) end
                zone = normalizeZone(nil, migratedName, values[3], values[4], values[5], values[6], values[7], values[8])
            elseif #values >= 9 then
                key = unescape(values[1])
                zone = normalizeZone(values[2], values[3], values[4], values[5], values[6], values[7], values[8], values[9])
            end
            if key and zone then
                Config.records[key] = Config.records[key] or {}
                Config.records[key][#Config.records[key] + 1] = zone
            end
        end
        line = reader:readLine()
    end
    reader:close()
end

function Config.save()
    local writer = getFileWriter(Config.fileName, true, false)
    if not writer then error("cannot write " .. Config.fileName) end
    writer:write("# save|id|name|x|y|z|radius|minZ|maxZ\r\n")
    local keys = {}
    for key, _ in pairs(Config.records) do keys[#keys + 1] = key end
    table.sort(keys)
    for _, key in ipairs(keys) do
        local zones = Config.records[key] or {}
        table.sort(zones, function(left, right) return tostring(left.id) < tostring(right.id) end)
        for _, zone in ipairs(zones) do
            writer:write(table.concat({
                escape(key), escape(zone.id), escape(zone.name or defaultBaseName()),
                tostring(zone.x), tostring(zone.y), tostring(zone.z),
                tostring(zone.radius), tostring(zone.minZ), tostring(zone.maxZ),
            }, "|"))
            writer:write("\r\n")
        end
    end
    writer:close()
end

function Config.currentZones()
    return Config.records[Config.currentSaveKey()] or {}
end

function Config.applyCurrentSave()
    local zones = Config.currentZones()
    PZMB.Scanner.setBaseZones(zones)
    return zones
end

function Config.findContainingBase(x, y, z)
    for _, zone in ipairs(Config.currentZones()) do
        if z >= zone.minZ and z <= zone.maxZ then
            local dx, dy = x - zone.x, y - zone.y
            if dx * dx + dy * dy <= zone.radius * zone.radius then return zone end
        end
    end
    return nil
end

function Config.setBaseHere(radius)
    local player = getPlayer()
    if not player then return false, nil, false end
    local x = math.floor(player:getX())
    local y = math.floor(player:getY())
    local z = math.floor(player:getZ())
    local existing = Config.findContainingBase(x, y, z)
    if existing then return true, existing, false end

    local key = Config.currentSaveKey()
    local zones = Config.records[key] or {}
    local zone = normalizeZone(
        zoneId(x, y, z),
        defaultBaseName(#zones + 1),
        x, y, z,
        math.max(1, math.floor(tonumber(radius) or Config.defaultRadius)),
        z - 2, z + 5
    )
    zones[#zones + 1] = zone
    Config.records[key] = zones
    Config.save()
    Config.applyCurrentSave()
    return true, zone, true
end

function Config.renameBase(id, newName)
    newName = tostring(newName or ""):gsub("^%s+", ""):gsub("%s+$", "")
    if newName == "" then return false end
    for _, zone in ipairs(Config.currentZones()) do
        if zone.id == id then
            zone.name = newName
            Config.save()
            Config.applyCurrentSave()
            return true
        end
    end
    return false
end

function Config.removeBase(id)
    local key = Config.currentSaveKey()
    local zones = Config.records[key] or {}
    for index, zone in ipairs(zones) do
        if zone.id == id then
            table.remove(zones, index)
            if #zones == 0 then Config.records[key] = nil end
            Config.save()
            Config.applyCurrentSave()
            return true
        end
    end
    return false
end

return Config
