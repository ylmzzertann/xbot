"""Testler icin ortak fixture'lar.

Onemli: testler proje kokundeki data/*.txt listelerini kullanir ama
config.yaml dosyasina BAGIMLI DEGILDIR (o dosya kullaniciya ait).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from xbot.config import AppConfig  # noqa: E402
from xbot.detector.engine import DecisionEngine  # noqa: E402
from xbot.models import Tweet  # noqa: E402


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def data_dir(project_root: Path) -> Path:
    return project_root / "data"


@pytest.fixture
def config_data() -> dict:
    """Testlerde kullanilan temel ayar sozlugu."""
    return {
        "search_queries": ["Okan Buruk"],
        "target_names": ["okan", "buruk"],
        "mode": "dry-run",
        "time_window_minutes": 60,
    }


@pytest.fixture
def app_config(config_data: dict, project_root: Path) -> AppConfig:
    """Proje kokundeki gercek kelime listelerini kullanan ayar nesnesi."""
    return AppConfig.from_dict(config_data, base_dir=project_root)


@pytest.fixture
def engine(app_config: AppConfig) -> DecisionEngine:
    return DecisionEngine.from_config(app_config)


@pytest.fixture
def make_tweet():
    """Test icin kolay tweet uretici."""

    counter = {"n": 0}

    def _make(text: str, username: str = "deneme_hesap") -> Tweet:
        counter["n"] += 1
        return Tweet(tweet_id=str(counter["n"]), username=username, text=text)

    return _make


@pytest.fixture
def decide(engine: DecisionEngine, make_tweet):
    """Metni dogrudan karara ceviren kisayol."""

    def _decide(text: str):
        return engine.evaluate(make_tweet(text))

    return _decide
