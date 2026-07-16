"""
face_extractor.py
-----------------
Detect faces in webcam frames and pick the best unique crops for enrollment.
Uses OpenCV's built-in Haar cascade (no extra model download).
"""

from __future__ import annotations

import cv2
import numpy as np


CASCADE = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

TARGET_SAMPLES = 8
MIN_SAMPLES = 1
MIN_FACE_SIZE = 60


def _decode_image(data: bytes) -> np.ndarray | None:
    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return image


def _prepare_gray(image: np.ndarray) -> np.ndarray:
    """Improve contrast so Haar detection works in dim or uneven lighting."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _detect_largest_face(image: np.ndarray) -> tuple[np.ndarray, float] | None:
    gray = _prepare_gray(image)
    faces = CASCADE.detectMultiScale(
        gray,
        scaleFactor=1.08,
        minNeighbors=4,
        minSize=(MIN_FACE_SIZE, MIN_FACE_SIZE),
    )
    if len(faces) == 0:
        return None

    best = max(faces, key=lambda f: f[2] * f[3])
    x, y, w, h = best
    pad = int(max(w, h) * 0.2)
    y1 = max(0, y - pad)
    y2 = min(image.shape[0], y + h + pad)
    x1 = max(0, x - pad)
    x2 = min(image.shape[1], x + w + pad)
    crop = image[y1:y2, x1:x2]
    crop_gray = gray[y1:y2, x1:x2]
    score = w * h + _sharpness(crop_gray) * 10
    return crop, score


def _is_duplicate(candidate: np.ndarray, existing: list[np.ndarray], threshold: float = 12.0) -> bool:
    small = cv2.resize(candidate, (64, 64))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
    for item in existing:
        other = cv2.resize(item, (64, 64))
        other_gray = cv2.cvtColor(other, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if float(np.mean(np.abs(gray - other_gray))) < threshold:
            return True
    return False


def extract_best_face_crops(
    frame_bytes_list: list[bytes],
    max_samples: int = TARGET_SAMPLES,
) -> list[np.ndarray]:
    """
    Run face detection across many captured frames and return up to max_samples
    distinct, high-quality face crops.
    """
    candidates: list[tuple[float, np.ndarray]] = []

    for data in frame_bytes_list:
        image = _decode_image(data)
        if image is None:
            continue
        result = _detect_largest_face(image)
        if result is None:
            continue
        crop, score = result
        candidates.append((score, crop))

    candidates.sort(key=lambda item: item[0], reverse=True)

    selected: list[np.ndarray] = []
    for _, crop in candidates:
        if _is_duplicate(crop, selected):
            continue
        selected.append(crop)
        if len(selected) >= max_samples:
            break

    if len(selected) < MIN_SAMPLES:
        raise ValueError(
            f"Could not find enough clear faces. Found {len(selected)}, need at least {MIN_SAMPLES}. "
            "Try better lighting, face the camera directly, and stay still."
        )

    return selected


def extract_face_crops_from_video(video_path: str, max_samples: int = TARGET_SAMPLES) -> list[np.ndarray]:
    """
    Fallback path when only a video file is available.
    OpenCV WebM support can be unreliable on Windows, so JPEG frames are preferred.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    frame_bytes: list[bytes] = []
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1
        if frame_idx % 3 != 0:
            continue
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if ok:
            frame_bytes.append(encoded.tobytes())
    cap.release()

    if not frame_bytes:
        return []

    try:
        return extract_best_face_crops(frame_bytes, max_samples=max_samples)
    except ValueError:
        return []
