import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="ballpark-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["RATE_LIMIT_GAMES_PER_HOUR"] = "0"
os.environ["RATE_LIMIT_GUESSES_PER_HOUR"] = "0"
os.environ["MIN_POOL_PER_OPTION"] = "50"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core import fx  # noqa: E402
from app.core.db import Base, get_db, make_engine  # noqa: E402
from app.core.security import limiter  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as s:
        yield s


@pytest.fixture
def client(engine):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _get_db():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    limiter.reset()
    fx.clear_cache()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    fx.clear_cache()


@pytest.fixture
def seeded(db):
    from app.seed import seed

    seed(db)
    return db


# ---------------------------------------------------------------------------------------------
# Local HTTP test server (for PoliteClient / robots.txt / example_html tests)
# ---------------------------------------------------------------------------------------------
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class _Server:
    """Serves `routes` (path -> (status, body, headers)) and falls back to files in `root`."""

    def __init__(self, root: Path | None = None):
        self.root = root
        self.routes: dict[str, tuple[int, str, dict]] = {}
        self.hits: list[tuple[str, dict]] = []
        self.sequences: dict[str, list[tuple[int, str]]] = {}
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def do_GET(self):  # noqa: N802
                server.hits.append((self.path, dict(self.headers)))
                if self.path in server.sequences and server.sequences[self.path]:
                    status, body = server.sequences[self.path].pop(0)
                    return self._send(status, body, {})
                if self.path in server.routes:
                    status, body, headers = server.routes[self.path]
                    return self._send(status, body, headers)
                if server.root is not None:
                    f = (server.root / self.path.lstrip("/").split("?")[0]).resolve()
                    if f.is_file() and server.root.resolve() in f.parents:
                        return self._send(200, f.read_text(encoding="utf-8"), {})
                return self._send(404, "not found", {})

            def _send(self, status, body, headers):
                data = body.encode()
                self.send_response(status)
                self.send_header("Content-Type", headers.pop("Content-Type", "text/html"))
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self.thread.start()

    def paths(self) -> list[str]:
        return [p for p, _ in self.hits]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = _Server()
    yield s
    s.close()


@pytest.fixture
def fixture_site():
    s = _Server(root=FIXTURES)
    yield s
    s.close()
