import io
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.config import Config
from app.media import read_c2pa
from app.models import Face, FacePhoto, Output, Purge, SourceVideo, SwapJob, User
from app.safety import ClaudeSafetyChecker

from .conftest import Client, data_url, jpeg, make_video, register_face, run_jobs


# ---------- config and login ----------

def test_production_refuses_dev_shortcuts():
    c = Config()
    c.APP_ENV, c.SECRET_KEY, c.SAFETY, c.FACESWAP_PROVIDER, c.STORAGE = "production", "x", "dev_allow", "dev_passthrough", "local"
    with pytest.raises(RuntimeError) as e:
        c.validate()
    msg = str(e.value)
    assert "SAFETY" in msg and "FACESWAP_PROVIDER" in msg and "STORAGE" in msg


def test_pages_need_login(app):
    c = app.test_client()
    assert c.get("/").status_code == 302
    assert c.get("/api/swaps/x").status_code == 401


def test_wrong_password(app):
    c = app.test_client()
    c.get("/login")
    r = c.post("/login", data={"email": "owner@example.com", "password": "nope"})
    assert r.status_code == 401


def test_post_without_csrf_is_rejected(client):
    r = client.c.post("/api/face/challenge")
    assert r.status_code == 400


def test_all_screens_render(client):
    for url in ["/", "/upload", "/face", "/library", "/usage"]:
        r = client.get(url)
        assert r.status_code == 200, url


# ---------- registering the face by camera ----------

def test_register_face_by_camera(client, ctx):
    r = register_face(client)
    assert r.status_code == 200, r.get_json()
    with ctx["Session"]() as s:
        face = s.query(Face).one()
        assert face.source == "camera"
        assert [p.source for p in face.photos] == ["camera"]
        assert face.photos[0].is_primary


def test_only_one_face(client):
    assert register_face(client).status_code == 200
    r = client.post("/api/face/challenge")
    assert r.status_code == 409


def test_challenge_is_single_use(client):
    ch = client.post("/api/face/challenge").get_json()
    frames = {"center": data_url(jpeg(0, 0)), "turn_a": data_url(jpeg(0, 0.3)), "turn_b": data_url(jpeg(0, 0.3))}
    r1 = client.post("/api/face", json={"challenge_id": ch["challenge_id"], "frames": frames, "client_ok": True})
    assert r1.status_code == 400  # both turns the same way
    frames["turn_b"] = data_url(jpeg(0, -0.3))
    r2 = client.post("/api/face", json={"challenge_id": ch["challenge_id"], "frames": frames, "client_ok": True})
    assert r2.status_code == 400
    assert "使われています" in r2.get_json()["error"]


@pytest.mark.parametrize("frames, needle", [
    ({"center": (0, 0.3), "turn_a": (0, 0.3), "turn_b": (0, -0.3)}, "正面"),
    ({"center": (0, 0.0), "turn_a": (0, 0.05), "turn_b": (0, -0.3)}, "左右"),
    ({"center": (0, 0.0), "turn_a": (1, 0.3), "turn_b": (0, -0.3)}, "別の人"),
    ({"center": (0, 0.0, True), "turn_a": (0, 0.3), "turn_b": (0, -0.3)}, "2人以上"),
])
def test_liveness_rejects(client, frames, needle):
    ch = client.post("/api/face/challenge").get_json()
    body = {k: data_url(jpeg(*v)) for k, v in frames.items()}
    r = client.post("/api/face", json={"challenge_id": ch["challenge_id"], "frames": body, "client_ok": True})
    assert r.status_code == 400
    assert needle in r.get_json()["error"]


def test_liveness_needs_browser_check(client):
    ch = client.post("/api/face/challenge").get_json()
    frames = {"center": data_url(jpeg(0, 0)), "turn_a": data_url(jpeg(0, 0.3)), "turn_b": data_url(jpeg(0, -0.3))}
    r = client.post("/api/face", json={"challenge_id": ch["challenge_id"], "frames": frames, "client_ok": False})
    assert r.status_code == 400


def test_registration_blocked_by_safety(client, checker, ctx):
    checker.block = True
    r = register_face(client)
    assert r.status_code == 400
    with ctx["Session"]() as s:
        assert s.query(Face).count() == 0


# ---------- uploading face photos ----------

def _upload_photo(client, data):
    return client.post("/face/photos", data={"photo": (io.BytesIO(data), "me.jpg", "image/jpeg")},
                       content_type="multipart/form-data", follow_redirects=True)


def test_upload_needs_camera_face_first(client, ctx):
    r = _upload_photo(client, jpeg(0, 0))
    assert "先にカメラで" in r.get_data(as_text=True)
    with ctx["Session"]() as s:
        assert s.query(FacePhoto).count() == 0


def test_upload_matching_photo_is_added(client, ctx):
    register_face(client, ident=0)
    r = _upload_photo(client, jpeg(0, 0.05))
    assert "写真を追加しました" in r.get_data(as_text=True)
    with ctx["Session"]() as s:
        up = s.query(FacePhoto).filter_by(source="upload").one()
        assert up.match_score >= up.match_threshold


def test_upload_someone_else_is_rejected_and_not_stored(client, ctx):
    register_face(client, ident=0)
    files_before = sorted(p.name for p in ctx["storage"].root.rglob("*") if p.is_file())
    r = _upload_photo(client, jpeg(2, 0.0))
    assert "同じ人だと確認できませんでした" in r.get_data(as_text=True)
    with ctx["Session"]() as s:
        assert s.query(FacePhoto).filter_by(source="upload").count() == 0
    files_after = sorted(p.name for p in ctx["storage"].root.rglob("*") if p.is_file())
    assert files_before == files_after


def test_upload_group_photo_is_rejected(client):
    register_face(client, ident=0)
    r = _upload_photo(client, jpeg(0, 0.0, two=True))
    assert "2人以上" in r.get_data(as_text=True)


def test_db_refuses_unmatched_upload(ctx, client):
    register_face(client)
    with ctx["Session"]() as s:
        face = s.query(Face).one()
        s.add(FacePhoto(face_id=face.id, source="upload", image_key="k", match_score=0.1,
                        match_threshold=0.45, safety_status="passed"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_db_refuses_non_camera_face(ctx, client):
    with ctx["Session"]() as s:
        user = s.query(User).one()
        from app.models import utcnow
        s.add(Face(user_id=user.id, source="upload", liveness_challenge_id="c", liveness_passed_at=utcnow(),
                   age_check_passed=True, embedding=b"x"))
        with pytest.raises(IntegrityError):
            s.commit()


# ---------- the whole loop ----------

def _upload_video(client, tmp_path, **kw):
    p = make_video(tmp_path / "in.mp4", **kw)
    r = client.post("/upload", data={"video": (open(p, "rb"), "in.mp4", "video/mp4"), "rights_confirmed": "1"},
                    content_type="multipart/form-data")
    assert r.status_code == 302, r.data
    return r.headers["Location"].rsplit("/", 1)[-1]


def test_full_loop_outputs_labelled_video(client, ctx, tmp_path):
    register_face(client, ident=0)
    vid = _upload_video(client, tmp_path, ident=1, seconds=3)
    run_jobs(ctx, rounds=1)
    with ctx["Session"]() as s:
        v = s.get(SourceVideo, vid)
        assert v.analysis_status == "done", v.analysis_error
        assert v.safety_status == "passed"
        assert len(v.detected_faces) == 1
    assert client.get(f"/videos/{vid}").status_code == 200

    r = client.post("/swaps", data={"video_id": vid, "target_face_index": "0", "aspect": "9:16",
                                    "idempotency_key": "k1"})
    assert r.status_code == 302
    job_id = r.headers["Location"].rsplit("/", 1)[-1]
    run_jobs(ctx, rounds=3)
    with ctx["Session"]() as s:
        job = s.get(SwapJob, job_id)
        assert job.status == "done", job.error
        out = s.query(Output).one()
        assert out.watermarked and out.c2pa_signed and out.height == 1280
        path = ctx["storage"].local_path(out.video_key)
    manifest = read_c2pa(str(path))
    assert "trainedAlgorithmicMedia" in str(manifest)
    assert client.get(f"/swaps/{job_id}").status_code == 200
    d = client.get(f"/outputs/{out.id}/download")
    assert d.status_code == 200 and "ai-generated" in d.headers["Content-Disposition"]


def test_same_key_does_not_start_twice(client, ctx, tmp_path):
    register_face(client)
    vid = _upload_video(client, tmp_path)
    run_jobs(ctx, rounds=1)
    data = {"video_id": vid, "target_face_index": "0", "aspect": "16:9", "idempotency_key": "same"}
    a = client.post("/swaps", data=data).headers["Location"]
    b = client.post("/swaps", data=data).headers["Location"]
    assert a == b
    with ctx["Session"]() as s:
        assert s.query(SwapJob).count() == 1


def test_blocked_video_cannot_be_used(client, ctx, checker, tmp_path):
    register_face(client)
    vid = _upload_video(client, tmp_path)
    checker.block = True
    run_jobs(ctx, rounds=1)
    r = client.post("/swaps", data={"video_id": vid, "target_face_index": "0", "aspect": "9:16",
                                    "idempotency_key": "x"}, follow_redirects=True)
    assert "安全チェックを通らなかった" in r.get_data(as_text=True)
    with ctx["Session"]() as s:
        assert s.query(SwapJob).count() == 0


def test_too_long_video_fails(client, ctx, tmp_path):
    ctx["cfg"].MAX_VIDEO_SECONDS = 2
    register_face(client)
    vid = _upload_video(client, tmp_path, seconds=4)
    run_jobs(ctx, rounds=1)
    with ctx["Session"]() as s:
        v = s.get(SourceVideo, vid)
        assert v.analysis_status == "failed" and "長すぎ" in v.analysis_error


def test_spend_limit(client, ctx, tmp_path):
    ctx["cfg"].DAILY_SPEND_LIMIT_USD = 0.01
    register_face(client)
    vid = _upload_video(client, tmp_path)
    run_jobs(ctx, rounds=1)
    r = client.post("/swaps", data={"video_id": vid, "target_face_index": "0", "aspect": "9:16",
                                    "idempotency_key": "y"}, follow_redirects=True)
    assert "上限" in r.get_data(as_text=True)


def test_rights_checkbox_required(client, tmp_path):
    p = make_video(tmp_path / "in.mp4")
    r = client.post("/upload", data={"video": (open(p, "rb"), "in.mp4", "video/mp4")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "権利の確認" in r.get_data(as_text=True)


def test_delete_face_purges_files_and_stops_jobs(client, ctx, tmp_path):
    register_face(client)
    vid = _upload_video(client, tmp_path)
    run_jobs(ctx, rounds=1)
    loc = client.post("/swaps", data={"video_id": vid, "target_face_index": "0", "aspect": "9:16",
                                      "idempotency_key": "z"}).headers["Location"]
    client.post("/face/delete")
    with ctx["Session"]() as s:
        assert s.query(Face).count() == 0 and s.query(FacePhoto).count() == 0
        assert s.query(Purge).count() >= 1
    run_jobs(ctx, rounds=2)
    with ctx["Session"]() as s:
        assert s.query(Purge).count() == 0
        job = s.get(SwapJob, loc.rsplit("/", 1)[-1])
        assert job.status == "failed" and "顔が削除" in job.error
    assert not any(p.is_file() for p in (ctx["storage"].root / "faces").rglob("*"))


def test_other_users_data_is_invisible(app, client, ctx, tmp_path):
    register_face(client)
    vid = _upload_video(client, tmp_path)
    with ctx["Session"]() as s:
        s.add(User(email="someone@example.com"))
        s.commit()
        other = s.query(User).filter_by(email="someone@example.com").one()
        s.query(SourceVideo).filter_by(id=vid).update({"user_id": other.id})
        s.commit()
    assert client.get(f"/videos/{vid}").status_code == 404
    assert client.get(f"/videos/{vid}/file").status_code == 404


def test_watermark_is_top_left(tmp_path, cfg):
    import cv2
    from app.media import render_output
    src = make_video(tmp_path / "plain.mp4", ident=2, seconds=1, size="720x1280")
    out = tmp_path / "out.mp4"
    render_output(str(src), str(out), "9:16", cfg.WATERMARK_FONT)
    cap = cv2.VideoCapture(str(out))
    ok, frame = cap.read()
    assert ok
    top_left = frame[30:70, 30:250].astype(float)
    bottom_right = frame[1280 - 70:1280 - 30, 720 - 250:720 - 30].astype(float)
    plain = frame[600:640, 300:420].astype(float)
    # the white text on a dark box makes the top-left busy; the bottom-right stays as flat as the rest
    # spread is measured per colour channel, so a flat colour scores ~0
    assert top_left.std(axis=(0, 1)).max() > 40
    assert bottom_right.std(axis=(0, 1)).max() < 5
    assert abs(bottom_right.mean() - plain.mean()) < 5


# ---------- the Claude safety checker fails closed ----------

class _Resp(SimpleNamespace):
    pass


def _checker_with(resp=None, exc=None):
    class Msgs:
        def parse(self, **kw):
            assert kw["model"] == "claude-opus-5-5"
            assert kw["output_config"] == {"effort": "low"}
            if exc:
                raise exc
            return resp
    return ClaudeSafetyChecker("claude-opus-5-5", client=SimpleNamespace(messages=Msgs()))


def test_claude_refusal_blocks():
    c = _checker_with(_Resp(stop_reason="refusal", parsed_output=None, usage=None))
    assert c.check_images([b"x"], "t").passed is False


def test_claude_error_blocks():
    c = _checker_with(exc=RuntimeError("down"))
    assert c.check_images([b"x"], "t").passed is False


def test_claude_flag_blocks_and_clean_passes():
    from app.safety import Verdict
    bad = Verdict(sexual=False, minor_present=True, public_figure_or_news=False, violence_or_harm=False, reason="未成年")
    ok = Verdict(sexual=False, minor_present=False, public_figure_or_news=False, violence_or_harm=False, reason="問題なし")
    usage = SimpleNamespace(input_tokens=10, output_tokens=5)
    assert _checker_with(_Resp(stop_reason="end_turn", parsed_output=bad, usage=usage)).check_images([b"x"], "t").passed is False
    assert _checker_with(_Resp(stop_reason="end_turn", parsed_output=ok, usage=usage)).check_images([b"x"], "t").passed is True


# ---------- Facemint adapter (request side) ----------

from app.providers import FacemintProvider, FacemintSettings, ProviderError, SwapInputs


def _inputs(**kw):
    base = dict(video_path="v.mp4", to_face_path="t.png", from_face_path="f.png",
                video_url="https://r2/v.mp4?sig", to_face_url="https://r2/t.png?sig",
                from_face_url="https://r2/f.png?sig", duration_s=4.2, workdir="/tmp")
    base.update(kw)
    return SwapInputs(**base)


def test_facemint_request_swaps_only_the_chosen_person():
    calls = []

    def http(method, url, headers, body):
        calls.append((method, url, headers, body))
        return 201, {"code": 0, "info": "ok", "data": {"taskId": "683b", "price": 2000}}

    p = FacemintProvider(FacemintSettings(api_key="k"), http=http)
    res = p.submit(_inputs())
    assert res.task_id == "683b" and res.price == 2000
    method, url, headers, body = calls[0]
    assert method == "POST" and url == "https://api.facemint.io/api/create-face-swap-task"
    assert headers == {"x-api-key": "k"}
    assert body["type"] == "video" and body["start_time"] == 0 and body["end_time"] == 5
    assert body["nsfw_check"] == 1
    assert body["swap_list"] == [{"from_face": "https://r2/f.png?sig", "to_face": "https://r2/t.png?sig"}]
    assert body["face_recognition"] < 0.8
    assert "callback_url" not in body


def test_facemint_needs_urls():
    p = FacemintProvider(FacemintSettings(api_key="k"), http=lambda *a: (201, {}))
    with pytest.raises(ProviderError):
        p.submit(_inputs(from_face_url=None))


@pytest.mark.parametrize("status, resp", [
    (201, {"code": 1, "info": "bad", "data": {}}),
    (401, {"code": 401, "info": "unauthorized"}),
    (201, {"code": 0, "info": "ok", "data": {}}),
])
def test_facemint_rejections_raise(status, resp):
    p = FacemintProvider(FacemintSettings(api_key="k"), http=lambda *a: (status, resp))
    with pytest.raises(ProviderError):
        p.submit(_inputs())


def test_facemint_needs_api_key():
    with pytest.raises(ProviderError):
        FacemintProvider(FacemintSettings(api_key=""))


def test_url_provider_files_live_until_the_job_ends(client, ctx, tmp_path):
    """Files a provider fetches by URL must not be deleted while the job is running."""
    class UrlProvider:
        name, needs_urls = "url_test", True
        def submit(self, inp):
            assert inp.to_face_url and inp.from_face_url and inp.video_url
            return SimpleNamespace(task_id="t1", price=7)
        def poll(self, task_id, workdir):
            return SimpleNamespace(status="processing", result_path=None, error=None)

    st = ctx["storage"]
    st.url = lambda key, expires=None: f"https://files.example/{key}"
    ctx["provider"] = UrlProvider()
    register_face(client)
    vid = _upload_video(client, tmp_path)
    run_jobs(ctx, rounds=1)
    loc = client.post("/swaps", data={"video_id": vid, "target_face_index": "0", "aspect": "9:16",
                                      "idempotency_key": "u"}).headers["Location"]
    job_id = loc.rsplit("/", 1)[-1]
    run_jobs(ctx, rounds=3)
    with ctx["Session"]() as s:
        job = s.get(SwapJob, job_id)
        assert job.status == "processing" and job.provider_price == 7
        user_id = job.user_id
    pngs = [st.local_path(f"jobs/{user_id}/{job_id}/{n}") for n in ("to_face.png", "from_face.png")]
    assert all(p.exists() for p in pngs)
    client.post(f"/swaps/{job_id}/cancel")
    run_jobs(ctx, rounds=1)
    assert not any(p.exists() for p in pngs)


# ---------- Facemint adapter (result side) ----------

def _task(state, file_url="https://cdn.example/out.mp4"):
    return 200, {"code": 0, "info": "success",
                 "data": {"id": "t", "state": state, "price": 100, "process": 50,
                          "result": {"file_url": file_url, "thumb_url": ""}}}


@pytest.mark.parametrize("reply, expected", [
    (_task(0), "processing"),
    (_task(1), "processing"),
    ((503, {}), "processing"),
    ((429, {}), "processing"),
    (_task(-1), "failed"),
    (_task(2), "failed"),
    (_task(7), "failed"),
    ((404, {"code": 404, "message": "not found"}), "failed"),
    (_task(3, file_url=""), "failed"),
    (_task(3, file_url="http://insecure/out.mp4"), "failed"),
])
def test_facemint_poll_states(reply, expected, tmp_path):
    calls = []

    def http(method, url, headers, body):
        calls.append((url, body))
        return reply

    p = FacemintProvider(FacemintSettings(api_key="k"), http=http)
    assert p.poll("t", str(tmp_path)).status == expected
    assert calls == [("https://api.facemint.io/api/get-task-info", {"task_id": "t"})]


def test_facemint_poll_done_downloads(tmp_path):
    p = FacemintProvider(FacemintSettings(api_key="k"), http=lambda *a: _task(3))
    got = []
    p.download = lambda url, dest: (got.append(url), open(dest, "wb").write(b"video"))
    res = p.poll("t", str(tmp_path))
    assert res.status == "done" and open(res.result_path, "rb").read() == b"video"
    assert got == ["https://cdn.example/out.mp4"]


def test_facemint_network_error_on_submit_is_not_retried():
    import urllib.error

    def http(*a):
        raise urllib.error.URLError("down")

    p = FacemintProvider(FacemintSettings(api_key="k"), http=http)
    with pytest.raises(ProviderError):
        p.submit(_inputs())


def test_production_facemint_needs_key():
    c = Config()
    c.APP_ENV, c.SECRET_KEY, c.SAFETY, c.STORAGE = "production", "x", "claude", "r2"
    c.OWNER_EMAIL, c.OWNER_PASSWORD_HASH = "a@b", "h"
    c.FACESWAP_PROVIDER, c.FACEMINT_API_KEY = "facemint", ""
    with pytest.raises(RuntimeError, match="FACEMINT_API_KEY"):
        c.validate()
    c.FACEMINT_API_KEY = "k"
    c.validate()


def _facemint_in_app(ctx, http, tmp_path):
    st = ctx["storage"]
    st.url = lambda key, expires=None: f"https://files.example/{key}"
    p = FacemintProvider(FacemintSettings(api_key="k"), http=http)
    p.download = lambda url, dest: __import__("shutil").copyfile(make_video(tmp_path / "result.mp4"), dest)
    ctx["provider"] = p
    return p


def _start(client, ctx, tmp_path, key):
    register_face(client)
    vid = _upload_video(client, tmp_path)
    run_jobs(ctx, rounds=1)
    loc = client.post("/swaps", data={"video_id": vid, "target_face_index": "0", "aspect": "9:16",
                                      "idempotency_key": key}).headers["Location"]
    return loc.rsplit("/", 1)[-1]


def test_full_loop_with_facemint(client, ctx, tmp_path):
    replies = iter([(201, {"code": 0, "info": "ok", "data": {"taskId": "fm1", "price": 2000}}),
                    _task(1), _task(3)])
    sent = []

    def http(method, url, headers, body):
        sent.append(url.rsplit("/", 1)[-1])
        return next(replies)

    _facemint_in_app(ctx, http, tmp_path)
    job_id = _start(client, ctx, tmp_path, "fm")
    with ctx["Session"]() as s:
        s.get(SwapJob, job_id).next_poll_at = None
        s.commit()
    run_jobs(ctx, rounds=1)          # submit + first poll (processing)
    with ctx["Session"]() as s:
        j = s.get(SwapJob, job_id)
        assert j.status == "processing" and j.provider_task_id == "fm1"
        j.next_poll_at = None
        s.commit()
    run_jobs(ctx, rounds=1)          # second poll (done) -> watermark, C2PA, store
    with ctx["Session"]() as s:
        j = s.get(SwapJob, job_id)
        assert j.status == "done", j.error
        assert j.output.watermarked and j.output.c2pa_signed
    assert sent == ["create-face-swap-task", "get-task-info", "get-task-info"]
    run_jobs(ctx, rounds=1)
    assert not any((ctx["storage"].root / "jobs").rglob("*.png"))


def test_facemint_failure_is_not_resubmitted(client, ctx, tmp_path):
    sent = []

    def http(method, url, headers, body):
        sent.append(url.rsplit("/", 1)[-1])
        if url.endswith("create-face-swap-task"):
            return 201, {"code": 0, "info": "ok", "data": {"taskId": "fm2", "price": 2000}}
        return _task(-1)

    _facemint_in_app(ctx, http, tmp_path)
    job_id = _start(client, ctx, tmp_path, "fm2")
    run_jobs(ctx, rounds=4)
    with ctx["Session"]() as s:
        j = s.get(SwapJob, job_id)
        assert j.status == "failed" and "Facemint" in j.error
    assert sent.count("create-face-swap-task") == 1


def test_stuck_job_times_out(client, ctx, tmp_path):
    from datetime import timedelta
    from app.models import utcnow

    def http(method, url, headers, body):
        if url.endswith("create-face-swap-task"):
            return 201, {"code": 0, "info": "ok", "data": {"taskId": "fm3", "price": 1}}
        return _task(1)

    _facemint_in_app(ctx, http, tmp_path)
    job_id = _start(client, ctx, tmp_path, "fm3")
    run_jobs(ctx, rounds=1)
    with ctx["Session"]() as s:
        j = s.get(SwapJob, job_id)
        j.created_at = utcnow() - timedelta(minutes=ctx["cfg"].SWAP_TIMEOUT_MINUTES + 1)
        j.next_poll_at = None
        s.commit()
    run_jobs(ctx, rounds=1)
    with ctx["Session"]() as s:
        assert "時間がかかりすぎた" in s.get(SwapJob, job_id).error


# ---------- setup without a terminal ----------

def test_plain_owner_password_is_hashed_and_dropped(monkeypatch):
    from werkzeug.security import check_password_hash
    monkeypatch.setenv("OWNER_PASSWORD", "a long enough password")
    monkeypatch.delenv("OWNER_PASSWORD_HASH", raising=False)
    c = Config()
    assert c.OWNER_PASSWORD == ""
    assert check_password_hash(c.OWNER_PASSWORD_HASH, "a long enough password")
    assert "a long enough password" not in repr(c)


def test_short_owner_password_is_refused(monkeypatch):
    monkeypatch.setenv("OWNER_PASSWORD", "short")
    monkeypatch.delenv("OWNER_PASSWORD_HASH", raising=False)
    c = Config()
    c.SECRET_KEY = "x"
    with pytest.raises(RuntimeError, match="12 characters"):
        c.validate()


def test_c2pa_cert_is_created_on_first_start(tmp_path):
    from app.c2pa_cert import ensure_cert
    c = Config()
    c.C2PA_CERT_CHAIN_PATH = str(tmp_path / "s" / "chain.pem")
    c.C2PA_PRIVATE_KEY_PATH = str(tmp_path / "s" / "key.pem")
    ensure_cert(c)
    assert (tmp_path / "s" / "chain.pem").exists() and (tmp_path / "s" / "key.pem").exists()
    before = (tmp_path / "s" / "chain.pem").read_bytes()
    ensure_cert(c)  # does not replace an existing certificate
    assert (tmp_path / "s" / "chain.pem").read_bytes() == before
