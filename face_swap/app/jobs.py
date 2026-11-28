"""Background work: analysing uploaded videos and running swaps."""
import logging
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from . import media
from .faces import FaceEngineUnavailable
from .providers import ProviderError, SwapInputs
from .models import FacePhoto, Output, Purge, SourceVideo, SwapJob, UsageEvent, User, utcnow
from .services import record_claude_usage

log = logging.getLogger("face_swap.jobs")
SAME_PERSON = 0.38
POLL_EVERY = timedelta(seconds=5)


class SwapError(ValueError):
    pass


# ---------- analysing a video ----------

def analyze_video(session, video: SourceVideo, *, storage, engine_factory, checker, cfg) -> None:
    video.analysis_status = "analyzing"
    session.commit()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            storage.get_to_file(video.video_key, src)
            info = media.probe(str(src))
            video.width, video.height, video.duration_s = info["width"], info["height"], round(info["duration"], 2)
            if info["duration"] > cfg.MAX_VIDEO_SECONDS:
                raise media.MediaError(f"動画が長すぎます（{cfg.MAX_VIDEO_SECONDS}秒まで）")
            frames = media.grab_frames(str(src), f"{tmp}/frames", every_s=1.0, max_frames=cfg.MAX_VIDEO_SECONDS)
            if not frames:
                raise media.MediaError("コマを取り出せませんでした")

            engine = engine_factory()
            video.detected_faces = _people(engine, frames, storage, video)

            step = max(1, len(frames) // 12)
            sample = [f.read_bytes() for f in frames[::step][:12]]
            outcome = checker.check_images(sample, "a source video the owner wants to put their own face into")
            record_claude_usage(session, video.user_id, outcome)
            video.safety_status = "passed" if outcome.passed else "blocked"
            video.safety_result = outcome.result
        video.analysis_status = "done"
        video.analysis_error = None
    except (media.MediaError, FaceEngineUnavailable, ValueError) as e:
        video.analysis_status = "failed"
        video.analysis_error = str(e)
        video.safety_status = "blocked" if video.safety_status == "pending" else video.safety_status
    session.commit()


def _people(engine, frames, storage, video) -> list[dict]:
    """Group the faces seen across frames into people."""
    from .faces import decode_image

    people = []  # each: {emb, count, best_score, box, frame, t}
    for i, f in enumerate(frames):
        img = decode_image(f.read_bytes())
        for face in engine.detect(img):
            emb = engine.embed(img, face)
            match = None
            for p in people:
                if engine.similarity(p["emb"], emb) >= SAME_PERSON:
                    match = p
                    break
            if match is None:
                match = {"emb": emb, "count": 0, "best_score": -1.0, "t": float(i)}
                people.append(match)
            match["count"] += 1
            if face.score > match["best_score"]:
                match.update(best_score=face.score, box=list(face.box), frame=f, img=img)
    people.sort(key=lambda p: -p["count"])
    out = []
    import cv2
    for idx, p in enumerate(people[:8]):
        x, y, w, h = (int(v) for v in p["box"])
        pad = int(max(w, h) * 0.35)
        crop = p["img"][max(0, y - pad): y + h + pad, max(0, x - pad): x + w + pad]
        ok, jpg = cv2.imencode(".jpg", crop)
        key = f"videos/{video.user_id}/{video.id}/person{idx}.jpg"
        storage.put_bytes(key, jpg.tobytes())
        out.append({"index": idx, "frames": p["count"], "first_seen_s": p["t"],
                    "box": p["box"], "thumb_key": key})
    return out


# ---------- starting a swap ----------

def spent_today_micro(session, user_id) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total = session.scalar(select(func.coalesce(func.sum(UsageEvent.cost_micro_usd), 0))
                           .where(UsageEvent.user_id == user_id, UsageEvent.created_at >= start))
    pending = session.scalar(select(func.coalesce(func.sum(SwapJob.estimated_cost_micro_usd), 0))
                             .where(SwapJob.user_id == user_id, SwapJob.created_at >= start,
                                    SwapJob.status.in_(["queued", "submitted", "processing", "postprocessing"])))
    return int(total or 0) + int(pending or 0)


def estimate_micro(video: SourceVideo, cfg) -> int:
    seconds = max(3.0, float(video.duration_s or 0))
    return int(round(seconds * cfg.FACESWAP_PRICE_PER_SECOND_USD * 1_000_000))


def create_swap(session, *, user: User, video: SourceVideo, target_index: int, aspect: str,
                photo_id: str | None, idempotency_key: str, cfg) -> SwapJob:
    existing = session.scalar(select(SwapJob).where(SwapJob.user_id == user.id,
                                                    SwapJob.idempotency_key == idempotency_key))
    if existing:
        return existing
    if video.user_id != user.id:
        raise SwapError("動画が見つかりません")
    if video.analysis_status != "done":
        raise SwapError("動画の確認がまだ終わっていません")
    if video.safety_status != "passed":
        raise SwapError("この動画は安全チェックを通らなかったため使えません")
    if not any(p["index"] == target_index for p in video.detected_faces):
        raise SwapError("入れ替える人を選んでください")
    if aspect not in media.OUTPUT_SIZES:
        raise SwapError("縦か横を選んでください")
    face = user.face
    if face is None:
        raise SwapError("先に自分の顔を登録してください")
    photos = {p.id: p for p in face.photos}
    photo = photos.get(photo_id) if photo_id else next((p for p in face.photos if p.is_primary), None)
    if photo is None:
        raise SwapError("使う顔写真が見つかりません")

    est = estimate_micro(video, cfg)
    limit = int(cfg.DAILY_SPEND_LIMIT_USD * 1_000_000)
    if spent_today_micro(session, user.id) + est > limit:
        raise SwapError(f"今日の費用の上限（${cfg.DAILY_SPEND_LIMIT_USD:.2f}）を超えるため、始められません")

    job = SwapJob(user_id=user.id, source_video_id=video.id, face_photo_id=photo.id,
                  target_face_index=target_index, aspect=aspect, idempotency_key=idempotency_key,
                  provider=cfg.FACESWAP_PROVIDER, safety_status="passed", status="queued",
                  estimated_seconds=video.duration_s, estimated_cost_micro_usd=est)
    session.add(job)
    session.commit()
    return job


# ---------- running a swap ----------

def _purge_job_files(session, job):
    for name in ("to_face.png", "from_face.png"):
        session.add(Purge(key=f"jobs/{job.user_id}/{job.id}/{name}"))


def _fail(session, job, msg):
    job.status = "failed"
    job.error = msg
    _purge_job_files(session, job)
    session.commit()


def step_swap(session, job: SwapJob, *, storage, provider, cfg, workdir: str) -> None:
    """Advance one job by one step. Safe to call repeatedly."""
    if job.status in ("done", "failed", "blocked", "cancelled"):
        return
    if job.safety_status != "passed":
        job.status = "blocked"
        session.commit()
        return
    photo = session.get(FacePhoto, job.face_photo_id) if job.face_photo_id else None
    if photo is None:
        return _fail(session, job, "顔が削除されたため、処理を中止しました")
    video = job.video
    target = next((p for p in video.detected_faces if p["index"] == job.target_face_index), None)
    if target is None:
        return _fail(session, job, "入れ替える人が見つかりません")

    jobdir = Path(workdir) / job.id
    jobdir.mkdir(parents=True, exist_ok=True)
    try:
        if job.status == "queued":
            inputs = _prepare_inputs(job, video, photo, target, storage=storage, provider=provider, jobdir=jobdir)
            job.attempts += 1
            res = provider.submit(inputs)
            job.provider_task_id = res.task_id
            job.provider_price = res.price
            job.status = "submitted"
            job.next_poll_at = utcnow()
            session.commit()

        if job.status in ("submitted", "processing"):
            started = job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=timezone.utc)
            if utcnow() - started > timedelta(minutes=cfg.SWAP_TIMEOUT_MINUTES):
                return _fail(session, job, "時間がかかりすぎたため、中止しました")
            res = provider.poll(job.provider_task_id, str(jobdir))
            if res.status == "failed":
                # no automatic resubmit: each submit is billed, and a content refusal would repeat
                return _fail(session, job, res.error or "顔の入れ替えに失敗しました")
            if res.status != "done":
                job.status = "processing"
                job.next_poll_at = utcnow() + POLL_EVERY
                session.commit()
                return
            job.status = "postprocessing"
            session.commit()
            _finish(session, job, res.result_path, storage=storage, cfg=cfg, jobdir=jobdir)
    except (media.MediaError, ProviderError) as e:
        _fail(session, job, str(e))


TO_FACE_MAX = 1072      # Facemint: to_face PNG under 1080x1080
FROM_FACE_SIZE = 128    # Facemint: from_face recommended 128x128 PNG
URL_TTL = timedelta(hours=2)


def _png(src_bytes: bytes, max_side: int, exact: bool = False) -> bytes:
    import cv2
    from .faces import decode_image

    img = decode_image(src_bytes)
    h, w = img.shape[:2]
    if exact:
        img = cv2.resize(img, (max_side, max_side), interpolation=cv2.INTER_AREA)
    elif max(h, w) > max_side:
        scale = max_side / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, data = cv2.imencode(".png", img)
    return data.tobytes()


def _prepare_inputs(job, video, photo, target, *, storage, provider, jobdir: Path):
    """Local copies for every provider, plus short-lived URLs for providers that fetch files."""
    src, to_face, from_face = jobdir / "src.mp4", jobdir / "to_face.png", jobdir / "from_face.png"
    storage.get_to_file(video.video_key, src)
    to_face.write_bytes(_png(storage.get_bytes(photo.image_key), TO_FACE_MAX))
    from_face.write_bytes(_png(storage.get_bytes(target["thumb_key"]), FROM_FACE_SIZE, exact=True))

    urls = {"video": None, "to": None, "from": None}
    if provider.needs_urls:
        base = f"jobs/{job.user_id}/{job.id}"
        storage.put_file(f"{base}/to_face.png", to_face)
        storage.put_file(f"{base}/from_face.png", from_face)
        # deleted by _purge_job_files() once the job ends, not before: the provider fetches them later
        urls ={"video": storage.url(video.video_key, URL_TTL),
                "to": storage.url(f"{base}/to_face.png", URL_TTL),
                "from": storage.url(f"{base}/from_face.png", URL_TTL)}
    return SwapInputs(video_path=str(src), to_face_path=str(to_face), from_face_path=str(from_face),
                      video_url=urls["video"], to_face_url=urls["to"], from_face_url=urls["from"],
                      duration_s=float(video.duration_s or 0), workdir=str(jobdir))


def _finish(session, job, result_path, *, storage, cfg, jobdir: Path):
    rendered, signed = jobdir / "rendered.mp4", jobdir / "signed.mp4"
    height = media.render_output(result_path, str(rendered), job.aspect, cfg.WATERMARK_FONT)
    media.c2pa_sign(str(rendered), str(signed), cfg.C2PA_CERT_CHAIN_PATH, cfg.C2PA_PRIVATE_KEY_PATH,
                    title=f"face-swap {job.id}.mp4")
    key = f"outputs/{job.user_id}/{job.id}.mp4"
    storage.put_file(key, signed)
    session.add(Output(user_id=job.user_id, job_id=job.id, video_key=key, aspect=job.aspect,
                       height=height, watermarked=True, c2pa_signed=True))
    seconds = max(3.0, float(job.estimated_seconds or 0))
    session.add(UsageEvent(user_id=job.user_id, job_id=job.id, service="faceswap", units=seconds,
                           unit="seconds", cost_micro_usd=0 if job.provider.startswith("dev_")
                           else int(job.estimated_cost_micro_usd or 0)))
    job.status = "done"
    job.estimated_cost_micro_usd = 0
    _purge_job_files(session, job)
    session.commit()


# ---------- the worker loop ----------

def run_pending(session_factory, *, storage, engine_factory, checker, provider, cfg, workdir: str) -> int:
    """Do one round of work. Returns how many items were touched."""
    touched = 0
    with session_factory() as s:
        for p in s.scalars(select(Purge).limit(50)).all():
            try:
                storage.delete(p.key)
            except Exception:  # keep the row and retry later
                continue
            s.delete(p)
            touched += 1
        s.commit()

    with session_factory() as s:
        v = s.scalars(select(SourceVideo).where(SourceVideo.analysis_status == "pending")
                      .order_by(SourceVideo.created_at).limit(1).with_for_update(skip_locked=True)).first()
        if v:
            analyze_video(s, v, storage=storage, engine_factory=engine_factory, checker=checker, cfg=cfg)
            touched += 1

    with session_factory() as s:
        now = utcnow()
        jobs = s.scalars(select(SwapJob).where(SwapJob.status.in_(["queued", "submitted", "processing"]))
                         .order_by(SwapJob.created_at).limit(5).with_for_update(skip_locked=True)).all()
        for job in jobs:
            due = job.next_poll_at
            if due is not None and due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if job.status != "queued" and due and due > now:
                continue
            step_swap(s, job, storage=storage, provider=provider, cfg=cfg, workdir=workdir)
            touched += 1
    return touched
