"""Face swap providers.

- dev_passthrough: development only, returns the video unchanged.
- FacemintProvider: https://api.facemint.io/api (docs: facemint.io/face-swap-api). Submitting is
  written from the "Create Face Swap Task" page. Polling waits for the "Get Face Swap Task Info
  by ID" page, so the provider is not registered for use yet.
"""
import json
import math
import shutil
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field


@dataclass
class SwapInputs:
    """Everything a provider may need. Local paths for providers that run here,
    short-lived URLs for providers that fetch the files themselves."""
    video_path: str
    to_face_path: str            # the owner's face, PNG
    from_face_path: str          # crop of the one person to replace, PNG
    video_url: str | None
    to_face_url: str | None
    from_face_url: str | None
    duration_s: float
    workdir: str


@dataclass
class SubmitResult:
    task_id: str
    price: int | None = None     # in the provider's own unit


@dataclass
class PollResult:
    status: str                  # processing | done | failed
    result_path: str | None = None
    error: str | None = None


class ProviderError(RuntimeError):
    pass


class FaceSwapProvider:
    name = "base"
    terms_note = ""
    needs_urls = False

    def submit(self, inp: SwapInputs) -> SubmitResult:
        raise NotImplementedError

    def poll(self, task_id: str, workdir: str) -> PollResult:
        raise NotImplementedError


class DevPassthroughProvider(FaceSwapProvider):
    """Development only: returns the source video unchanged, so the rest of the pipeline
    (watermark, C2PA, storage, screens) can be tested without paying for an API.
    Config.validate() refuses it in production."""
    name = "dev_passthrough"
    terms_note = "開発用（顔は入れ替わりません）"

    def submit(self, inp):
        task_id = uuid.uuid4().hex
        shutil.copyfile(inp.video_path, f"{inp.workdir}/{task_id}.mp4")
        return SubmitResult(task_id)

    def poll(self, task_id, workdir):
        return PollResult("done", f"{workdir}/{task_id}.mp4")


def _http_json(method: str, url: str, headers: dict, body: dict | None, timeout: float = 60) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={**headers, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


@dataclass
class FacemintSettings:
    api_key: str
    base_url: str = "https://api.facemint.io/api"
    resolution: int = 2               # 1=480p, 2=720p, 3=1080p ... (billed at the requested level)
    enhance: int = 1
    face_recognition: float = 0.6     # lower = stricter match (Facemint default 0.8)
    face_detection: float = 0.25     # Facemint default
    watermark_text: str = "AI-GENERATED"
    callback_url: str = ""


class FacemintProvider(FaceSwapProvider):
    name = "facemint"
    terms_note = "Facemint（生成物は7日で削除。学習には使わないと規約に記載）"
    needs_urls = True

    def __init__(self, settings: FacemintSettings, http=_http_json):
        if not settings.api_key:
            raise ProviderError("FACEMINT_API_KEY が設定されていません")
        self.s = settings
        self.http = http

    def build_request(self, inp: SwapInputs) -> dict:
        if not (inp.video_url and inp.to_face_url and inp.from_face_url):
            raise ProviderError("Facemint には外から読めるファイルのURLが必要です（STORAGE=r2 で使ってください）")
        body = {
            "type": "video",
            "media_url": inp.video_url,
            "start_time": 0,
            "end_time": max(1, math.ceil(inp.duration_s)),
            "resolution": self.s.resolution,
            "enhance": self.s.enhance,
            "nsfw_check": 1,                         # always on, on top of our own check
            "face_recognition": self.s.face_recognition,
            "face_detection": self.s.face_detection,
            "watermark": self.s.watermark_text,
            # from_face is always sent: without it Facemint replaces every face in the video
            "swap_list": [{"from_face": inp.from_face_url, "to_face": inp.to_face_url}],
        }
        if self.s.callback_url:
            body["callback_url"] = self.s.callback_url
        return body

    def submit(self, inp):
        status, resp = self.http("POST", f"{self.s.base_url}/create-face-swap-task",
                                 {"x-api-key": self.s.api_key}, self.build_request(inp))
        data = resp.get("data") or {}
        if status not in (200, 201) or resp.get("code") != 0 or not data.get("taskId"):
            raise ProviderError(f"Facemint がタスクを受け付けませんでした（{status}: {resp.get('info', '')}）")
        return SubmitResult(str(data["taskId"]), data.get("price"))

    def poll(self, task_id, workdir):
        raise ProviderError("Facemint の結果の受け取り方（Get Face Swap Task Info by ID）がまだ実装されていません")


# facemint is added here once poll() is written from its docs
PROVIDERS = {"dev_passthrough": lambda cfg: DevPassthroughProvider()}


def make_provider(cfg) -> FaceSwapProvider:
    try:
        factory = PROVIDERS[cfg.FACESWAP_PROVIDER]
    except KeyError:
        raise RuntimeError(f"未対応の顔入れ替えAPIです: {cfg.FACESWAP_PROVIDER}")
    return factory(cfg)
