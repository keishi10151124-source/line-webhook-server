"""Face registration and reference photos."""
import uuid

from .faces import decode_image, from_bytes, to_bytes
from .liveness import verify
from .models import Face, FacePhoto, Purge, UsageEvent, User, utcnow

CLAUDE_IN_PER_TOKEN_MICRO = 4      # $4 / 1M input tokens
CLAUDE_OUT_PER_TOKEN_MICRO = 20    # $20 / 1M output tokens


class FaceError(ValueError):
    pass


def record_claude_usage(session, user_id, outcome, job_id=None):
    if not (outcome.input_tokens or outcome.output_tokens):
        return
    session.add(UsageEvent(user_id=user_id, job_id=job_id, service="claude",
                           units=outcome.input_tokens + outcome.output_tokens, unit="tokens",
                           cost_micro_usd=outcome.input_tokens * CLAUDE_IN_PER_TOKEN_MICRO
                           + outcome.output_tokens * CLAUDE_OUT_PER_TOKEN_MICRO))


def register_face(session, *, user: User, engine, checker, storage, challenge_id: str,
                  frames: dict[str, bytes], client_ok: bool, threshold: float) -> Face:
    if user.face is not None:
        raise FaceError("顔はもう登録されています。登録し直すときは、先に削除してください")
    result = verify(session, engine, user.id, challenge_id, frames, client_ok)

    outcome = checker.check_images([result.center_image], "registering the owner's own face")
    record_claude_usage(session, user.id, outcome)
    if not outcome.passed or outcome.result.get("minor_present"):
        session.commit()  # keep the used challenge and the usage record
        raise FaceError("この顔は登録できません: " + str(outcome.result.get("reason", "")))

    face = Face(user_id=user.id, source="camera", liveness_challenge_id=result.challenge.id,
                liveness_passed_at=utcnow(), age_check_passed=True,
                embedding=to_bytes(result.center_embedding))
    session.add(face)
    session.flush()
    key = f"faces/{user.id}/{uuid.uuid4().hex}.jpg"
    storage.put_bytes(key, result.center_image)
    session.add(FacePhoto(face_id=face.id, source="camera", image_key=key, match_score=None,
                          match_threshold=threshold, safety_status="passed", is_primary=True))
    session.commit()
    return face


def add_uploaded_photo(session, *, user: User, engine, checker, storage, data: bytes,
                       threshold: float, max_bytes: int) -> FacePhoto:
    """Accept an uploaded photo only if it is the same person as the camera-registered face."""
    face = user.face
    if face is None:
        raise FaceError("先にカメラで自分の顔を登録してください。写真は、その顔と同じ人か確かめてから追加します")
    if len(data) > max_bytes:
        raise FaceError("写真が大きすぎます")
    img = decode_image(data)
    found = engine.detect(img)
    if len(found) == 0:
        raise FaceError("写真に顔が見つかりませんでした")
    if len(found) > 1:
        raise FaceError("写真に2人以上写っています。自分だけが写っている写真にしてください")
    score = engine.similarity(from_bytes(face.embedding), engine.embed(img, found[0]))
    if score < threshold:
        # not stored anywhere
        raise FaceError("登録した顔と同じ人だと確認できませんでした。自分の写真だけを追加できます")

    outcome = checker.check_images([data], "adding a reference photo of the owner's own face")
    record_claude_usage(session, user.id, outcome)
    if not outcome.passed:
        session.commit()
        raise FaceError("この写真は使えません: " + str(outcome.result.get("reason", "")))

    import cv2
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    key = f"faces/{user.id}/{uuid.uuid4().hex}.jpg"
    storage.put_bytes(key, jpg.tobytes())
    photo = FacePhoto(face_id=face.id, source="upload", image_key=key, match_score=score,
                      match_threshold=threshold, safety_status="passed", is_primary=False)
    session.add(photo)
    session.commit()
    return photo


def set_primary(session, user: User, photo_id: str) -> None:
    face = user.face
    if face is None:
        raise FaceError("顔が登録されていません")
    found = False
    for p in face.photos:
        p.is_primary = p.id == photo_id
        found = found or p.is_primary
    if not found:
        raise FaceError("写真が見つかりません")
    session.commit()


def delete_photo(session, user: User, photo_id: str) -> None:
    face = user.face
    photo = next((p for p in (face.photos if face else []) if p.id == photo_id), None)
    if photo is None:
        raise FaceError("写真が見つかりません")
    if photo.source == "camera":
        raise FaceError("カメラで撮った写真は消せません。顔ごと削除してください")
    session.add(Purge(key=photo.image_key))
    session.delete(photo)
    session.commit()


def delete_face(session, user: User) -> None:
    face = user.face
    if face is None:
        return
    for p in face.photos:
        session.add(Purge(key=p.image_key))
    session.delete(face)
    session.commit()
