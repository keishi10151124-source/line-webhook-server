"""Settings, read from environment variables only. No secrets in code."""
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    APP_ENV: str = field(default_factory=lambda: os.environ.get("APP_ENV", "development"))
    SECRET_KEY: str = field(default_factory=lambda: os.environ.get("SECRET_KEY", ""))
    DATABASE_URL: str = field(
        default_factory=lambda: os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'dev.db'}")
    )

    # the single owner account
    OWNER_EMAIL: str = field(default_factory=lambda: os.environ.get("OWNER_EMAIL", ""))
    OWNER_PASSWORD_HASH: str = field(default_factory=lambda: os.environ.get("OWNER_PASSWORD_HASH", ""))
    # Alternative to OWNER_PASSWORD_HASH for setups without a terminal: the plain password is
    # hashed once at startup and the plain value is dropped from this object.
    OWNER_PASSWORD: str = field(default_factory=lambda: os.environ.get("OWNER_PASSWORD", ""), repr=False)

    # storage: "local" (dev) or "r2"
    STORAGE: str = field(default_factory=lambda: os.environ.get("STORAGE", "local"))
    LOCAL_STORAGE_DIR: str = field(default_factory=lambda: os.environ.get("LOCAL_STORAGE_DIR", str(BASE_DIR / "data" / "files")))
    R2_ENDPOINT: str = field(default_factory=lambda: os.environ.get("R2_ENDPOINT", ""))
    R2_BUCKET: str = field(default_factory=lambda: os.environ.get("R2_BUCKET", ""))
    R2_ACCESS_KEY_ID: str = field(default_factory=lambda: os.environ.get("R2_ACCESS_KEY_ID", ""))
    R2_SECRET_ACCESS_KEY: str = field(default_factory=lambda: os.environ.get("R2_SECRET_ACCESS_KEY", ""))

    # face models (OpenCV Zoo: YuNet MIT, SFace Apache 2.0). Downloaded by scripts/fetch_models.sh
    FACE_MODELS_DIR: str = field(default_factory=lambda: os.environ.get("FACE_MODELS_DIR", str(BASE_DIR / "models")))
    # cosine similarity needed for an uploaded photo to count as the same person as the camera face.
    # OpenCV's published SFace threshold is 0.363; we use a stricter default.
    FACE_MATCH_THRESHOLD: float = field(default_factory=lambda: float(os.environ.get("FACE_MATCH_THRESHOLD", "0.45")))

    # safety check: "claude" or "dev_allow" (development only; refused in production)
    SAFETY: str = field(default_factory=lambda: os.environ.get("SAFETY", "claude"))
    CLAUDE_MODEL: str = field(default_factory=lambda: os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"))

    # face swap provider: "dev_passthrough" (development only) or a real adapter name
    FACESWAP_PROVIDER: str = field(default_factory=lambda: os.environ.get("FACESWAP_PROVIDER", "dev_passthrough"))
    FACESWAP_PRICE_PER_SECOND_USD: float = field(
        default_factory=lambda: float(os.environ.get("FACESWAP_PRICE_PER_SECOND_USD", "0.01"))
    )
    # Facemint (FACESWAP_PROVIDER=facemint). The key is a secret: set it in the host's dashboard.
    FACEMINT_API_KEY: str = field(default_factory=lambda: os.environ.get("FACEMINT_API_KEY", ""))
    FACEMINT_RESOLUTION: int = field(default_factory=lambda: int(os.environ.get("FACEMINT_RESOLUTION", "2")))
    FACEMINT_FACE_RECOGNITION: float = field(
        default_factory=lambda: float(os.environ.get("FACEMINT_FACE_RECOGNITION", "0.6")))
    FACEMINT_FACE_DETECTION: float = field(
        default_factory=lambda: float(os.environ.get("FACEMINT_FACE_DETECTION", "0.25")))
    # a job still running after this long is marked failed
    SWAP_TIMEOUT_MINUTES: int = field(default_factory=lambda: int(os.environ.get("SWAP_TIMEOUT_MINUTES", "120")))
    DAILY_SPEND_LIMIT_USD: float = field(default_factory=lambda: float(os.environ.get("DAILY_SPEND_LIMIT_USD", "20")))

    # C2PA signing (PEM). Created by scripts/make_c2pa_cert.py for personal use.
    C2PA_CERT_CHAIN_PATH: str = field(default_factory=lambda: os.environ.get("C2PA_CERT_CHAIN_PATH", str(BASE_DIR / "secrets" / "c2pa_chain.pem")))
    C2PA_PRIVATE_KEY_PATH: str = field(default_factory=lambda: os.environ.get("C2PA_PRIVATE_KEY_PATH", str(BASE_DIR / "secrets" / "c2pa_key.pem")))
    WATERMARK_FONT: str = field(
        default_factory=lambda: os.environ.get("WATERMARK_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    )

    MAX_VIDEO_SECONDS: int = field(default_factory=lambda: int(os.environ.get("MAX_VIDEO_SECONDS", "60")))
    MAX_VIDEO_BYTES: int = field(default_factory=lambda: int(os.environ.get("MAX_VIDEO_BYTES", str(200 * 1024 * 1024))))
    MAX_PHOTO_BYTES: int = field(default_factory=lambda: int(os.environ.get("MAX_PHOTO_BYTES", str(10 * 1024 * 1024))))

    # run background jobs in a thread inside the web process (handy for local dev)
    RUN_JOBS_INLINE: bool = field(default_factory=lambda: _bool("RUN_JOBS_INLINE", False))

    def __post_init__(self):
        self._password_too_short = False
        if self.OWNER_PASSWORD and not self.OWNER_PASSWORD_HASH:
            if len(self.OWNER_PASSWORD) < 12:
                self._password_too_short = True
            else:
                from werkzeug.security import generate_password_hash
                self.OWNER_PASSWORD_HASH = generate_password_hash(self.OWNER_PASSWORD)
        self.OWNER_PASSWORD = ""

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    def validate(self) -> None:
        """Refuse to start in production with development-only shortcuts."""
        problems = []
        if self._password_too_short:
            problems.append("OWNER_PASSWORD must be at least 12 characters")
        if not self.SECRET_KEY:
            problems.append("SECRET_KEY is not set")
        if self.is_production:
            if self.SAFETY != "claude":
                problems.append("SAFETY must be 'claude' in production")
            if self.FACESWAP_PROVIDER.startswith("dev_"):
                problems.append("FACESWAP_PROVIDER must be a real provider in production")
            if self.STORAGE != "r2":
                problems.append("STORAGE must be 'r2' in production")
            if self.FACESWAP_PROVIDER == "facemint" and not self.FACEMINT_API_KEY:
                problems.append("FACEMINT_API_KEY must be set to use Facemint")
            if not (self.OWNER_EMAIL and self.OWNER_PASSWORD_HASH):
                problems.append("OWNER_EMAIL and OWNER_PASSWORD (or OWNER_PASSWORD_HASH) must be set")
        if problems:
            raise RuntimeError("Invalid configuration: " + "; ".join(problems))
