require "PZMonitoringBot/PZMB_Json"
require "PZMonitoringBot/PZMB_Scanner"
require "PZMonitoringBot/PZMB_Config"
require "PZMonitoringBot/PZMB_Vehicles"
require "PZMonitoringBot/PZMB_Export"
require "PZMonitoringBot/PZMB_UI"

PZMB = PZMB or {}
PZMB.Runtime = PZMB.Runtime or {}

local Runtime = PZMB.Runtime

local function onGameStart()
    PZMB.Config.load()
    PZMB.Config.applyCurrentSave()
    PZMB.Vehicles.load()
end

-- Performance contract: never poll, scan or serialize telemetry in the
-- background. A complete snapshot can contain thousands of item records and
-- must only be produced by an explicit Organizer action in PZMB_UI.
Events.OnGameStart.Add(onGameStart)

return Runtime