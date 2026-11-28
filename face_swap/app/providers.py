"""Face swap providers. The real API is not chosen yet (see replica/neface/architecture.md),
so only a development provider exists. A real adapter implements the same three methods."""
import shutil
import uuid
from dataclasses import dataclass


@dataclass
class PollResult:
    status: str               # processing | done | failed
    result_path: str | None = None
    error: str | None = None


class FaceSwapProvider:
    name = "base"
    terms_note = ""

    def submit(self, video_path: str, face_image_path: str, target_box: list[float], workdir: str) -> str:
        raise NotImplementedError

    def poll(self, task_id: str, workdir: str) -> PollResult:
        raise NotImplementedError


class DevPassthroughProvider(FaceSwapProvider):
    """Development only: returns the source video unchanged, so the rest of the pipeline
    (watermark, C2PA, storage, screens) can be tested without paying for an API.
    Config.validate() refuses it in production."""
    name = "dev_passthrough"
    terms_note = "開発用（顔は入れ替わりません）"

    def submit(self, video_path, face_image_path, target_box, workdir):
        task_id = uuid.uuid4().hex
        shutil.copyfile(video_path, f"{workdir}/{task_id}.mp4")
        return task_id

    def poll(self, task_id, workdir):
        return PollResult("done", f"{workdir}/{task_id}.mp4")


PROVIDERS = {"dev_passthrough": DevPassthroughProvider}


def make_provider(cfg) -> FaceSwapProvider:
    try:
        return PROVIDERS[cfg.FACESWAP_PROVIDER]()
    except KeyError:
        raise RuntimeError(f"未対応の顔入れ替えAPIです: {cfg.FACESWAP_PROVIDER}")
