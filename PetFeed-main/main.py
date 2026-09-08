"""
main.py
Entry point for the PowerPet smart feeder. Integrates:
  - 3x HX711 load cells (loadcell.py)
  - Servo/pump/DC actuator control (actuators.py)
  - CV/ML feeding-detection model (feeding_detector.py)
  - Flask API consumed by the PowerPet MIT App Inventor app

This replaces the earlier prototype (rpi_integrated.py), which only
controlled the water pump/flush relays directly and had no load-cell or
camera integration. The HTTP contract below (GET/POST /get_message) is
kept backward compatible with that prototype's JSON shape so the existing
App Inventor blocks project continues to work against this server without
changes on the app side.
"""

import threading
import time
import sqlite3
from datetime import datetime

from flask import Flask, request, jsonify

import config
from loadcell import LoadCellArray
from actuators import ActuatorController
from feeding_detector import FeedingDetector

app = Flask(__name__)

load_cells = None
actuators = None
detector = None

state_lock = threading.Lock()
latest_data = {
    "device_id": config.DEVICE_ID,
    "battery_status": "OK",
    "feed_left": "200",
    "water_left": "400",
    "feed_ack": "Idle",
}
feeding_schedule = []   # list of [hour, minute, portion_grams]
triggered_times = set()


def init_db():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feed_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            portion_target_g REAL,
            portion_dispensed_g REAL,
            success INTEGER,
            fault TEXT,
            missed_feed INTEGER
        )
    """)
    conn.commit()
    conn.close()


def log_feed_event(feed_result, missed_feed=None):
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute(
        "INSERT INTO feed_events (timestamp, portion_target_g, portion_dispensed_g, "
        "success, fault, missed_feed) VALUES (?, ?, ?, ?, ?, ?)",
        (
            datetime.now().isoformat(),
            feed_result.get("target_g"),
            feed_result.get("dispensed_g"),
            int(feed_result.get("success", False)),
            feed_result.get("fault"),
            int(missed_feed) if missed_feed is not None else None,
        ),
    )
    conn.commit()
    conn.close()


def run_scheduled_feed(portion_g):
    """Runs one full feed cycle, updates telemetry, and kicks off a
    background missed-feed check via the CV/ML model."""
    global latest_data

    result = actuators.run_feed_sequence(load_cells, portion_target_g=portion_g)
    result["target_g"] = portion_g

    with state_lock:
        latest_data["feed_ack"] = "Completed" if result["success"] else f"Fault: {result['fault']}"
        feed_left = max(int(float(latest_data.get("feed_left", 0))) - int(portion_g), 0)
        latest_data["feed_left"] = str(feed_left)

    log_feed_event(result)

    # Give water alongside the dry feed, matching the original prototype's
    # give-water-then-flush behavior.
    actuators.dispense_water()
    with state_lock:
        water_left = max(int(float(latest_data.get("water_left", 0))) - 50, 0)
        latest_data["water_left"] = str(water_left)

    # Missed-feed check runs in its own thread so it doesn't block the
    # scheduler loop while it samples the camera for a couple minutes.
    def _check_missed():
        outcome = detector.watch_for_missed_feed(
            check_duration_s=config.MISSED_FEED_CHECK_DELAY_S
        )
        log_feed_event(result, missed_feed=outcome["missed"])
        if outcome["missed"]:
            with state_lock:
                latest_data["feed_ack"] = "Missed feed detected"

    threading.Thread(target=_check_missed, daemon=True).start()


def monitor_schedule():
    global triggered_times
    while True:
        now = datetime.now()
        current_time = (now.hour, now.minute)

        for schedule in feeding_schedule:
            hour, minute, portion_g = schedule
            if (hour, minute) == current_time and (hour, minute) not in triggered_times:
                print(f"Feeding time triggered: {hour}:{minute} ({portion_g}g)")
                run_scheduled_feed(portion_g)
                triggered_times.add((hour, minute))

        if now.second == 59:
            triggered_times.clear()
        time.sleep(1)


# ---------------------------------------------------------------------------
# API consumed by the PowerPet MIT App Inventor app
# ---------------------------------------------------------------------------
@app.route("/get_message", methods=["GET", "POST"])
def get_message():
    """
    GET  -> returns current telemetry (battery, feed/water levels, last
            feed acknowledgement) as JSON, polled by the app.
    POST -> body is a comma-separated schedule string in the same format
            the original prototype used: "[H:7;M:30],[H:18;M:0]"
            Optionally each entry can include a portion in grams:
            "[H:7;M:30;G:40],[H:18;M:0;G:40]" (defaults to 40g if omitted).
    """
    global feeding_schedule

    if request.method == "GET":
        with state_lock:
            return jsonify(latest_data), 200

    try:
        data = request.data.decode("utf-8")
        new_schedule = []
        for entry in data.split(","):
            entry = entry.strip()
            if not (entry.startswith("[H:") and entry.endswith("]")):
                continue
            parts = entry.strip("[]").split(";")
            hour = int(parts[0].split(":")[1])
            minute = int(parts[1].split(":")[1])
            grams = int(parts[2].split(":")[1]) if len(parts) > 2 else 40
            new_schedule.append([hour, minute, grams])

        feeding_schedule = new_schedule
        return jsonify({"message": "Schedule updated", "schedule": feeding_schedule}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/feed_now", methods=["POST"])
def feed_now():
    """Manual on-demand feed trigger, e.g. from an app button."""
    grams = int(request.args.get("grams", 40))
    threading.Thread(target=run_scheduled_feed, args=(grams,), daemon=True).start()
    return jsonify({"message": "Feed triggered", "grams": grams}), 200


@app.route("/history", methods=["GET"])
def history():
    """Returns recent feed events for the app's report/history view."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM feed_events ORDER BY id DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows]), 200


def main():
    global load_cells, actuators, detector

    init_db()
    load_cells = LoadCellArray(
        config.LOADCELL_PINS, config.REFERENCE_UNIT, config.ERROR_CELL_TOLERANCE_G
    )
    load_cells.tare_all()
    actuators = ActuatorController()
    detector = FeedingDetector()

    threading.Thread(target=monitor_schedule, daemon=True).start()

    try:
        app.run(host=config.API_HOST, port=config.API_PORT)
    finally:
        actuators.cleanup()
        load_cells.cleanup()
        detector.release()


if __name__ == "__main__":
    main()
