"""Creates a personal C2PA signing certificate.
Usage: python scripts/make_c2pa_cert.py [out_dir]   (default: secrets/)
The app also creates one by itself on first start if none is configured."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.c2pa_cert import main  # noqa: E402

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent.parent / "secrets"))
