PZMB = PZMB or {}
PZMB.Config = PZMB.Config or {}

local Config = PZMB.Config
Config.fileName = "pzmb_bases.tsv"
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
            local key, name, x, y, z, radius, minZ, maxZ =
                line:match("^([^|]*)|([^|]*)|([^|]*)|([^|]*)|([^|]*)|([^|]*)|([^|]*)|([^|]*)$")
            if key then
                Config.records[unescape(key)] = {
                    id = "main_base",
                    name = unescape(name),
                    shape = "circle",
                    x = tonumber(x),
                    y = tonumber(y),
                    z = tonumber(z),
                    radius = tonumber(radius) or Config.defaultRadius,
                    minZ = tonumber(minZ),
                    maxZ = tonumber(maxZ),
                }
            end
        end
        line = reader:readLine()
    end
    reader:close()
end

function Config.save()
    local writer = getFileWriter(Config.fileName, true, false)
    if not writer then error("cannot write " .. Config.fileName) end
    writer:write("# save|name|x|y|z|radius|minZ|maxZ\r\n")
    local keys = {}
    for key, _ in pairs(Config.records) do keys[#keys + 1] = key end
    table.sort(keys)
    for _, key in ipairs(keys) do
        local base = Config.records[key]
        writer:write(table.concat({
            escape(key),
            escape(base.name or "Main base"),
            tostring(base.x),
            tostring(base.y),
            tostring(base.z),
            tostring(base.radius),
            tostring(base.minZ),
            tostring(base.maxZ),
        }, "|"))
        writer:write("\r\n")
    end
    writer:close()
end

function Config.applyCurrentSave()
    local base = Config.records[Config.currentSaveKey()]
    PZMB.Scanner.baseZone = base
    return base
end

function Config.setBaseHere(radius, name)
    if not PZMB.Scanner.setBaseHere(radius or Config.defaultRadius) then return false end
    PZMB.Scanner.baseZone.name = name or "Main base"
    Config.records[Config.currentSaveKey()] = PZMB.Scanner.baseZone
    Config.save()
    return true
end

function Config.clearBase()
    Config.records[Config.currentSaveKey()] = nil
    PZMB.Scanner.baseZone = nil
    Config.save()
end

return Config
