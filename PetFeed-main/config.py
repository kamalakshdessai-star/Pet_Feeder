"""
config.py
Central place for every GPIO pin assignment and tunable constant used by the
PowerPet smart feeder. Change wiring here, not inside the logic modules.
"""

# ---------------------------------------------------------------------------
# Load cells (3x HX711) -> portion cell, flow cell, error-detection cell
# ---------------------------------------------------------------------------
LOADCELL_PINS = {
    "portion": {"dt": 20, "sck": 21},   # measures food dispensed per feed
    "flow":    {"dt": 16, "sck": 12},   # measures water flow / bowl weight
    "error":   {"dt": 19, "sck": 13},   # secondary cell used to cross-check
}

# Calibration factors (raw HX711 units per gram). These are placeholders —
# run `python3 calibrate.py <cell_name>` to generate real values for your
# hardware, then paste the printed numbers in here.
REFERENCE_UNIT = {
    "portion": 420.0,
    "flow": 420.0,
    "error": 420.0,
}

# Max allowed disagreement between the portion cell and the error cell
# before a feed is flagged as a hardware fault (grams).
ERROR_CELL_TOLERANCE_G = 5.0

# ---------------------------------------------------------------------------
# Actuators: servo valve (food gate), pump (water), DC actuator (flush/mix)
# ---------------------------------------------------------------------------
SERVO_PIN = 18          # PWM-capable pin, controls the food gate servo
PUMP_RELAY_PIN = 1      # drives the water pump via relay
PUMP_DIR_PIN = 25       # relay/H-bridge direction pin for the pump circuit
DC_ACTUATOR_PIN_A = 7   # DC actuator (flush / auger) - forward
DC_ACTUATOR_PIN_B = 8   # DC actuator (flush / auger) - reverse

SERVO_CLOSED_ANGLE = 0
SERVO_OPEN_ANGLE = 70
SERVO_FREQ_HZ = 50

# Target portion accuracy from the resume claim: +/-60s timing window on
# whether a feed completed, not a weight tolerance. Weight tolerance below.
PORTION_WEIGHT_TOLERANCE_G = 3.0
FEED_TIMEOUT_S = 5          # end-to-end feed cycle must complete inside this
WATER_DISPENSE_S = 10
FLUSH_DURATION_S = 10

# ---------------------------------------------------------------------------
# Camera / CV feeding-detection model
# ---------------------------------------------------------------------------
CAMERA_INDEX = 0              # USB webcam index for cv2.VideoCapture
FRAME_WIDTH = 320
FRAME_HEIGHT = 240
CAPTURE_FPS = 5
MODEL_PATH = "ml_model/feeding_detector.tflite"
CLASS_NAMES = ["no_pet", "pet_not_eating", "pet_eating"]
MISSED_FEED_CHECK_DELAY_S = 300   # how long after a scheduled feed to check
MISSED_FEED_CONFIDENCE_THRESH = 0.6

# ---------------------------------------------------------------------------
# Flask API
# ---------------------------------------------------------------------------
API_HOST = "0.0.0.0"
API_PORT = 5000
DEVICE_ID = "PETFEEDER-001"   # used by the App Inventor app to pair a device

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
DB_PATH = "petfeed.db"
LOG_PATH = "petfeed.log"
