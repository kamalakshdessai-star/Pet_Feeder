"""
loadcell.py
Driver for the HX711 load-cell amplifier, refactored to support running
three independent load cells at once (portion, flow, error-detection),
each on its own DT/SCK GPIO pair.

This replaces the original single-cell prototype script. The bit-banged
read protocol (24 clock pulses + 1 gain pulse, two's-complement decode)
is unchanged from the original prototype; it has just been wrapped in a
class so multiple cells can be instantiated side by side and so a stuck
sensor can't hang the whole process.
"""

import time
import statistics
import RPi.GPIO as GPIO


class HX711:
    def __init__(self, dt_pin, sck_pin, reference_unit=1.0, name="cell"):
        self.dt = dt_pin
        self.sck = sck_pin
        self.reference_unit = reference_unit
        self.name = name
        self.offset = 0.0

        GPIO.setup(self.sck, GPIO.OUT)
        GPIO.setup(self.dt, GPIO.IN)
        GPIO.output(self.sck, False)

    def _read_raw(self, timeout_s=1.0):
        """Read one 24-bit sample. Returns None instead of hanging forever
        if the chip doesn't respond (original script would block here)."""
        start = time.time()
        while GPIO.input(self.dt):
            if time.time() - start > timeout_s:
                return None
            time.sleep(0.0005)

        count = 0
        for _ in range(24):
            GPIO.output(self.sck, True)
            count = count << 1
            GPIO.output(self.sck, False)
            if GPIO.input(self.dt):
                count += 1

        # Gain-128 channel A: one extra pulse
        GPIO.output(self.sck, True)
        GPIO.output(self.sck, False)

        if count & 0x800000:
            count -= 0x1000000
        return count

    def read_average(self, samples=10, timeout_s=1.0):
        readings = []
        for _ in range(samples):
            r = self._read_raw(timeout_s=timeout_s)
            if r is not None:
                readings.append(r)
        if not readings:
            return None
        # median instead of mean: rejects single-sample glitches, which
        # the original averaging approach did not handle
        return statistics.median(readings)

    def tare(self, samples=10):
        avg = self.read_average(samples=samples)
        if avg is not None:
            self.offset = avg
        return self.offset

    def get_weight_grams(self, samples=5):
        raw = self.read_average(samples=samples)
        if raw is None:
            return None
        return (raw - self.offset) / self.reference_unit


class LoadCellArray:
    """Owns all three HX711 instances (portion / flow / error) and provides
    the cross-check logic the resume calls out: comparing the portion cell
    reading against the error-detection cell to catch jams or double-feeds."""

    def __init__(self, pin_map, reference_units, error_tolerance_g=5.0):
        GPIO.setmode(GPIO.BCM)
        self.cells = {}
        for name, pins in pin_map.items():
            self.cells[name] = HX711(
                dt_pin=pins["dt"],
                sck_pin=pins["sck"],
                reference_unit=reference_units.get(name, 1.0),
                name=name,
            )
        self.error_tolerance_g = error_tolerance_g

    def tare_all(self):
        return {name: cell.tare() for name, cell in self.cells.items()}

    def read_all_grams(self):
        return {name: cell.get_weight_grams() for name, cell in self.cells.items()}

    def check_portion_error(self):
        """Returns (ok: bool, detail: dict). Flags a fault when the portion
        cell and error cell disagree by more than tolerance, which usually
        means a jam, a double-dispense, or a cell that lost calibration."""
        weights = self.read_all_grams()
        portion = weights.get("portion")
        error_cell = weights.get("error")
        if portion is None or error_cell is None:
            return False, {"reason": "sensor_timeout", "weights": weights}

        delta = abs(portion - error_cell)
        ok = delta <= self.error_tolerance_g
        return ok, {"delta_g": delta, "weights": weights}

    def cleanup(self):
        GPIO.cleanup()


if __name__ == "__main__":
    # Standalone manual test / calibration helper, run as:
    #   python3 loadcell.py
    import config

    array = LoadCellArray(
        config.LOADCELL_PINS, config.REFERENCE_UNIT, config.ERROR_CELL_TOLERANCE_G
    )
    print("Taring all cells (ensure no weight is on any cell)...")
    time.sleep(2)
    array.tare_all()
    print("Tare complete. Reading weights, Ctrl+C to stop.")
    try:
        while True:
            print(array.read_all_grams())
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        array.cleanup()
