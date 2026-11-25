import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
CORPUS = Path(__file__).resolve().parents[2] / "data" / "corpus.jsonl.gz"


@pytest.fixture(scope="session")
def lib():
    from nerdcore.library import Library
    return Library(CORPUS)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "h.db"))
    monkeypatch.setenv("GROQ_API_KEY", "")
    from nerdcore import config
    config.get_settings.cache_clear()
    import importlib
    import nerdcore.api as api
    importlib.reload(api)
    from fastapi.testclient import TestClient
    with TestClient(api.app) as c:
        yield c
    config.get_settings.cache_clear()


H = {"X-Reader-Id": "reader-test-0001"}
