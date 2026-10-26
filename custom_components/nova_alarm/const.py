"""Constants for the experimental AVS integration."""

DOMAIN = "nova_alarm"
NAME = "Nova Alarm"
VERSION = "0.5.0"
CONF_KEEP_SESSION = "keep_session"
CONF_AUTOMATIC_UPDATES = "automatic_updates"
CONF_REQUIRE_COMMAND_PIN = "require_command_pin"
CONF_ENABLED_MODES = "enabled_modes"
DEFAULT_ENABLED_MODES = ["ON", "HO", "AR", "PE"]
CONF_PLANT_ID = "plant_id"
CONF_PLANT_NAME = "plant_name"
CONF_DEVICE_ID = "device_id"
CONF_PIN = "pin"
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 600

# These are the AVS mode labels, not inferred HA home/away equivalents.
AVS_MODES = {0: "ON", 1: "HO", 2: "AR", 3: "PE", 4: "OFF"}

# Defaults can be changed in the integration options to match the installation.
DEFAULT_MODE_MAP = {
    "mode_on": "armed_away",
    "mode_ho": "armed_home",
    "mode_ar": "armed_custom_bypass",
    "mode_pe": "armed_night",
}
