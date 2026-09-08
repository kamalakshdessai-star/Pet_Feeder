"""
calibrate.py
Run this once per load cell to find its reference_unit (raw HX711 counts
per gram), then paste the printed value into config.REFERENCE_UNIT.

Usage:
    python3 calibrate.py portion
    python3 calibrate.py flow
    python3 calibrate.py error
"""

import sys
import time
import RPi.GPIO as GPIO

import config
from loadcell import HX711


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in config.LOADCELL_PINS:
        print(f"Usage: python3 calibrate.py <{'|'.join(config.LOADCELL_PINS)}>")
        sys.exit(1)

    name = sys.argv[1]
    pins = config.LOADCELL_PINS[name]

    GPIO.setmode(GPIO.BCM)
    cell = HX711(pins["dt"], pins["sck"], reference_unit=1.0, name=name)

    print(f"Calibrating '{name}' cell. Remove all weight, then press Enter.")
    input()
    cell.tare(samples=15)
    print("Tare complete.")

    known_weight_g = float(input("Place a known weight on the cell and enter its mass in grams: "))
    time.sleep(1)
    raw = cell.read_average(samples=15)
    reference_unit = (raw - cell.offset) / known_weight_g

    print(f"\nreference_unit for '{name}' = {reference_unit:.4f}")
    print(f"Paste this into config.py -> REFERENCE_UNIT['{name}'] = {reference_unit:.4f}")

    GPIO.cleanup()


if __name__ == "__main__":
    main()
