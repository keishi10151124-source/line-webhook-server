"""Screens (S01-S09) and JSON endpoints."""
import base64
import uuid
from datetime import datetime, timezone

from flask import (Blueprint, Response, abort, current_app, flash, g, jsonify, redirect,
                   render_template, request, send_file, url_for)
from sqlalchemy import func, select

from .auth import login_required
from .faces import FaceEngineUnavailable
from .jobs import SwapError, create_swap, estimate_micro, spent_today_micro
from .liveness import LivenessError, new_challenge
from .models import FacePhoto, Output, SourceVideo, SwapJob, Template, UsageEvent
from .services import FaceError, add_uploaded_photo, delete_face, delete_photo, register_face, set_primary

bp = Blueprint("views", __name__)
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm"}


def ctx():
    return current_app.extensions["face_swap"]


def _video(video_id) -> SourceVideo:
    v = g.db.get(SourceVideo, video_id)
    if v is None or v.user_id != g.user.id:
        abort(404)
    return v


def _job(job_id) -> SwapJob:
    j = g.db.get(SwapJob, job_id)
    if j is None or j.user_id != g.user.id:
        abort(404)
    return j


def _file_response(key: str, download_name: str | None = None, mimetype: str | None = None):
    st = ctx()["storage"]
    url = st.url(key)
    if url:
        return redirect(url)
    path = st.local_path(key)
    if path is None or not path.exists():
        abort(404)
    return send_file(path, mimetype=mimetype, as_attachment=bool(download_name), download_name=download_name)


# ---------- S01 home ----------

@bp.get("/")
@login_required
def home():
    aspect = request.args.get("aspect", "")
    category = request.args.get("category", "")
    q = select(Template).join(SourceVideo).where(Template.user_id == g.user.id)
    if category:
        q = q.where(Template.category == category)
    templates = g.db.scalars(q.order_by(Template.created_at.desc())).all()
    if aspect in ("9:16", "16:9"):
        templates = [t for t in templates if _aspect_of(t.video) == aspect]
    categories = sorted({c for c in g.db.scalars(select(Template.category).where(
        Template.user_id == g.user.id, Template.category.is_not(None))).all()})
    recent = g.db.scalars(select(Output).where(Output.user_id == g.user.id)
                          .order_by(Output.created_at.desc()).limit(6)).all()
    return render_template("home.html", templates=templates, categories=categories, recent=recent,
                           aspect=aspect, category=category, has_face=g.user.face is not None)


def _aspect_of(v: SourceVideo) -> str:
    if not (v.width and v.height):
        return "other"
    r = v.width / v.height
    return "9:16" if r < 0.8 else ("16:9" if r > 1.25 else "other")


# ---------- S02 template detail ----------

@bp.get("/templates/<tid>")
@login_required
def template_detail(tid):
    t = g.db.get(Template, tid)
    if t is None or t.user_id != g.user.id:
        abort(404)
    return render_template("template.html", t=t)


@bp.post("/videos/<video_id>/template")
@login_required
def make_template(video_id):
    v = _video(video_id)
    if v.safety_status != "passed":
        flash("安全チェックを通った動画だけテンプレートにできます", "error")
        return redirect(url_for("views.video_page", video_id=v.id))
    title = request.form.get("title", "").strip()[:120]
    license_note = request.form.get("license_note", "").strip()
    if not title or not license_note:
        flash("名前と、素材の権利についてのメモを入れてください", "error")
        return redirect(url_for("views.video_page", video_id=v.id))
    if v.template is None:
        v.kind = "template"
        g.db.add(Template(user_id=g.user.id, source_video_id=v.id, title=title,
                          category=(request.form.get("category", "").strip()[:60] or None),
                          license_note=license_note))
        g.db.commit()
    flash("テンプレートに追加しました", "ok")
    return redirect(url_for("views.home"))


# ---------- S03 upload ----------

@bp.get("/upload")
@login_required
def upload_page():
    cfg = ctx()["cfg"]
    return render_template("upload.html", max_seconds=cfg.MAX_VIDEO_SECONDS,
                           max_mb=cfg.MAX_VIDEO_BYTES // (1024 * 1024))


@bp.post("/upload")
@login_required
def upload_video():
    cfg = ctx()["cfg"]
    f = request.files.get("video")
    if not request.form.get("rights_confirmed"):
        flash("動画の権利の確認にチェックを入れてください", "error")
        return redirect(url_for("views.upload_page"))
    if f is None or not f.filename:
        flash("動画を選んでください", "error")
        return redirect(url_for("views.upload_page"))
    if f.mimetype not in VIDEO_TYPES:
        flash("MP4、MOV、WebM の動画だけ使えます", "error")
        return redirect(url_for("views.upload_page"))
    data = f.read()
    if not data:
        flash("空のファイルです", "error")
        return redirect(url_for("views.upload_page"))
    if len(data) > cfg.MAX_VIDEO_BYTES:
        flash("動画が大きすぎます", "error")
        return redirect(url_for("views.upload_page"))
    vid = str(uuid.uuid4())
    key = f"videos/{g.user.id}/{vid}/source"
    ctx()["storage"].put_bytes(key, data)
    v = SourceVideo(id=vid, user_id=g.user.id, kind="upload", original_name=f.filename[:255], video_key=key,
                    bytes=len(data), rights_confirmed=True,
                    rights_note=(request.form.get("rights_note", "").strip() or None))
    g.db.add(v)
    g.db.commit()
    return redirect(url_for("views.video_page", video_id=v.id))


# ---------- S04 choose who to replace ----------

@bp.get("/videos/<video_id>")
@login_required
def video_page(video_id):
    v = _video(video_id)
    cfg = ctx()["cfg"]
    est = estimate_micro(v, cfg) if v.duration_s else None
    face = g.user.face
    return render_template("video.html", v=v, est_usd=(est / 1_000_000 if est is not None else None),
                           photos=(face.photos if face else []), aspect_guess=_aspect_of(v),
                           idem=uuid.uuid4().hex)


@bp.get("/api/videos/<video_id>")
@login_required
def video_status(video_id):
    v = _video(video_id)
    return jsonify(analysis_status=v.analysis_status, safety_status=v.safety_status,
                   error=v.analysis_error, people=len(v.detected_faces or []))


@bp.get("/videos/<video_id>/file")
@login_required
def video_file(video_id):
    v = _video(video_id)
    return _file_response(v.video_key, mimetype="video/mp4")


@bp.get("/videos/<video_id>/people/<int:idx>.jpg")
@login_required
def person_thumb(video_id, idx):
    v = _video(video_id)
    p = next((p for p in v.detected_faces if p["index"] == idx), None)
    if p is None:
        abort(404)
    return _file_response(p["thumb_key"], mimetype="image/jpeg")


@bp.post("/videos/<video_id>/delete")
@login_required
def delete_video(video_id):
    v = _video(video_id)
    from .models import Purge
    g.db.add(Purge(key=v.video_key))
    for p in v.detected_faces or []:
        g.db.add(Purge(key=p["thumb_key"]))
    g.db.delete(v)
    g.db.commit()
    flash("動画を削除しました", "ok")
    return redirect(url_for("views.home"))


@bp.post("/swaps")
@login_required
def start_swap():
    v = _video(request.form.get("video_id", ""))
    try:
        idx = int(request.form.get("target_face_index", "-1"))
        job = create_swap(g.db, user=g.user, video=v, target_index=idx, aspect=request.form.get("aspect", ""),
                          photo_id=request.form.get("photo_id") or None,
                          idempotency_key=request.form.get("idempotency_key") or uuid.uuid4().hex,
                          cfg=ctx()["cfg"])
    except (SwapError, ValueError) as e:
        flash(str(e), "error")
        return redirect(url_for("views.video_page", video_id=v.id))
    return redirect(url_for("views.job_page", job_id=job.id))


# ---------- S05 own face ----------

@bp.get("/face")
@login_required
def face_page():
    cfg = ctx()["cfg"]
    engine_ok, engine_error = True, None
    try:
        ctx()["engine_factory"]()
    except FaceEngineUnavailable as e:
        engine_ok, engine_error = False, str(e)
    return render_template("face.html", face=g.user.face, engine_ok=engine_ok, engine_error=engine_error,
                           max_photo_mb=cfg.MAX_PHOTO_BYTES // (1024 * 1024))


@bp.post("/api/face/challenge")
@login_required
def face_challenge():
    if g.user.face is not None:
        return {"error": "顔はもう登録されています"}, 409
    ch = new_challenge(g.db, g.user.id)
    g.db.commit()
    return {"challenge_id": ch.id, "steps": ch.steps}


def _decode_data_url(s: str) -> bytes:
    if not s.startswith("data:image/jpeg;base64,"):
        raise ValueError("画像の形式が違います")
    data = base64.b64decode(s.split(",", 1)[1], validate=True)
    if len(data) > 3 * 1024 * 1024:
        raise ValueError("画像が大きすぎます")
    return data


@bp.post("/api/face")
@login_required
def face_register():
    body = request.get_json(silent=True) or {}
    try:
        frames = {k: _decode_data_url(v) for k, v in (body.get("frames") or {}).items()
                  if k in ("center", "turn_a", "turn_b")}
        engine = ctx()["engine_factory"]()
        register_face(g.db, user=g.user, engine=engine, checker=ctx()["checker"], storage=ctx()["storage"],
                      challenge_id=str(body.get("challenge_id", "")), frames=frames,
                      client_ok=bool(body.get("client_ok")), threshold=ctx()["cfg"].FACE_MATCH_THRESHOLD)
    except FaceEngineUnavailable as e:
        g.db.rollback()
        return {"error": str(e)}, 503
    except (LivenessError, FaceError, ValueError) as e:
        g.db.commit()  # the challenge stays used
        return {"error": str(e)}, 400
    return {"ok": True}


@bp.post("/face/photos")
@login_required
def face_photo_upload():
    f = request.files.get("photo")
    if f is None or not f.filename:
        flash("写真を選んでください", "error")
        return redirect(url_for("views.face_page"))
    if f.mimetype not in ("image/jpeg", "image/png", "image/webp"):
        flash("JPEG、PNG、WebP の写真だけ使えます", "error")
        return redirect(url_for("views.face_page"))
    try:
        engine = ctx()["engine_factory"]()
        photo = add_uploaded_photo(g.db, user=g.user, engine=engine, checker=ctx()["checker"],
                                   storage=ctx()["storage"], data=f.read(),
                                   threshold=ctx()["cfg"].FACE_MATCH_THRESHOLD,
                                   max_bytes=ctx()["cfg"].MAX_PHOTO_BYTES)
    except (FaceEngineUnavailable, FaceError, ValueError) as e:
        g.db.rollback()
        flash(str(e), "error")
        return redirect(url_for("views.face_page"))
    flash(f"写真を追加しました（一致度 {photo.match_score:.2f}）", "ok")
    return redirect(url_for("views.face_page"))


@bp.post("/face/photos/<photo_id>/primary")
@login_required
def face_photo_primary(photo_id):
    try:
        set_primary(g.db, g.user, photo_id)
    except FaceError as e:
        flash(str(e), "error")
    return redirect(url_for("views.face_page"))


@bp.post("/face/photos/<photo_id>/delete")
@login_required
def face_photo_delete(photo_id):
    try:
        delete_photo(g.db, g.user, photo_id)
        flash("写真を削除しました", "ok")
    except FaceError as e:
        flash(str(e), "error")
    return redirect(url_for("views.face_page"))


@bp.post("/face/delete")
@login_required
def face_delete():
    delete_face(g.db, g.user)
    flash("顔の写真と特徴データを削除しました", "ok")
    return redirect(url_for("views.face_page"))


@bp.get("/face/photos/<photo_id>.jpg")
@login_required
def face_photo_file(photo_id):
    p = g.db.get(FacePhoto, photo_id)
    if p is None or p.face.user_id != g.user.id:
        abort(404)
    return _file_response(p.image_key, mimetype="image/jpeg")


# ---------- S06 / S07 job ----------

@bp.get("/swaps/<job_id>")
@login_required
def job_page(job_id):
    return render_template("job.html", job=_job(job_id))


@bp.get("/api/swaps/<job_id>")
@login_required
def job_status(job_id):
    j = _job(job_id)
    return jsonify(status=j.status, error=j.error, has_output=j.output is not None)


@bp.post("/swaps/<job_id>/cancel")
@login_required
def job_cancel(job_id):
    j = _job(job_id)
    if j.status in ("queued", "submitted", "processing"):
        j.status = "cancelled"
        g.db.commit()
    return redirect(url_for("views.job_page", job_id=j.id))


@bp.get("/outputs/<oid>/view")
@login_required
def output_view(oid):
    o = g.db.get(Output, oid)
    if o is None or o.user_id != g.user.id:
        abort(404)
    return _file_response(o.video_key, mimetype="video/mp4")


@bp.get("/outputs/<oid>/download")
@login_required
def output_download(oid):
    o = g.db.get(Output, oid)
    if o is None or o.user_id != g.user.id:
        abort(404)
    stamp = o.created_at.strftime("%Y%m%d-%H%M")
    return _file_response(o.video_key, download_name=f"ai-generated-{stamp}.mp4", mimetype="video/mp4")


# ---------- S08 library ----------

@bp.get("/library")
@login_required
def library():
    outputs = g.db.scalars(select(Output).where(Output.user_id == g.user.id)
                           .order_by(Output.created_at.desc())).all()
    videos = g.db.scalars(select(SourceVideo).where(SourceVideo.user_id == g.user.id)
                          .order_by(SourceVideo.created_at.desc())).all()
    return render_template("library.html", outputs=outputs, videos=videos)


@bp.post("/outputs/<oid>/delete")
@login_required
def output_delete(oid):
    o = g.db.get(Output, oid)
    if o is None or o.user_id != g.user.id:
        abort(404)
    from .models import Purge
    g.db.add(Purge(key=o.video_key))
    g.db.delete(o)
    g.db.commit()
    flash("作品を削除しました", "ok")
    return redirect(url_for("views.library"))


# ---------- usage ----------

@bp.get("/usage")
@login_required
def usage():
    start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = g.db.execute(select(UsageEvent.service, func.sum(UsageEvent.cost_micro_usd), func.count())
                        .where(UsageEvent.user_id == g.user.id, UsageEvent.created_at >= start)
                        .group_by(UsageEvent.service)).all()
    cfg = ctx()["cfg"]
    return render_template("usage.html", rows=rows, today=spent_today_micro(g.db, g.user.id) / 1_000_000,
                           limit=cfg.DAILY_SPEND_LIMIT_USD)


@bp.get("/healthz")
def healthz():
    return Response("ok", mimetype="text/plain")
