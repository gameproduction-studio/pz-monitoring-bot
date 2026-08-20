PZMB = PZMB or {}
PZMB.Json = PZMB.Json or {}

local function escapeString(value)
    local escaped = value:gsub("\\", "\\\\")
    escaped = escaped:gsub('"', '\\"')
    escaped = escaped:gsub("\b", "\\b")
    escaped = escaped:gsub("\f", "\\f")
    escaped = escaped:gsub("\n", "\\n")
    escaped = escaped:gsub("\r", "\\r")
    escaped = escaped:gsub("\t", "\\t")
    escaped = escaped:gsub("[%z\1-\31]", function(char)
        return string.format("\\u%04x", string.byte(char))
    end)
    return '"' .. escaped .. '"'
end

local function isArray(value)
    local count = 0
    local maximum = 0
    for key, _ in pairs(value) do
        if type(key) ~= "number" or key < 1 or key ~= math.floor(key) then
            return false, 0
        end
        count = count + 1
        if key > maximum then maximum = key end
    end
    return count == maximum, maximum
end

local function encodeValue(value, stack)
    local valueType = type(value)
    if value == nil then
        return "null"
    elseif valueType == "boolean" then
        return value and "true" or "false"
    elseif valueType == "number" then
        if value ~= value or value == math.huge or value == -math.huge then
            return "null"
        end
        return tostring(value)
    elseif valueType == "string" then
        return escapeString(value)
    elseif valueType ~= "table" then
        return escapeString(tostring(value))
    end

    if stack[value] then
        error("cannot JSON-encode a cyclic table")
    end
    stack[value] = true

    local array, length = isArray(value)
    local parts = {}
    if array then
        for index = 1, length do
            parts[#parts + 1] = encodeValue(value[index], stack)
        end
        stack[value] = nil
        return "[" .. table.concat(parts, ",") .. "]"
    end

    local keys = {}
    for key, _ in pairs(value) do
        keys[#keys + 1] = tostring(key)
    end
    table.sort(keys)
    for _, key in ipairs(keys) do
        parts[#parts + 1] = escapeString(key) .. ":" .. encodeValue(value[key], stack)
    end
    stack[value] = nil
    return "{" .. table.concat(parts, ",") .. "}"
end

function PZMB.Json.encode(value)
    return encodeValue(value, {})
end

function PZMB.Json.writeFile(fileName, value)
    local writer = getFileWriter(fileName, true, false)
    if not writer then
        error("getFileWriter returned nil for " .. tostring(fileName))
    end
    local ok, encoded = pcall(PZMB.Json.encode, value)
    if not ok then
        writer:close()
        error(encoded)
    end
    writer:write(encoded)
    writer:write("\r\n")
    writer:close()
end

function PZMB.Json.appendLine(fileName, value)
    local writer = getFileWriter(fileName, true, true)
    if not writer then
        error("getFileWriter returned nil for " .. tostring(fileName))
    end
    local ok, encoded = pcall(PZMB.Json.encode, value)
    if not ok then
        writer:close()
        error(encoded)
    end
    writer:write(encoded)
    writer:write("\r\n")
    writer:close()
end

