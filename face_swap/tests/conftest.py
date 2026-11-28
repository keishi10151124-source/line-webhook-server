import base64
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.config import Config
from app.faces import DetectedFace
from app.providers import DevPassthroughProvider
from app.safety import SafetyOutcome

PASSWORD = "correct horse battery"
EMAIL = "owner@example.com"


class FakeEngine:
    """Reads 'faces' out of solid-colour test images:
    blue channel -> identity (0, 1, 2), green -> head yaw, red >= 128 -> two people."""

    def detect(self, img):
        b, gr, r = (float(v) for v in img.reshape(-1, 3).mean(axis=0))
        ident = int(round(b / 127.5))
        yaw = (gr - 128) / 255
        n = 2 if r >= 128 else 1
        faces = []
        for i in range(n):
            # landmarks chosen so DetectedFace.yaw equals `yaw`
            lm = [(40.0, 50.0), (80.0, 50.0), (60.0 + yaw * 40.0, 70.0), (45.0, 90.0), (75.0, 90.0)]
            faces.append(DetectedFace((10.0 + 100 * i, 10.0, 100.0, 100.0), 0.95 - i * 0.1, lm, (ident + i * 7,)))
        return faces

    def embed(self, img, face):
        v = np.zeros(16, dtype=np.float32)
        v[face.raw[0] % 16] = 1.0
        return v

    @staticmethod
    def similarity(a, b):
        return float(np.dot(a, b) / ((np.linalg.norm(a) or 1) * (np.linalg.norm(b) or 1)))


class FakeChecker:
    name = "fake"

    def __init__(self):
        self.block = False
        self.calls = []

    def check_images(self, images, purpose):
        self.calls.append(purpose)
        if self.block:
            return SafetyOutcome(False, {"reason": "テスト用に止めました", "sexual": True}, 100, 20)
        return SafetyOutcome(True, {"reason": "問題なし"}, 100, 20)


def jpeg(ident=0, yaw=0.0, two=False, size=200) -> bytes:
    img = np.zeros((size, size, 3), dtype=np.uint8)
    img[:] = (ident * 127.5, 128 + yaw * 255, 200 if two else 0)
    ok, data = cv2.imencode(".jpg", img)
    return data.tobytes()


def data_url(b: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(b).decode()


def make_video(path: Path, ident=1, seconds=3, two=False, size="360x640"):
    b = int(ident * 127.5)
    color = f"0x{200 if two else 0:02x}{128:02x}{b:02x}"  # 0xRRGGBB
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=24:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


@pytest.fixture(scope="session")
def c2pa_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("c2pa")
    from scripts.make_c2pa_cert import main
    main(str(d))
    return d


@pytest.fixture
def cfg(tmp_path, c2pa_dir):
    c = Config()
    c.APP_ENV = "test"
    c.SECRET_KEY = "test-secret"
    c.DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    if os.environ.get("TEST_DATABASE_URL"):
        from app.models import Base, make_session_factory
        eng, _ = make_session_factory(c.DATABASE_URL)
        Base.metadata.drop_all(eng)
        eng.dispose()
    c.OWNER_EMAIL = EMAIL
    c.OWNER_PASSWORD_HASH = generate_password_hash(PASSWORD)
    c.STORAGE = "local"
    c.LOCAL_STORAGE_DIR = str(tmp_path / "files")
    c.SAFETY = "claude"
    c.FACESWAP_PROVIDER = "dev_passthrough"
    c.C2PA_CERT_CHAIN_PATH = str(c2pa_dir / "c2pa_chain.pem")
    c.C2PA_PRIVATE_KEY_PATH = str(c2pa_dir / "c2pa_key.pem")
    c.RUN_JOBS_INLINE = False
    return c


@pytest.fixture
def checker():
    return FakeChecker()


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def app(cfg, checker, engine):
    a = create_app(cfg, engine_factory=lambda: engine, checker=checker, provider=DevPassthroughProvider())
    a.config["TESTING"] = True
    return a


@pytest.fixture
def ctx(app):
    return app.extensions["face_swap"]


class Client:
    def __init__(self, app):
        self.c = app.test_client()
        self.csrf = None

    def get(self, *a, **kw):
        return self.c.get(*a, **kw)

    def _token(self):
        with self.c.session_transaction() as s:
            return s.get("csrf")

    def post(self, url, **kw):
        headers = kw.pop("headers", {})
        headers.setdefault("X-CSRF-Token", self._token() or "")
        return self.c.post(url, headers=headers, **kw)

    def login(self):
        self.c.get("/login")
        r = self.c.post("/login", data={"email": EMAIL, "password": PASSWORD})
        assert r.status_code == 302, r.data
        self.c.get("/")  # sets a CSRF token
        return self


@pytest.fixture
def client(app):
    return Client(app).login()


def run_jobs(ctx, rounds=5):
    from app.jobs import run_pending
    for _ in range(rounds):
        run_pending(ctx["Session"], storage=ctx["storage"], engine_factory=ctx["engine_factory"],
                    checker=ctx["checker"], provider=ctx["provider"], cfg=ctx["cfg"], workdir=ctx["workdir"])


def register_face(client, ident=0):
    ch = client.post("/api/face/challenge").get_json()
    frames = {"center": data_url(jpeg(ident, 0.0)), "turn_a": data_url(jpeg(ident, 0.3)),
              "turn_b": data_url(jpeg(ident, -0.3))}
    return client.post("/api/face", json={"challenge_id": ch["challenge_id"], "frames": frames, "client_ok": True})
