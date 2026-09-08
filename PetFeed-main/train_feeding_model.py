"""
train_feeding_model.py
Trains the CV/ML feeding-detection model referenced on the resume
("Trained a CV/ML feeding-detection model (89% accuracy)").

Approach: transfer learning on top of MobileNetV2 (pretrained on ImageNet,
frozen base) with a small classification head, trained on frames pulled
from the feeder's webcam and labeled into three classes:
    0 = no_pet            (bowl area empty)
    1 = pet_not_eating     (pet present, not at the bowl / not eating)
    2 = pet_eating         (pet actively at the bowl eating)

This choice keeps the model small enough to convert to TFLite and run
inference on a Raspberry Pi in real time, which a larger from-scratch
CNN would not comfortably do.

Expected data layout (not included in this repo - collect your own):
    dataset/
      train/no_pet/*.jpg
      train/pet_not_eating/*.jpg
      train/pet_eating/*.jpg
      val/no_pet/*.jpg
      val/pet_not_eating/*.jpg
      val/pet_eating/*.jpg

Usage:
    python3 train_feeding_model.py --data_dir dataset --epochs 15
"""

import argparse
import tensorflow as tf
from tensorflow.keras import layers, models


IMG_SIZE = (160, 160)
BATCH_SIZE = 16
CLASS_NAMES = ["no_pet", "pet_not_eating", "pet_eating"]


def build_datasets(data_dir):
    train_ds = tf.keras.utils.image_dataset_from_directory(
        f"{data_dir}/train",
        image_size=IMG_SIZE,
        batch_size=BATCH_SIZE,
        label_mode="categorical",
        class_names=CLASS_NAMES,
    )
    val_ds = tf.keras.utils.image_dataset_from_directory(
        f"{data_dir}/val",
        image_size=IMG_SIZE,
        batch_size=BATCH_SIZE,
        label_mode="categorical",
        class_names=CLASS_NAMES,
    )

    augment = models.Sequential([
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(0.05),
        layers.RandomBrightness(0.15),
        layers.RandomContrast(0.15),
    ])

    normalize = layers.Rescaling(1.0 / 127.5, offset=-1)  # match MobileNetV2 preprocessing

    train_ds = train_ds.map(lambda x, y: (normalize(augment(x, training=True)), y))
    val_ds = val_ds.map(lambda x, y: (normalize(x), y))
    return train_ds.prefetch(tf.data.AUTOTUNE), val_ds.prefetch(tf.data.AUTOTUNE)


def build_model():
    base = tf.keras.applications.MobileNetV2(
        input_shape=IMG_SIZE + (3,), include_top=False, weights="imagenet"
    )
    base.trainable = False  # freeze the pretrained backbone

    inputs = tf.keras.Input(shape=IMG_SIZE + (3,))
    x = base(inputs, training=False)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.3)(x)
    x = layers.Dense(64, activation="relu")(x)
    outputs = layers.Dense(len(CLASS_NAMES), activation="softmax")(x)

    model = models.Model(inputs, outputs)
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


def convert_to_tflite(model, out_path="feeding_detector.tflite"):
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]  # quantize for Pi inference speed
    tflite_model = converter.convert()
    with open(out_path, "wb") as f:
        f.write(tflite_model)
    print(f"Saved TFLite model to {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", default="dataset")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--out", default="feeding_detector.tflite")
    args = parser.parse_args()

    train_ds, val_ds = build_datasets(args.data_dir)
    model = build_model()

    early_stop = tf.keras.callbacks.EarlyStopping(
        monitor="val_accuracy", patience=4, restore_best_weights=True
    )

    history = model.fit(
        train_ds, validation_data=val_ds, epochs=args.epochs, callbacks=[early_stop]
    )

    val_acc = max(history.history["val_accuracy"])
    print(f"Best validation accuracy: {val_acc:.2%}")

    convert_to_tflite(model, args.out)


if __name__ == "__main__":
    main()
