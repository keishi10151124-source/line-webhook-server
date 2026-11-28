"""Video helpers: probe, frame grabs, the AI watermark and C2PA signing."""
import json
import subprocess
from pathlib import Path

WATERMARK_TEXT = "AI-GENERATED"
OUTPUT_SIZES = {"9:16": (720, 1280), "16:9": (1280, 720)}


class MediaError(RuntimeError):
    pass


def probe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        raise MediaError("動画を読み込めませんでした（形式が未対応か、壊れています）")
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        raise MediaError("映像が入っていません")
    duration = float((data.get("format") or {}).get("duration") or 0)
    return {"width": int(streams[0]["width"]), "height": int(streams[0]["height"]), "duration": duration}


def grab_frames(path: str, outdir: str, every_s: float = 1.0, max_frames: int = 30) -> list[Path]:
    Path(outdir).mkdir(parents=True, exist_ok=True)
    pattern = str(Path(outdir) / "f%03d.jpg")
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vf", f"fps=1/{every_s},scale='min(1280,iw)':-2",
         "-frames:v", str(max_frames), "-q:v", "3", pattern],
        capture_output=True, text=True, timeout=300,
    )
    if r.returncode != 0:
        raise MediaError("コマを取り出せませんでした")
    return sorted(Path(outdir).glob("f*.jpg"))


def render_output(src: str, dest: str, aspect: str, font: str) -> int:
    """Fit to 9:16 or 16:9 HD (letterboxed, never cropped) and burn in the AI watermark.
    Returns the output height."""
    w, h = OUTPUT_SIZES[aspect]
    if not Path(font).exists():
        raise MediaError(f"透かし用のフォントがありません: {font}")
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,"
        # top-left, so it never overlaps a provider's own bottom-right mark
        f"drawtext=fontfile={font}:text='{WATERMARK_TEXT}':x=36:y=36:fontsize=28:fontcolor=white"
        f":box=1:boxcolor=black@0.55:boxborderw=12"
    )
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(dest)],
        capture_output=True, text=True, timeout=1800,
    )
    if r.returncode != 0:
        raise MediaError("書き出しに失敗しました: " + r.stderr[-300:])
    return h


def c2pa_sign(src: str, dest: str, chain_path: str, key_path: str, title: str) -> None:
    """Attach C2PA Content Credentials saying this video was made by an AI model."""
    import c2pa

    if not (Path(chain_path).exists() and Path(key_path).exists()):
        raise MediaError("C2PA の署名用ファイルがありません。scripts/make_c2pa_cert.py を実行してください")
    info = c2pa.C2paSignerInfo(
        alg=b"es256", sign_cert=Path(chain_path).read_bytes(),
        private_key=Path(key_path).read_bytes(), ta_url=None,
    )
    signer = c2pa.Signer.from_info(info)
    manifest = {
        "claim_generator_info": [{"name": "face-swap", "version": "0.1"}],
        "title": title,
        "assertions": [{
            "label": "c2pa.actions",
            "data": {"actions": [{
                "action": "c2pa.created",
                "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia",
                "softwareAgent": {"name": "face-swap"},
            }]},
        }],
    }
    builder = c2pa.Builder(json.dumps(manifest))
    builder.sign_file(src, dest, signer)


def read_c2pa(path: str) -> dict:
    import c2pa

    return json.loads(c2pa.Reader(path).json())
