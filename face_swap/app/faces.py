"""Face detection, head pose and identity matching.

Real engine: OpenCV YuNet (detector, MIT) + SFace (recognizer, Apache 2.0) from the OpenCV Model Zoo.
The model files are not in the repository; scripts/fetch_models.sh downloads them.
If they are missing, every face operation fails closed (nothing gets registered).
"""
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = "face_recognition_sface_2021dec.onnx"


class FaceEngineUnavailable(RuntimeError):
    pass


@dataclass
class DetectedFace:
    box: tuple[float, float, float, float]  # x, y, w, h
    score: float
    landmarks: list[tuple[float, float]]    # right eye, left eye, nose, right mouth, left mouth
    raw: object = None                       # engine-specific row, used for alignment

    @property
    def yaw(self) -> float:
        """Signed head turn estimate from the 5 landmarks. ~0 facing the camera.
        The sign depends on which way the head turns (and on mirroring), so callers only
        compare signs between frames, never against a fixed direction."""
        (rx, _), (lx, _), (nx, _) = self.landmarks[0], self.landmarks[1], self.landmarks[2]
        mid = (rx + lx) / 2
        dist = abs(lx - rx) or 1.0
        return (nx - mid) / dist


def decode_image(data: bytes):
    import cv2

    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("画像を読み込めませんでした")
    return img


class OpenCVFaceEngine:
    def __init__(self, models_dir: str):
        import cv2

        d = Path(models_dir) / DETECTOR_FILE
        r = Path(models_dir) / RECOGNIZER_FILE
        if not (d.exists() and r.exists() and d.stat().st_size > 10_000 and r.stat().st_size > 10_000):
            raise FaceEngineUnavailable(
                f"顔のモデルファイルがありません（{models_dir}）。scripts/fetch_models.sh を実行してください"
            )
        self.cv2 = cv2
        self.detector = cv2.FaceDetectorYN.create(str(d), "", (320, 320), 0.8, 0.3, 50)
        self.recognizer = cv2.FaceRecognizerSF.create(str(r), "")

    def detect(self, img) -> list[DetectedFace]:
        h, w = img.shape[:2]
        self.detector.setInputSize((w, h))
        _, rows = self.detector.detect(img)
        faces = []
        if rows is None:
            return faces
        for row in rows:
            lm = [(float(row[4 + 2 * i]), float(row[5 + 2 * i])) for i in range(5)]
            faces.append(DetectedFace(tuple(float(v) for v in row[:4]), float(row[14]), lm, row))
        return faces

    def embed(self, img, face: DetectedFace) -> np.ndarray:
        aligned = self.recognizer.alignCrop(img, face.raw)
        return self.recognizer.feature(aligned).astype(np.float32).flatten()

    @staticmethod
    def similarity(a: np.ndarray, b: np.ndarray) -> float:
        a = a / (np.linalg.norm(a) or 1.0)
        b = b / (np.linalg.norm(b) or 1.0)
        return float(np.dot(a, b))


_engine = None


def get_engine(models_dir: str):
    global _engine
    if _engine is None:
        _engine = OpenCVFaceEngine(models_dir)
    return _engine


def set_engine(engine) -> None:
    """Tests inject a fake engine here."""
    global _engine
    _engine = engine


def to_bytes(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_bytes(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float32)
