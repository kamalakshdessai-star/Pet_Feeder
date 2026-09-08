"""
actuators.py
Controls the three physical actuators on the feeder:
  - Servo valve: gates the dry food chute open/closed
  - Pump (relay-driven): dispenses water
  - DC actuator: drives the flush/auger mechanism used to clear jams
    and settle food after a dispense

The original prototype (rpi_integrated.py) drove the pump and flush relays
directly with fixed time.sleep() calls and no feedback, so it could not
tell whether a feed actually happened or diagnose a stuck valve. This
module adds a PWM-driven servo, converts the water/flush routines into
reusable functions, and adds a watchdog timeout so one stuck actuator
can't block the whole feed cycle -- the "resolution of multi-actuator
timing and synchronization" the resume describes.
"""

import time
import RPi.GPIO as GPIO
import config


class ActuatorController:
    def __init__(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(config.SERVO_PIN, GPIO.OUT)
        GPIO.setup(config.PUMP_RELAY_PIN, GPIO.OUT)
        GPIO.setup(config.PUMP_DIR_PIN, GPIO.OUT)
        GPIO.setup(config.DC_ACTUATOR_PIN_A, GPIO.OUT)
        GPIO.setup(config.DC_ACTUATOR_PIN_B, GPIO.OUT)

        self._servo_pwm = GPIO.PWM(config.SERVO_PIN, config.SERVO_FREQ_HZ)
        self._servo_pwm.start(self._angle_to_duty(config.SERVO_CLOSED_ANGLE))

        self._all_off()

    # -- low level ----------------------------------------------------
    def _all_off(self):
        GPIO.output(config.PUMP_RELAY_PIN, GPIO.LOW)
        GPIO.output(config.PUMP_DIR_PIN, GPIO.LOW)
        GPIO.output(config.DC_ACTUATOR_PIN_A, GPIO.LOW)
        GPIO.output(config.DC_ACTUATOR_PIN_B, GPIO.LOW)

    @staticmethod
    def _angle_to_duty(angle):
        # 50Hz servo: 2%-12% duty maps roughly to 0-180 degrees
        return 2 + (angle / 18.0)

    # -- servo (food gate) ---------------------------------------------
    def open_food_gate(self, hold_s=1.5):
        self._servo_pwm.ChangeDutyCycle(self._angle_to_duty(config.SERVO_OPEN_ANGLE))
        time.sleep(hold_s)

    def close_food_gate(self):
        self._servo_pwm.ChangeDutyCycle(self._angle_to_duty(config.SERVO_CLOSED_ANGLE))
        time.sleep(0.3)
        # stop sending pulses once settled so the servo doesn't buzz/jitter
        self._servo_pwm.ChangeDutyCycle(0)

    # -- pump (water) ----------------------------------------------------
    def dispense_water(self, duration_s=None):
        duration_s = duration_s or config.WATER_DISPENSE_S
        GPIO.output(config.PUMP_RELAY_PIN, GPIO.HIGH)
        GPIO.output(config.PUMP_DIR_PIN, GPIO.LOW)
        time.sleep(duration_s)
        GPIO.output(config.PUMP_RELAY_PIN, GPIO.LOW)

    # -- DC actuator (flush / anti-jam) -----------------------------------
    def flush(self, duration_s=None):
        duration_s = duration_s or config.FLUSH_DURATION_S
        GPIO.output(config.DC_ACTUATOR_PIN_A, GPIO.HIGH)
        GPIO.output(config.DC_ACTUATOR_PIN_B, GPIO.LOW)
        time.sleep(duration_s)
        GPIO.output(config.DC_ACTUATOR_PIN_A, GPIO.LOW)
        GPIO.output(config.DC_ACTUATOR_PIN_B, GPIO.LOW)

    # -- synchronized sequence -------------------------------------------
    def run_feed_sequence(self, load_cells, portion_target_g, timeout_s=None):
        """Runs one full, synchronized feed cycle:
             1. tare the portion cell
             2. open the food gate until target weight is reached or timeout
             3. close the gate
             4. cross-check against the error-detection cell
             5. run the flush actuator briefly to clear the chute
        Returns a dict describing what happened, used for the missed-feed /
        fault-alert logic and for the telemetry sent to the app.
        """
        timeout_s = timeout_s or config.FEED_TIMEOUT_S
        result = {"success": False, "dispensed_g": 0.0, "fault": None}
        start = time.time()

        load_cells.cells["portion"].tare()
        self.open_food_gate(hold_s=0.1)

        try:
            while time.time() - start < timeout_s:
                grams = load_cells.cells["portion"].get_weight_grams()
                if grams is not None and grams >= portion_target_g - config.PORTION_WEIGHT_TOLERANCE_G:
                    result["dispensed_g"] = grams
                    result["success"] = True
                    break
                time.sleep(0.1)
            else:
                result["fault"] = "timeout_before_target_weight"
        finally:
            self.close_food_gate()

        ok, detail = load_cells.check_portion_error()
        result["error_check"] = detail
        if not ok:
            result["fault"] = result["fault"] or "portion_error_mismatch"

        self.flush(duration_s=2.0)  # short clear-out, not a full flush cycle
        result["elapsed_s"] = round(time.time() - start, 2)
        return result

    def cleanup(self):
        self._servo_pwm.stop()
        self._all_off()
