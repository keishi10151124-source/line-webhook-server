"""Liveness check for registering the owner's face by camera.

The browser asks the person to look straight, turn one way, turn the other way and blink,
in a random order, and sends one frame per pose step. The server checks, independently of the
browser's own result:

- the challenge is fresh, belongs to this user, and is used only once
- every frame has exactly one face
- "center" faces the camera; the two turn steps point in opposite directions
- every frame is the same person (so nobody can swap in a photo halfway)

Blinks can't be checked with 5 landmarks, so that step relies on the browser.
A determined person can still fool a browser-based check. It is a guard, not proof.
"""
import secrets
from dataclasses import dataclass
from datetime import timedelta

from .models import LivenessChallenge, utcnow

POSE_STEPS = ["center", "turn_a", "turn_b"]
CENTER_MAX_YAW = 0.12
TURN_MIN_YAW = 0.18
SAME_PERSON_MIN = 0.38
CHALLENGE_TTL = timedelta(minutes=3)


class LivenessError(ValueError):
    pass


def new_challenge(session, user_id: str) -> LivenessChallenge:
    rng = secrets.SystemRandom()
    turns = ["turn_a", "turn_b"]
    rng.shuffle(turns)
    steps = ["center"] + turns
    steps.insert(rng.randrange(1, len(steps) + 1), "blink")
    ch = LivenessChallenge(id=secrets.token_urlsafe(24), user_id=user_id, steps=steps,
                           expires_at=utcnow() + CHALLENGE_TTL)
    session.add(ch)
    session.flush()
    return ch


@dataclass
class LivenessResult:
    center_image: bytes
    center_embedding: object
    challenge: LivenessChallenge


def _aware(dt):
    from datetime import timezone
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def verify(session, engine, user_id: str, challenge_id: str, frames: dict[str, bytes], client_ok: bool):
    from .faces import decode_image

    ch = session.get(LivenessChallenge, challenge_id)
    if ch is None or ch.user_id != user_id:
        raise LivenessError("確認の手順が見つかりません。最初からやり直してください")
    if ch.used_at is not None:
        raise LivenessError("この確認はもう使われています。最初からやり直してください")
    if _aware(ch.expires_at) < utcnow():
        raise LivenessError("時間切れです。最初からやり直してください")
    ch.used_at = utcnow()  # single use, even when it fails
    session.flush()

    if not client_ok:
        raise LivenessError("ブラウザでの確認が完了していません")
    missing = [s for s in POSE_STEPS if s not in frames]
    if missing:
        raise LivenessError("撮影が足りません: " + ", ".join(missing))

    found = {}
    for step in POSE_STEPS:
        img = decode_image(frames[step])
        faces = engine.detect(img)
        if len(faces) == 0:
            raise LivenessError("顔が写っていないコマがあります。明るい場所でやり直してください")
        if len(faces) > 1:
            raise LivenessError("2人以上写っているコマがあります。1人で撮影してください")
        found[step] = (img, faces[0])

    if abs(found["center"][1].yaw) > CENTER_MAX_YAW:
        raise LivenessError("正面のコマで、顔がカメラを向いていません")
    ya, yb = found["turn_a"][1].yaw, found["turn_b"][1].yaw
    if abs(ya) < TURN_MIN_YAW or abs(yb) < TURN_MIN_YAW or (ya > 0) == (yb > 0):
        raise LivenessError("顔を左右に向けたコマが確認できませんでした")

    center_img, center_face = found["center"]
    center_emb = engine.embed(center_img, center_face)
    for step in ("turn_a", "turn_b"):
        img, face = found[step]
        if engine.similarity(center_emb, engine.embed(img, face)) < SAME_PERSON_MIN:
            raise LivenessError("途中で別の人に入れ替わったように見えます")

    return LivenessResult(frames["center"], center_emb, ch)
