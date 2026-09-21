"""Dedektor arayuzu.

Yeni bir dedektor eklemek icin:

    from .base import Detector, AnalysisContext, register_detector

    @register_detector("benim_dedektorum")
    class MyDetector(Detector):
        name = "benim_dedektorum"
        kind = "content"          # "content" (karar uretir) | "context" (ipucu verir)

        def analyze(self, tweet, context=None):
            ctx = self.context_for(tweet, context)
            ...
            return Verdict(detector=self.name, level=Level.SUSPECT, ...)

Ileride eklenecek yapay zeka tabanli siniflandirici da ayni arayuzu
kullanacak; motor (engine.py) dedektorun icini bilmek zorunda degil.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

from ..models import Tweet, Verdict
from .normalizer import NormalizedText, normalize_text

#: "context" turundeki dedektorlerin uretebilecegi bayraklar
FLAG_TARGET = "target"  # tweette hedef isim geciyor
FLAG_POSITIVE = "positive_context"  # sevinc/olumlu baglam


@dataclass
class AnalysisContext:
    """Bir tweet icin dedektorler arasinda paylasilan is alani.

    Normalizasyon pahali olmasin diye bir kez yapilir ve burada saklanir.
    """

    tweet: Tweet
    _normalized: NormalizedText | None = None
    extras: dict[str, object] = field(default_factory=dict)

    @property
    def normalized(self) -> NormalizedText:
        if self._normalized is None:
            self._normalized = normalize_text(self.tweet.text)
        return self._normalized


class Detector(ABC):
    """Tum dedektorlerin ortak arayuzu."""

    #: Raporlarda gorunen kisa ad
    name: str = "detector"
    #: "content": karar seviyesi uretir. "context": sadece bayrak/ipucu uretir.
    kind: str = "content"

    @abstractmethod
    def analyze(self, tweet: Tweet, context: AnalysisContext | None = None) -> Verdict:
        """Tweeti inceleyip bir Verdict dondurur."""

    @staticmethod
    def context_for(
        tweet: Tweet, context: AnalysisContext | None = None
    ) -> AnalysisContext:
        """Verilen baglami dogrular, yoksa yenisini olusturur."""
        if context is not None and context.tweet is tweet:
            return context
        if context is not None and context.tweet.tweet_id == tweet.tweet_id:
            return context
        return AnalysisContext(tweet=tweet)

    def close(self) -> None:
        """Kaynaklari serbest birakir (varsayilan olarak yapacak is yok)."""
        return None


#: Eklenti kaydi: ad -> dedektor fabrikasi
DETECTOR_REGISTRY: dict[str, Callable[..., Detector]] = {}


def register_detector(name: str) -> Callable[[Callable[..., Detector]], Callable[..., Detector]]:
    """Dedektoru kayda ekler (ileride config'ten ada gore secmek icin)."""

    def decorator(factory: Callable[..., Detector]) -> Callable[..., Detector]:
        DETECTOR_REGISTRY[name] = factory
        return factory

    return decorator


def build_detector(name: str, **kwargs: object) -> Detector:
    """Kayittaki dedektoru olusturur."""
    try:
        factory = DETECTOR_REGISTRY[name]
    except KeyError as exc:
        available = ", ".join(sorted(DETECTOR_REGISTRY)) or "(kayitli dedektor yok)"
        raise KeyError(
            f"Bilinmeyen dedektor: {name!r}. Kayitli olanlar: {available}"
        ) from exc
    return factory(**kwargs)
