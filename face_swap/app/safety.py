"""Safety check before any swap: looks at still frames and face photos.

Blocks: sexual content, anyone who looks under 18, and footage that looks like a real public
figure, news or someone else's identity. Fails closed: no answer, an error or a refusal
all count as blocked.
"""
import base64
from dataclasses import dataclass

from pydantic import BaseModel, Field

SYSTEM_PROMPT = """You review still frames for a personal video face-swap tool. The owner may only put
their own face into footage they have the rights to. Judge only what is visible.

Flag:
- sexual: nudity, sexual activity, or sexualised poses
- minor_present: any person who could reasonably be under 18
- public_figure_or_news: footage that looks like a news broadcast, an identifiable celebrity
  or politician, or other material whose purpose seems to be impersonating a real person
- violence_or_harm: graphic violence, self-harm

When unsure, flag it. Give a short reason in Japanese."""


class Verdict(BaseModel):
    sexual: bool
    minor_present: bool
    public_figure_or_news: bool
    violence_or_harm: bool
    reason: str = Field(description="短い理由（日本語）")


@dataclass
class SafetyOutcome:
    passed: bool
    result: dict
    input_tokens: int = 0
    output_tokens: int = 0


class ClaudeSafetyChecker:
    name = "claude"

    def __init__(self, model: str, client=None):
        self.model = model
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def check_images(self, images: list[bytes], purpose: str) -> SafetyOutcome:
        if not images:
            return SafetyOutcome(False, {"reason": "確認する画像がありません"})
        content = []
        for img in images[:12]:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.standard_b64encode(img).decode()}})
        content.append({"type": "text", "text": f"Purpose: {purpose}. Review all images above together."})
        try:
            resp = self.client.messages.parse(
                model=self.model,
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                output_config={"effort": "low"},
                output_format=Verdict,
                messages=[{"role": "user", "content": content}],
            )
        except Exception as e:  # network, auth, rate limit: fail closed
            return SafetyOutcome(False, {"reason": "安全チェックを実行できませんでした", "error": type(e).__name__})
        usage = getattr(resp, "usage", None)
        tin = getattr(usage, "input_tokens", 0) or 0
        tout = getattr(usage, "output_tokens", 0) or 0
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            return SafetyOutcome(False, {"reason": "安全チェックが判定を拒否しました"}, tin, tout)
        v: Verdict = resp.parsed_output
        flagged = v.sexual or v.minor_present or v.public_figure_or_news or v.violence_or_harm
        return SafetyOutcome(not flagged, v.model_dump(), tin, tout)


class DevAllowChecker:
    """Development only. Config.validate() refuses it in production."""
    name = "dev_allow"

    def check_images(self, images, purpose):
        return SafetyOutcome(bool(images), {"reason": "開発用：安全チェックを省略しました", "dev": True})


def make_checker(cfg):
    if cfg.SAFETY == "dev_allow":
        return DevAllowChecker()
    return ClaudeSafetyChecker(cfg.CLAUDE_MODEL)
