import RPi.GPIO as GPIO
import time

# Define GPIO pins for HX711
DT = 20  # Data pin
SCK = 21  # Clock pin

# GPIO setup
GPIO.setmode(GPIO.BCM)
GPIO.setup(SCK, GPIO.OUT)
GPIO.setup(DT, GPIO.IN)

def read_raw_data():
    """Read raw data from the HX711."""
    count = 0
    while GPIO.input(DT):  # Wait until DT goes low
        pass
    for _ in range(24):  # Read 24 bits
        GPIO.output(SCK, True)
        count = count << 1
        GPIO.output(SCK, False)
        if GPIO.input(DT):
            count += 1
    # Set the gain (1 additional pulse to SCK)
    GPIO.output(SCK, True)
    GPIO.output(SCK, False)

    # Convert to signed integer
    if count & 0x800000:  # Check if the 24th bit is 1 (negative value)
        count -= 0x1000000
    return count

def calibrate():
    """Calibrate the scale by taking an average of raw data when no weight is applied."""
    print("Calibrating... Please ensure no weight is on the scale.")
    time.sleep(2)
    readings = [read_raw_data() for _ in range(10)]
    return sum(readings) / len(readings)

def get_weight(reference_unit, offset):
    """Get the weight in kilograms."""
    raw_value = read_raw_data()
    weight = (raw_value - offset) / reference_unit
    return weight

try:
    # Calibrate the scale
    offset = calibrate()
    print("Calibration complete!")
    reference_unit = float(input("Enter the reference unit (calibration factor): "))

    print("Place weight on the scale...")
    last_tare_time = time.time()

    while True:
        # Get the current weight
        weight = get_weight(reference_unit, offset)
        print(f"Weight: {weight:.2f} kg")

        # Recalibrate every 5 seconds
        if time.time() - last_tare_time >= 5:
            print("Recalibrating to correct drift...")
            offset = calibrate()
            last_tare_time = time.time()

        time.sleep(0.5)

except KeyboardInterrupt:
    print("Exiting...")
finally:
    GPIO.cleanup()
