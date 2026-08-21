require "PZMonitoringBot/PZMB_Json"

PZMB = PZMB or {}
PZMB.Scanner = PZMB.Scanner or {}

local Scanner = PZMB.Scanner
Scanner.knownContainers = Scanner.knownContainers or {}
Scanner.containerRefs = Scanner.containerRefs or {}
Scanner.openedContainerIds = Scanner.openedContainerIds or {}
Scanner.baseZones = Scanner.baseZones or {}
Scanner.lastSelectedContainerId = Scanner.lastSelectedContainerId or nil
Scanner.baseIndexesBuilt = Scanner.baseIndexesBuilt or {}
Scanner.ownedVehicles = Scanner.ownedVehicles or {}
Scanner.ownedVehicleById = Scanner.ownedVehicleById or {}
Scanner.knownVehicles = Scanner.knownVehicles or {}
Scanner.vehicleRefs = Scanner.vehicleRefs or {}

local function safeCall(object, methodName, defaultValue, ...)
    if not object then return defaultValue end
    local method = object[methodName]
    if not method then return defaultValue end
    local ok, value = pcall(method, object, ...)
    if not ok or value == nil then return defaultValue end
    return value
end

local function toStringOrNil(value)
    if value == nil then return nil end
    return tostring(value)
end

local function javaListToArray(list)
    local result = {}
    if not list then return result end
    local size = safeCall(list, "size", 0)
    for index = 0, size - 1 do
        result[#result + 1] = tostring(safeCall(list, "get", "", index))
    end
    return result
end

local function tagsToArray(item)
    local tags = safeCall(item, "getTags", nil)
    if not tags then return {} end
    local ok, values = pcall(function() return tags:toArray() end)
    if ok and values then
        local result = {}
        for _, tag in ipairs(values) do
            result[#result + 1] = tostring(tag)
        end
        table.sort(result)
        return result
    end
    return javaListToArray(tags)
end

local function equipmentMap(player)
    local map = {}
    local function record(item, field, value)
        if not item then return end
        local id = tostring(safeCall(item, "getID", tostring(item)))
        map[id] = map[id] or {}
        map[id][field] = value
        map[id].equipped = true
    end

    record(safeCall(player, "getPrimaryHandItem", nil), "primaryHand", true)
    record(safeCall(player, "getSecondaryHandItem", nil), "secondaryHand", true)

    local worn = safeCall(player, "getWornItems", nil)
    local wornCount = safeCall(worn, "size", 0)
    for index = 0, wornCount - 1 do
        local entry = safeCall(worn, "get", nil, index)
        local item = safeCall(entry, "getItem", nil)
        local location = safeCall(entry, "getLocation", nil)
        if location == nil and item then
            location = safeCall(item, "getBodyLocation", nil)
        end
        record(item, "wornLocation", toStringOrNil(location) or "worn")
    end

    local attached = safeCall(player, "getAttachedItems", nil)
    local attachedCount = safeCall(attached, "size", 0)
    for index = 0, attachedCount - 1 do
        local entry = safeCall(attached, "get", nil, index)
        local item = safeCall(entry, "getItem", nil)
        local location = safeCall(entry, "getLocation", nil)
        record(item, "attachedLocation", toStringOrNil(location) or "attached")
    end
    return map
end

local function ammoType(item)
    local value = safeCall(item, "getAmmoType", nil)
    if value == nil then return nil end
    local key = safeCall(value, "getItemKey", nil)
    return toStringOrNil(key or value)
end

local function replaceOnCooked(food)
    local values = safeCall(food, "getReplaceOnCooked", nil)
    return javaListToArray(values)
end

local function foodData(item)
    if not instanceof(item, "Food") then return nil end
    local age = safeCall(item, "getAge", 0)
    local offAge = safeCall(item, "getOffAge", 1000000000)
    local offAgeMax = safeCall(item, "getOffAgeMax", 1000000000)
    local rotten = safeCall(item, "isRotten", false)
    local stage = "fresh"
    if rotten or age >= offAgeMax then
        stage = "rotten"
    elseif age >= offAge then
        stage = "stale"
    end

    local hoursUntilStale = nil
    local hoursUntilRotten = nil
    if offAge < 1000000000 then
        hoursUntilStale = math.max(0, (offAge - age) * 24)
    end
    if offAgeMax < 1000000000 then
        hoursUntilRotten = math.max(0, (offAgeMax - age) * 24)
    end

    return {
        calories = safeCall(item, "getCalories", 0),
        carbohydrates = safeCall(item, "getCarbohydrates", 0),
        lipids = safeCall(item, "getLipids", 0),
        proteins = safeCall(item, "getProteins", 0),
        hungerChange = safeCall(item, "getHungerChange", 0),
        baseHunger = safeCall(item, "getBaseHunger", 0),
        thirstChange = safeCall(item, "getThirstChange", 0),
        boredomChange = safeCall(item, "getBoredomChange", 0),
        unhappyChange = safeCall(item, "getUnhappyChange", 0),
        ageDays = age,
        daysFresh = offAge,
        daysTotallyRotten = offAgeMax,
        freshnessStage = stage,
        hoursUntilStaleAtRoomTemperature = hoursUntilStale,
        hoursUntilRottenAtRoomTemperature = hoursUntilRotten,
        frozen = safeCall(item, "isFrozen", false),
        freezingTime = safeCall(item, "getFreezingTime", 0),
        meltingTime = safeCall(item, "getMeltingTime", 0),
        cooked = safeCall(item, "isCooked", false),
        burnt = safeCall(item, "isBurnt", false),
        rotten = rotten,
        cookable = safeCall(item, "isIsCookable", false),
        cookingTime = safeCall(item, "getCookingTime", 0),
        minutesToCook = safeCall(item, "getMinutesToCook", 0),
        minutesToBurn = safeCall(item, "getMinutesToBurn", 0),
        dangerousUncooked = safeCall(item, "isbDangerousUncooked", false),
        poisonous = safeCall(item, "isPoison", false),
        poisonPower = safeCall(item, "getPoisonPower", 0),
        foodType = toStringOrNil(safeCall(item, "getFoodType", nil)),
        evolvedRecipeName = toStringOrNil(safeCall(item, "getEvolvedRecipeName", nil)),
        replaceOnCooked = replaceOnCooked(item),
    }
end

local function weaponData(item)
    local maxAmmo = safeCall(item, "getMaxAmmo", 0)
    if maxAmmo <= 0 and not instanceof(item, "HandWeapon") then return nil end
    return {
        ammoType = ammoType(item),
        currentAmmoCount = safeCall(item, "getCurrentAmmoCount", 0),
        maxAmmo = maxAmmo,
        chambered = safeCall(item, "isRoundChambered", false),
        spentRoundChambered = safeCall(item, "isSpentRoundChambered", false),
        spentRoundCount = safeCall(item, "getSpentRoundCount", 0),
        containsMagazine = safeCall(item, "isContainsClip", false),
        magazineType = toStringOrNil(safeCall(item, "getMagazineType", nil)),
        jammed = safeCall(item, "isJammed", false),
    }
end

local scanItem

local function scanItems(container, path, equipment, storage, seen)
    local result = {}
    local items = safeCall(container, "getItems", nil)
    local count = safeCall(items, "size", 0)
    for index = 0, count - 1 do
        local item = safeCall(items, "get", nil, index)
        if item then
            result[#result + 1] = scanItem(item, path, equipment, storage, seen)
        end
    end
    table.sort(result, function(left, right)
        local leftId = tostring(left.itemId or "")
        local rightId = tostring(right.itemId or "")
        if left.fullType == right.fullType then return leftId < rightId end
        return tostring(left.fullType) < tostring(right.fullType)
    end)
    return result
end

scanItem = function(item, path, equipment, storage, seen)
    local id = tostring(safeCall(item, "getID", tostring(item)))
    if seen[id] then
        return {
            itemId = id,
            fullType = safeCall(item, "getFullType", "unknown"),
            cycleDetected = true,
        }
    end
    seen[id] = true

    local itemEquipment = equipment[id] or {}
    local result = {
        itemId = id,
        fullType = safeCall(item, "getFullType", "unknown"),
        nameLocalized = safeCall(item, "getDisplayName", safeCall(item, "getName", "unknown")),
        customName = safeCall(item, "isCustomName", false) and safeCall(item, "getName", nil) or nil,
        quantity = math.max(1, safeCall(item, "getCount", 1)),
        currentUses = safeCall(item, "getCurrentUses", 1),
        uses = safeCall(item, "getUses", 1),
        condition = safeCall(item, "getCondition", 0),
        conditionMax = safeCall(item, "getConditionMax", 0),
        weight = safeCall(item, "getWeight", 0),
        actualWeight = safeCall(item, "getActualWeight", 0),
        category = toStringOrNil(safeCall(item, "getCategory", nil)),
        displayCategory = toStringOrNil(safeCall(item, "getDisplayCategory", nil)),
        tags = tagsToArray(item),
        locationPath = path,
        storage = storage,
        equipped = itemEquipment.equipped or false,
        primaryHand = itemEquipment.primaryHand or false,
        secondaryHand = itemEquipment.secondaryHand or false,
        wornLocation = itemEquipment.wornLocation,
        attachedLocation = itemEquipment.attachedLocation,
        favorite = safeCall(item, "isFavorite", false),
        food = foodData(item),
        weapon = weaponData(item),
        replaceOnUse = toStringOrNil(safeCall(item, "getReplaceOnUseFullType", nil)),
    }

    if instanceof(item, "InventoryContainer") then
        local nested = safeCall(item, "getInventory", nil)
        local nestedPath = path .. "/" .. result.nameLocalized .. "#" .. id
        result.container = {
            type = toStringOrNil(safeCall(nested, "getType", nil)),
            capacity = safeCall(nested, "getCapacity", 0),
            weightReduction = safeCall(item, "getWeightReduction", 0),
            items = scanItems(nested, nestedPath, equipment, storage, seen),
        }
    end
    seen[id] = nil
    return result
end

local function squarePosition(container)
    local square = safeCall(container, "getSourceGrid", nil)
    if not square then
        local parent = safeCall(container, "getParent", nil)
        square = safeCall(parent, "getSquare", nil)
    end
    if not square then return nil end
    return {
        x = safeCall(square, "getX", 0),
        y = safeCall(square, "getY", 0),
        z = safeCall(square, "getZ", 0),
    }
end

local function containerIndex(container, parent)
    local count = safeCall(parent, "getContainerCount", 0)
    for index = 0, count - 1 do
        if safeCall(parent, "getContainerByIndex", nil, index) == container then
            return index
        end
    end
    return 0
end

local function containerIdentity(container)
    local position = squarePosition(container)
    local containerType = tostring(safeCall(container, "getType", "unknown"))
    local containingItem = safeCall(container, "getContainingItem", nil)
    if containingItem then
        return "item:" .. tostring(safeCall(containingItem, "getID", containingItem))
    end

    local vehicle = safeCall(container, "getVehicle", nil)
    if vehicle then
        local vehicleId = tostring(safeCall(vehicle, "getId", "unknown"))
        local part = safeCall(container, "getVehiclePart", nil)
        local partId = tostring(safeCall(part, "getId", containerType))
        return "vehicle:" .. vehicleId .. ":" .. partId
    end

    local parent = safeCall(container, "getParent", nil)
    local objectIndex = safeCall(parent, "getObjectIndex", -1)
    local index = containerIndex(container, parent)
    if position then
        return table.concat({
            "world", position.x, position.y, position.z,
            objectIndex, index, containerType,
        }, ":")
    end
    return "runtime:" .. tostring(container)
end

local function containerKind(container)
    if safeCall(container, "getContainingItem", nil) then return "portable" end
    if safeCall(container, "getVehicle", nil) then return "vehicle" end
    local containerType = tostring(safeCall(container, "getType", ""))
    if containerType == "inventorymale" or containerType == "inventoryfemale" then
        return "corpse"
    end
    if containerType == "floor" then return "ground" end
    return "stationary"
end

local function containingBase(position)
    if not position then return nil end
    for _, base in ipairs(Scanner.baseZones) do
        if position.z >= base.minZ and position.z <= base.maxZ then
            local dx = position.x - base.x
            local dy = position.y - base.y
            if dx * dx + dy * dy <= base.radius * base.radius then return base end
        end
    end
    return nil
end

local function ownedVehicleRecord(vehicle)
    if not vehicle then return nil end
    local id = tostring(safeCall(vehicle, "getId", ""))
    return Scanner.ownedVehicleById[id]
end

function Scanner.containerSnapshot(container, observation)
    if not container then return nil end
    local id = containerIdentity(container)
    local position = squarePosition(container)
    local typeName = tostring(safeCall(container, "getType", "unknown"))
    local localizedType = getTextOrNull("IGUI_ContainerTitle_" .. typeName) or typeName
    local customName = nil
    local parent = safeCall(container, "getParent", nil)
    -- Build 42.20.3 throws a Java NPE when getCustomName() is called on
    -- transient UI ItemContainers whose parent is nil. Do not call it at all.
    if parent then customName = safeCall(container, "getCustomName", nil) end
    local ownedByOpened = Scanner.openedContainerIds[id] == true
    local owningBase = containingBase(position)
    local ownedByBase = owningBase ~= nil
    local vehicle = safeCall(container, "getVehicle", nil)
    local vehicleRecord = ownedVehicleRecord(vehicle)
    local ownedByVehicle = vehicleRecord ~= nil
    local storage = {
        containerId = id,
        containerName = customName or localizedType,
        kind = containerKind(container),
        refrigerator = safeCall(container, "isFridge", false),
        freezer = safeCall(container, "isFreezer", false),
        baseZoneId = owningBase and owningBase.id or nil,
        baseZoneName = owningBase and owningBase.name or nil,
        vehicleId = vehicleRecord and vehicleRecord.vehicleId or nil,
        vehicleName = vehicleRecord and vehicleRecord.name or nil,
    }
    local player = getPlayer()
    local equipment = player and equipmentMap(player) or {}
    return {
        containerId = id,
        kind = storage.kind,
        containerType = typeName,
        typeNameLocalized = localizedType,
        customName = customName,
        displayName = customName or localizedType,
        position = position,
        capacity = safeCall(container, "getCapacity", 0),
        explored = safeCall(container, "isExplored", false),
        hasBeenLooted = safeCall(container, "isHasBeenLooted", false),
        refrigerator = storage.refrigerator,
        freezer = storage.freezer,
        vehicleId = storage.vehicleId,
        vehicleName = storage.vehicleName,
        ownership = {
            owned = ownedByOpened or ownedByBase or ownedByVehicle,
            reason = ownedByVehicle and "registered_vehicle" or (ownedByBase and "inside_base" or (ownedByOpened and "opened_by_player" or "observed_only")),
            baseZoneId = owningBase and owningBase.id or nil,
            baseZoneName = owningBase and owningBase.name or nil,
            vehicleId = vehicleRecord and vehicleRecord.vehicleId or nil,
            vehicleName = vehicleRecord and vehicleRecord.name or nil,
        },
        observation = observation or "nearby",
        lastSeenWorldAgeHours = getGameTime():getWorldAgeHours(),
        items = scanItems(container, "container:" .. id, equipment, storage, {}),
    }
end

function Scanner.observeContainer(container, observation, opened)
    if not container then return nil end
    local containerType = tostring(safeCall(container, "getType", ""))
    if containerType == "floor" then return nil end
    local id = containerIdentity(container)
    if opened then Scanner.openedContainerIds[id] = true end
    local snapshot = Scanner.containerSnapshot(container, observation)
    Scanner.knownContainers[id] = snapshot
    Scanner.containerRefs[id] = container
    return snapshot
end

function Scanner.observeInventoryWindow(inventoryPage)
    if not inventoryPage or inventoryPage.onCharacter then return end
    for _, button in ipairs(inventoryPage.backpacks or {}) do
        Scanner.observeContainer(button.inventory, "nearby_inventory_window", false)
    end
end

function Scanner.observeSelectedContainer(forceRefresh)
    local player = getPlayer()
    if not player then return nil end
    local loot = getPlayerLoot(player:getPlayerNum())
    if not loot or not loot.inventoryPane then return nil end
    local container = loot.inventoryPane.inventory
    if not container then return nil end
    local parent = safeCall(container, "getParent", nil)
    if parent == player then return nil end
    local containerType = tostring(safeCall(container, "getType", ""))
    if containerType == "floor" then return nil end
    local id = containerIdentity(container)
    local isNewSelection = id ~= Scanner.lastSelectedContainerId
    if not isNewSelection and not forceRefresh then return nil end
    local snapshot = Scanner.observeContainer(container, "selected_by_player", true)
    if isNewSelection then
        Scanner.lastSelectedContainerId = id
        return {
            type = "container_opened",
            worldAgeHours = getGameTime():getWorldAgeHours(),
            container = snapshot,
        }
    end
    return nil
end

local function scanObjectContainers(object, observation)
    local count = safeCall(object, "getContainerCount", 0)
    for index = 0, count - 1 do
        Scanner.observeContainer(safeCall(object, "getContainerByIndex", nil, index), observation, false)
    end
    local direct = safeCall(object, "getContainer", nil)
    if count == 0 and direct then
        Scanner.observeContainer(direct, observation, false)
    end
end

function Scanner.setBaseZones(zones)
    Scanner.baseZones = zones or {}
    Scanner.baseIndexesBuilt = {}
end

function Scanner.setOwnedVehicles(records)
    Scanner.ownedVehicles = records or {}
    Scanner.ownedVehicleById = {}
    for _, record in ipairs(Scanner.ownedVehicles) do
        Scanner.ownedVehicleById[tostring(record.vehicleId)] = record
    end
end

function Scanner.isPlayerNearBase(base, padding)
    local player = getPlayer()
    if not base or not player then return false end
    local dx = player:getX() - base.x
    local dy = player:getY() - base.y
    local radius = base.radius + math.max(0, tonumber(padding) or 0)
    return dx * dx + dy * dy <= radius * radius
end

function Scanner.refreshKnownContainers()
    local refreshed = 0
    for id, container in pairs(Scanner.containerRefs) do
        local ok, snapshot = pcall(Scanner.containerSnapshot, container, "save_boundary_refresh")
        if ok and snapshot then
            Scanner.knownContainers[id] = snapshot
            refreshed = refreshed + 1
        end
    end
    return refreshed
end

function Scanner.refreshKnownBaseContainers()
    if #Scanner.baseZones == 0 then return 0 end
    local refreshed = 0
    for id, container in pairs(Scanner.containerRefs) do
        local position = squarePosition(container)
        if containingBase(position) then
            local ok, snapshot = pcall(Scanner.containerSnapshot, container, "base_save_refresh")
            if ok and snapshot then
                Scanner.knownContainers[id] = snapshot
                refreshed = refreshed + 1
            end
        end
    end
    return refreshed
end

function Scanner.scanBaseLoadedSquares(zoneId)
    local cell = getCell()
    if not cell then return 0 end
    local scanned = 0
    for _, base in ipairs(Scanner.baseZones) do
        local selected = not zoneId or base.id == zoneId
        local alreadyBuilt = Scanner.baseIndexesBuilt[base.id] == true
        if selected and not alreadyBuilt and Scanner.isPlayerNearBase(base, 15) then
            for x = base.x - base.radius, base.x + base.radius do
                for y = base.y - base.radius, base.y + base.radius do
                    local dx = x - base.x
                    local dy = y - base.y
                    if dx * dx + dy * dy <= base.radius * base.radius then
                        for z = base.minZ, base.maxZ do
                            local square = cell:getGridSquare(x, y, z)
                            if square then
                                scanned = scanned + 1
                                local objects = square:getObjects()
                                for index = 0, objects:size() - 1 do
                                    scanObjectContainers(objects:get(index), "loaded_base_zone")
                                end
                                local staticObjects = square:getStaticMovingObjects()
                                for index = 0, staticObjects:size() - 1 do
                                    scanObjectContainers(staticObjects:get(index), "loaded_base_zone")
                                end
                            end
                        end
                    end
                end
            end
            Scanner.baseIndexesBuilt[base.id] = true
        end
    end
    return scanned
end

local function localizedVehicleName(vehicle)
    local script = safeCall(vehicle, "getScript", nil)
    local scriptName = tostring(safeCall(script, "getName", "unknown"))
    local modelName = tostring(safeCall(script, "getCarModelName", scriptName))
    return getTextOrNull("IGUI_VehicleName" .. modelName)
        or getTextOrNull("IGUI_VehicleName" .. scriptName)
        or modelName
end

local function vehiclePartSnapshot(part)
    local partId = tostring(safeCall(part, "getId", "unknown"))
    local category = tostring(safeCall(part, "getCategory", "Other"))
    local item = safeCall(part, "getInventoryItem", nil)
    local itemTypes = safeCall(part, "getItemType", nil)
    local requiresInstalledItem = itemTypes ~= nil and not safeCall(itemTypes, "isEmpty", true)
    local amount = safeCall(part, "getContainerContentAmount", 0)
    local capacity = safeCall(part, "getContainerCapacity", 0)
    local content = nil
    if partId == "GasTank" or amount ~= 0 or capacity ~= 0 then
        content = {
            amount = amount,
            capacity = capacity,
            fraction = capacity > 0 and amount / capacity or nil,
            contentType = toStringOrNil(safeCall(part, "getContainerContentType", nil)),
        }
    end
    local installedItem = nil
    if item then
        installedItem = {
            itemId = tostring(safeCall(item, "getID", item)),
            fullType = tostring(safeCall(item, "getFullType", "unknown")),
            nameLocalized = tostring(safeCall(item, "getDisplayName", safeCall(item, "getName", "unknown"))),
            condition = safeCall(item, "getCondition", nil),
            conditionMax = safeCall(item, "getConditionMax", nil),
            remainingFraction = safeCall(item, "getCurrentUsesFloat", nil),
        }
    end
    return {
        partId = partId,
        nameLocalized = getTextOrNull("IGUI_VehiclePart" .. partId) or partId,
        category = category,
        categoryLocalized = getTextOrNull("IGUI_VehiclePartCat" .. category) or category,
        condition = safeCall(part, "getCondition", 0),
        requiresInstalledItem = requiresInstalledItem,
        installed = (not requiresInstalledItem) or item ~= nil,
        installedItem = installedItem,
        content = content,
    }
end

function Scanner.vehicleSnapshot(vehicle, observation)
    local record = ownedVehicleRecord(vehicle)
    if not record then return nil end
    local id = tostring(safeCall(vehicle, "getId", record.vehicleId))
    local script = safeCall(vehicle, "getScript", nil)
    local parts = {}
    local containers = {}
    local conditionTotal = 0
    local conditionCount = 0
    local partCount = safeCall(vehicle, "getPartCount", 0)
    for index = 0, partCount - 1 do
        local part = safeCall(vehicle, "getPartByIndex", nil, index)
        if part then
            local category = tostring(safeCall(part, "getCategory", "Other"))
            if category ~= "nodisplay" then
                local partSnapshot = vehiclePartSnapshot(part)
                parts[#parts + 1] = partSnapshot
                conditionTotal = conditionTotal + (tonumber(partSnapshot.condition) or 0)
                conditionCount = conditionCount + 1
            end
            local container = safeCall(part, "getItemContainer", nil)
            if container then
                local snapshot = Scanner.containerSnapshot(container, observation or "registered_vehicle")
                if snapshot then containers[#containers + 1] = snapshot end
            end
        end
    end
    table.sort(parts, function(left, right) return tostring(left.partId) < tostring(right.partId) end)
    table.sort(containers, function(left, right)
        return tostring(left.containerId) < tostring(right.containerId)
    end)

    local gasTank = safeCall(vehicle, "getPartById", nil, "GasTank")
    local fuelAmount = safeCall(gasTank, "getContainerContentAmount", 0)
    local fuelCapacity = safeCall(gasTank, "getContainerCapacity", 0)
    local position = {
        x = safeCall(vehicle, "getX", record.x or 0),
        y = safeCall(vehicle, "getY", record.y or 0),
        z = safeCall(vehicle, "getZ", record.z or 0),
    }
    record.x, record.y, record.z = position.x, position.y, position.z
    return {
        vehicleId = id,
        keyId = safeCall(vehicle, "getKeyId", record.keyId),
        name = record.name,
        displayName = localizedVehicleName(vehicle),
        scriptFullType = tostring(safeCall(script, "getFullType", record.scriptFullType or "unknown")),
        scriptName = tostring(safeCall(script, "getName", record.scriptName or "unknown")),
        position = position,
        ownership = {
            owned = true,
            reason = "registered_with_matching_key",
            confidence = "exact",
        },
        observation = observation or "registered_vehicle",
        lastSeenWorldAgeHours = getGameTime():getWorldAgeHours(),
        fuel = {
            amount = fuelAmount,
            capacity = fuelCapacity,
            fraction = fuelCapacity > 0 and fuelAmount / fuelCapacity or nil,
        },
        batteryCharge = safeCall(vehicle, "getBatteryCharge", nil),
        overallCondition = conditionCount > 0 and conditionTotal / conditionCount or nil,
        engine = {
            quality = safeCall(vehicle, "getEngineQuality", nil),
            power = safeCall(vehicle, "getEnginePower", nil),
            loudness = safeCall(vehicle, "getEngineLoudness", nil),
            running = safeCall(vehicle, "isEngineRunning", false),
            working = safeCall(vehicle, "isEngineWorking", false),
        },
        hotwired = safeCall(vehicle, "isHotwired", false),
        keyInIgnition = safeCall(vehicle, "isKeysInIgnition", false),
        mass = safeCall(vehicle, "getMass", nil),
        parts = parts,
        containers = containers,
    }
end

function Scanner.observeVehicle(vehicle, observation)
    local snapshot = Scanner.vehicleSnapshot(vehicle, observation)
    if not snapshot then return nil end
    Scanner.knownVehicles[tostring(snapshot.vehicleId)] = snapshot
    Scanner.vehicleRefs[tostring(snapshot.vehicleId)] = vehicle
    return snapshot
end

function Scanner.refreshOwnedVehicles()
    local cell = getCell()
    if not cell then return 0 end
    local vehicles = safeCall(cell, "getVehicles", nil)
    local count = safeCall(vehicles, "size", 0)
    local refreshed = 0
    for index = 0, count - 1 do
        local vehicle = safeCall(vehicles, "get", nil, index)
        if vehicle and ownedVehicleRecord(vehicle) then
            local ok, snapshot = pcall(Scanner.observeVehicle, vehicle, "registered_vehicle_refresh")
            if ok and snapshot then refreshed = refreshed + 1 end
        end
    end
    return refreshed
end
local function characterSnapshot(player)

    local descriptor = safeCall(player, "getDescriptor", nil)
    local firstName = safeCall(descriptor, "getForename", "")
    local lastName = safeCall(descriptor, "getSurname", "")
    local equipment = equipmentMap(player)
    local storage = {
        containerId = "player:inventory",
        containerName = "Character inventory",
        kind = "player",
        refrigerator = false,
        freezer = false,
    }
    return {
        name = (firstName .. " " .. lastName):gsub("^%s+", ""):gsub("%s+$", ""),
        forename = firstName,
        surname = lastName,
        dead = safeCall(player, "isDead", false),
        position = {
            x = player:getX(),
            y = player:getY(),
            z = player:getZ(),
        },
        carryingWeight = safeCall(player, "getInventoryWeight", 0),
        maxWeight = safeCall(player, "getMaxWeight", 0),
        inventory = {
            containerId = "player:inventory",
            items = scanItems(player:getInventory(), "player.inventory", equipment, storage, {}),
        },
    }
end

function Scanner.currentState()
    local player = getPlayer()
    if not player then error("no active player") end
    local containers = {}
    for _, container in pairs(Scanner.knownContainers) do
        local registeredVehicleContainer = container.kind == "vehicle"
            and Scanner.ownedVehicleById[tostring(container.vehicleId or "")] ~= nil
        if not registeredVehicleContainer then containers[#containers + 1] = container end
    end
    local vehicles = {}
    for id, vehicle in pairs(Scanner.knownVehicles) do
        if Scanner.ownedVehicleById[tostring(id)] then vehicles[#vehicles + 1] = vehicle end
    end
    table.sort(containers, function(left, right)
        return tostring(left.containerId) < tostring(right.containerId)
    end)
    table.sort(vehicles, function(left, right)
        return tostring(left.vehicleId) < tostring(right.vehicleId)
    end)

    local world = getWorld()
    local worldName = world and safeCall(world, "getWorld", "unknown") or "unknown"
    local gameMode = world and safeCall(world, "getGameMode", "unknown") or "unknown"
    local baseZones = Scanner.baseZones
    local baseLoadedSquaresScanned = false
    for _, built in pairs(Scanner.baseIndexesBuilt) do
        if built then
            baseLoadedSquaresScanned = true
            break
        end
    end

    return {
        schema = "pz-monitoring-bot/mod-snapshot/v1",
        schemaVersion = "0.4.0",
        source = { kind = "in_game_mod", readOnly = true },
        game = {
            build = toStringOrNil(safeCall(getCore(), "getVersionNumber", nil)),
            worldAgeHours = getGameTime():getWorldAgeHours(),
        },
        save = {
            id = tostring(gameMode) .. ":" .. tostring(worldName),
            name = tostring(worldName),
            gameMode = tostring(gameMode),
        },
        character = characterSnapshot(player),
        baseZones = baseZones,
        ownedVehicles = Scanner.ownedVehicles,
        world = {
            containers = containers,
            vehicles = vehicles,
            coverage = {
                runtimeLoadedOnly = true,
                registeredVehiclesConfigured = #Scanner.ownedVehicles,
                registeredVehiclesLoaded = #vehicles,
                openedContainersRememberedThisSession = true,
                baseLoadedSquaresScanned = baseLoadedSquaresScanned,
                configuredBaseCount = #Scanner.baseZones,
                unloadedRemoteContainersComplete = false,
            },
        },
    }
end

return Scanner
