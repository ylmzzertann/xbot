"""'phrase' komutunun karar mantigi (tarayicidan bagimsiz, test edilebilir).

Akis:
  1. Kullanici bir ifade yazar ("okan istifa")
  2. X'te aranir; bulunan tweetler PhraseDetector ile yeniden dogrulanir
  3. Tweetler hesap bazinda gruplanir -> numarali aday listesi
  4. Kullaniciya gosterilir; istedigi numaralari cikarir
  5. Kullanici "evet" yazarsa engelleme baslar (limitler gecerli)
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .detector.phrase import PhraseDetector
from .models import Decision, Level, Tweet
from .scraper import ScrapeResult

# --- aday durumlari ---
STATUS_TO_BLOCK = "block"
STATUS_WHITELISTED = "whitelist"
STATUS_ALREADY = "already"
STATUS_SELF = "self"

STATUS_LABELS = {
    STATUS_TO_BLOCK: "engellenecek",
    STATUS_WHITELISTED: "beyaz listede (atlanır)",
    STATUS_ALREADY: "zaten engelli (atlanır)",
    STATUS_SELF: "senin hesabın (atlanır)",
}


def search_query_for(phrase: str) -> str:
    """X arama kutusuna yazilacak metin: cok kelimeliyse tirnak icinde."""
    cleaned = " ".join(phrase.split()).replace('"', "")
    if len(cleaned.split()) > 1:
        return f'"{cleaned}"'
    return cleaned


@dataclass
class Candidate:
    """Ekranda gosterilen tek satir: bir hesap ve onun eslesen tweetleri."""

    number: int
    username: str
    tweets: list[Tweet]
    decision: Decision
    status: str
    profanity: Level | None = None

    @property
    def first_tweet(self) -> Tweet:
        return self.tweets[0]

    @property
    def will_block(self) -> bool:
        return self.status == STATUS_TO_BLOCK

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


@dataclass
class PhraseSearchResult:
    """Tarayicidan donen arama sonucu."""

    phrase: str
    query: str
    matches: list[tuple[Tweet, Decision]] = field(default_factory=list)
    scrape: ScrapeResult | None = None

    @property
    def tweet_count(self) -> int:
        return len(self.matches)


@dataclass
class BlockPlan:
    """Onaydan sonra yapilacaklar."""

    to_block: list[Candidate] = field(default_factory=list)
    deferred: list[Candidate] = field(default_factory=list)  # limit yuzunden sonraya
    excluded: list[Candidate] = field(default_factory=list)  # kullanici cikardi
    skipped: list[Candidate] = field(default_factory=list)  # beyaz liste/zaten/kendisi


def match_tweets(
    tweets: Iterable[Tweet], detector: PhraseDetector
) -> list[tuple[Tweet, Decision]]:
    """Ifadeyi GERCEKTEN iceren tweetleri karar nesneleriyle dondurur.

    X aramasi gevsektir (kelimeleri farkli yerlerde, profil adinda vb. bulabilir);
    bu yuzden her tweet kendi normalizasyonumuzla yeniden kontrol edilir.
    """
    out: list[tuple[Tweet, Decision]] = []
    for tweet in tweets:
        verdict = detector.analyze(tweet)
        if verdict.level is not Level.HIGH:
            continue
        out.append(
            (
                tweet,
                Decision(
                    tweet=tweet,
                    level=Level.HIGH,
                    matches=verdict.matches,
                    reasons=verdict.reasons,
                    verdicts=(verdict,),
                ),
            )
        )
    return out


def build_candidates(
    matches: Sequence[tuple[Tweet, Decision]],
    *,
    whitelist=None,
    storage=None,
    own_handle: str = "",
    engine=None,
) -> list[Candidate]:
    """Tweetleri hesap bazinda gruplar ve her hesabin durumunu belirler."""
    groups: dict[str, list[tuple[Tweet, Decision]]] = {}
    for tweet, decision in matches:
        groups.setdefault(tweet.username.lower(), []).append((tweet, decision))

    own = (own_handle or "").lstrip("@").lower()
    candidates: list[Candidate] = []
    for number, items in enumerate(groups.values(), start=1):
        tweets = [tweet for tweet, _decision in items]
        username = tweets[0].username
        key = username.lower()
        if own and key == own:
            status = STATUS_SELF
        elif whitelist is not None and whitelist.contains(username):
            status = STATUS_WHITELISTED
        elif storage is not None and storage.is_blocked(username):
            status = STATUS_ALREADY
        else:
            status = STATUS_TO_BLOCK

        profanity = None
        if engine is not None:
            profanity = max(engine.evaluate(tweet).level for tweet in tweets)

        candidates.append(
            Candidate(
                number=number,
                username=username,
                tweets=tweets,
                decision=items[0][1],
                status=status,
                profanity=profanity,
            )
        )
    return candidates


def parse_numbers(text: str, max_number: int) -> set[int]:
    """'2, 5, 7-9' -> {2, 5, 7, 8, 9}. Hatali girdide Turkce ValueError."""
    numbers: set[int] = set()
    cleaned = (text or "").replace(";", ",").replace(" ", ",")
    for part in cleaned.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, _, end_text = part.partition("-")
            if not (start_text.isdigit() and end_text.isdigit()):
                raise ValueError(f"Anlaşılamadı: '{part}'. Örnek: 2,5,7-9")
            start, end = int(start_text), int(end_text)
            if start > end:
                start, end = end, start
            values = range(start, end + 1)
        else:
            if not part.isdigit():
                raise ValueError(f"Anlaşılamadı: '{part}'. Örnek: 2,5,7-9")
            values = (int(part),)
        for value in values:
            if not 1 <= value <= max_number:
                raise ValueError(f"{value} numaralı satır yok (1-{max_number} arası gir).")
            numbers.add(value)
    return numbers


def plan_blocks(
    candidates: Sequence[Candidate],
    *,
    excluded: set[int] | None = None,
    limit_left: int | None = None,
) -> BlockPlan:
    """Onaylanan listeyi limite gore 'simdi' ve 'sonraya' diye ayirir."""
    excluded = excluded or set()
    plan = BlockPlan()
    for candidate in candidates:
        if not candidate.will_block:
            plan.skipped.append(candidate)
        elif candidate.number in excluded:
            plan.excluded.append(candidate)
        elif limit_left is not None and len(plan.to_block) >= limit_left:
            plan.deferred.append(candidate)
        else:
            plan.to_block.append(candidate)
    return plan
