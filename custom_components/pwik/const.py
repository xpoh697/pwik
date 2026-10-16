"""Constants for the PWiK Piaseczno iBOK integration."""

DOMAIN = "pwik"

# URLs
BASE_URL = "https://ibok.pwikpiaseczno.pl"
URL_LOGIN = f"{BASE_URL}/?"
URL_KILL_SESSION = f"{BASE_URL}/?logout=true&kill=true"
URL_NOTIFY_READOUT = f"{BASE_URL}/?module=NotifyReadout_v1"
URL_ADD_READOUT = f"{BASE_URL}/?module=NotifyReadout_v1&action=add"
URL_REMOVE_READOUT = f"{BASE_URL}/?module=NotifyReadout_v1&action=remove"
URL_READOUTS_HISTORY = f"{BASE_URL}/?module=Readouts_v1"
URL_ERRORS = f"{BASE_URL}/?module=Errors"

# Config & Options
CONF_SOURCE_SENSORS = "source_sensors"
CONF_UPDATE_INTERVAL = "update_interval"
DEFAULT_UPDATE_INTERVAL = 7200  # 2 hours

# Meter Types
METER_TYPE_MAIN = "N"  # Nieruchomość (Główny)
METER_TYPE_SUB = "P"   # Podlicznik (Ogród / Podlicznik)

# Submission Statuses
STATUS_PENDING = "pending"          # ist == 1: Oczekujące
STATUS_IN_PROGRESS = "in_progress"  # ist == 2: W trakcie realizacji
STATUS_REJECTED = "rejected"        # ist == 3: Odrzucony
STATUS_APPROVED = "approved"        # ist == 4: Zatwierdzony (окно открыто)
