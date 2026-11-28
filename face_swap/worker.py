"""Background worker: analyses uploaded videos and runs swaps. Run alongside the web process."""
import logging
import sys
import tempfile
import time

from app.config import Config
from app.faces import get_engine
from app.jobs import run_pending
from app.models import Base, make_session_factory
from app.providers import make_provider
from app.safety import make_checker
from app.storage import make_storage


def main(once: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config()
    cfg.validate()
    from app.c2pa_cert import ensure_cert
    ensure_cert(cfg)
    engine, Session = make_session_factory(cfg.DATABASE_URL)
    Base.metadata.create_all(engine)
    kw = dict(storage=make_storage(cfg), engine_factory=lambda: get_engine(cfg.FACE_MODELS_DIR),
              checker=make_checker(cfg), provider=make_provider(cfg), cfg=cfg,
              workdir=tempfile.mkdtemp(prefix="face_swap_worker_"))
    while True:
        try:
            n = run_pending(Session, **kw)
        except Exception:
            logging.exception("worker round failed")
            n = 0
        if once:
            return
        time.sleep(0.5 if n else 2)


if __name__ == "__main__":
    main(once="--once" in sys.argv)
