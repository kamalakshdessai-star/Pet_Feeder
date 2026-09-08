"""
feeding_detector.py
Runs the trained TFLite feeding-detection model against the live USB webcam
feed on the Raspberry Pi, and generates missed-feed alerts when a scheduled
feed completed (per the load cells) but no "pet_eating" frame was observed
within the follow-up window.

Uses tflite-runtime (not full TensorFlow) since that is what actually fits
comfortably on a Pi for inference-only workloads.
"""

import time
import collections
import numpy as np
import cv2

try:
    from tflite_runtime.interpreter import Interpreter
except ImportError:
    # fallback for dev machines that only have full TensorFlow installed
    from tensorflow.lite.python.interpreter import Interpreter

import config


class FeedingDetector:
    def __init__(self, model_path=config.MODEL_PATH, camera_index=config.CAMERA_INDEX):
        self.interpreter = Interpreter(model_path=model_path)
        self.interpreter.allocate_tensors()
        self._input_details = self.interpreter.get_input_details()
        self._output_details = self.interpreter.get_output_details()
        self._input_h = self._input_details[0]["shape"][1]
        self._input_w = self._input_details[0]["shape"][2]

        self.cap = cv2.VideoCapture(camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)

        # rolling buffer of recent classifications, used to smooth
        # single-frame misclassifications out of the missed-feed decision
        self._recent = collections.deque(maxlen=15)

    def _preprocess(self, frame):
        resized = cv2.resize(frame, (self._input_w, self._input_h))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        normalized = (rgb.astype(np.float32) / 127.5) - 1.0
        return np.expand_dims(normalized, axis=0)

    def classify_frame(self):
        """Grabs one frame and returns (label, confidence) or (None, 0.0)
        if the camera didn't return a frame."""
        ok, frame = self.cap.read()
        if not ok:
            return None, 0.0

        input_tensor = self._preprocess(frame)
        self.interpreter.set_tensor(self._input_details[0]["index"], input_tensor)
        self.interpreter.invoke()
        output = self.interpreter.get_tensor(self._output_details[0]["index"])[0]

        idx = int(np.argmax(output))
        label = config.CLASS_NAMES[idx]
        confidence = float(output[idx])
        self._recent.append(label)
        return label, confidence

    def pet_ate_recently(self):
        """True if 'pet_eating' shows up often enough in the recent buffer
        to count as a real feeding event rather than a passing glance."""
        if not self._recent:
            return False
        eating_frames = sum(1 for label in self._recent if label == "pet_eating")
        return (eating_frames / len(self._recent)) >= 0.2

    def watch_for_missed_feed(self, check_duration_s=60, sample_interval_s=2):
        """Called after a scheduled feed dispenses. Samples the camera for
        `check_duration_s` seconds; if 'pet_eating' is never observed above
        confidence threshold, the feed is flagged as missed."""
        start = time.time()
        while time.time() - start < check_duration_s:
            label, confidence = self.classify_frame()
            if label == "pet_eating" and confidence >= config.MISSED_FEED_CONFIDENCE_THRESH:
                return {"missed": False, "confirmed_at": time.time()}
            time.sleep(sample_interval_s)

        return {"missed": True, "checked_for_s": check_duration_s}

    def release(self):
        self.cap.release()


if __name__ == "__main__":
    # Manual smoke test: prints live classifications, Ctrl+C to stop
    detector = FeedingDetector()
    print("Running live classification. Ctrl+C to stop.")
    try:
        while True:
            label, confidence = detector.classify_frame()
            print(f"{label} ({confidence:.2f})")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        detector.release()
