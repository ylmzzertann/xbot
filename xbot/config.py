"""config.yaml okuma ve dogrulama.

Kullanim:

    from xbot.config import load_config
    config = load_config()            # ./config.yaml
    config = load_config("bir/yol/config.yaml")

Hatali ayarlarda ConfigError yukselir ve mesaj Turkce, ne yapilacagini
soyleyecek sekilde yazilmistir. Bu dosyada ASLA gizli bilgi (sifre, token,
cerez) tutulmaz; oturum yalnizca tarayici profil klasorunde saklanir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: Calisma modlari
MODE_DRY_RUN = "dry-run"
MODE_AUTO = "auto"
MODES = (MODE_DRY_RUN, MODE_AUTO)

#: Gecerli log seviyeleri
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

DEFAULT_CONFIG_NAME = "config.yaml"
EXAMPLE_CONFIG_NAME = "config.example.yaml"


class ConfigError(Exception):
    """Ayar dosyasi eksik, bozuk veya gecersiz."""


# --------------------------------------------------------------------------
# dogrulama yardimcilari
# --------------------------------------------------------------------------


def _fail(message: str) -> None:
    raise ConfigError(message)


def _get_mapping(data: Any, name: str) -> dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        _fail(f"'{name}' bir sözlük (anahtar: değer) olmalı, verilen: {type(data).__name__}")
    return dict(data)


def _check_unknown(data: dict[str, Any], allowed: tuple[str, ...], name: str) -> None:
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        _fail(
            f"'{name}' içinde tanınmayan ayar(lar): {', '.join(unknown)}. "
            f"Geçerli ayarlar: {', '.join(allowed)}"
        )


def _as_int(value: Any, name: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"'{name}' tam sayı olmalı, verilen: {value!r}")
    if minimum is not None and value < minimum:
        _fail(f"'{name}' en az {minimum} olmalı, verilen: {value}")
    if maximum is not None and value > maximum:
        _fail(f"'{name}' en fazla {maximum} olmalı, verilen: {value}")
    return int(value)


def _as_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"'{name}' true veya false olmalı, verilen: {value!r}")
    return bool(value)


def _as_str(value: Any, name: str, *, allowed: tuple[str, ...] | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"'{name}' boş olmayan bir metin olmalı, verilen: {value!r}")
    text = value.strip()
    if allowed and text not in allowed:
        _fail(f"'{name}' şunlardan biri olmalı: {', '.join(allowed)} (verilen: {text})")
    return text


def _as_optional_str(value: Any, name: str) -> str:
    """Bos birakilabilen metin ayarlari icin."""
    if value is None:
        return ""
    if not isinstance(value, str):
        _fail(f"'{name}' metin olmalı, verilen: {value!r}")
    return value.strip()


def _as_str_tuple(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        _fail(f"'{name}' bir liste olmalı. Tek öğe için de liste kullan: [\"{value}\"]")
    if not isinstance(value, (list, tuple)):
        _fail(f"'{name}' bir liste olmalı, verilen: {type(value).__name__}")
    items: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            _fail(f"'{name}' listesindeki {index}. öğe boş olmayan bir metin olmalı: {item!r}")
        items.append(item.strip())
    return tuple(dict.fromkeys(items))


def _as_range(value: Any, name: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        _fail(f"'{name}' iki öğeli bir liste olmalı, örnek: [8, 25] (verilen: {value!r})")
    low, high = value
    for item, label in ((low, "alt"), (high, "üst")):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            _fail(f"'{name}' {label} sınırı sayı olmalı, verilen: {item!r}")
        if item < 0:
            _fail(f"'{name}' {label} sınırı negatif olamaz, verilen: {item}")
    if low > high:
        _fail(f"'{name}' alt sınır üst sınırdan büyük olamaz: {low} > {high}")
    return (float(low), float(high))


# --------------------------------------------------------------------------
# ayar bolumleri
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Limits:
    """Engelleme ust sinirlari."""

    per_hour: int = 10
    per_day: int = 40

    @classmethod
    def from_dict(cls, data: Any) -> "Limits":
        mapping = _get_mapping(data, "limits")
        _check_unknown(mapping, ("per_hour", "per_day"), "limits")
        return cls(
            per_hour=_as_int(mapping.get("per_hour", 10), "limits.per_hour", minimum=0),
            per_day=_as_int(mapping.get("per_day", 40), "limits.per_day", minimum=0),
        )


@dataclass(frozen=True, slots=True)
class Delays:
    """Islemler arasi rastgele bekleme araliklari (saniye)."""

    between_actions: tuple[float, float] = (8.0, 25.0)
    between_scrolls: tuple[float, float] = (2.0, 5.0)

    @classmethod
    def from_dict(cls, data: Any) -> "Delays":
        mapping = _get_mapping(data, "delays")
        _check_unknown(mapping, ("between_actions", "between_scrolls"), "delays")
        return cls(
            between_actions=_as_range(
                mapping.get("between_actions", [8, 25]), "delays.between_actions"
            ),
            between_scrolls=_as_range(
                mapping.get("between_scrolls", [2, 5]), "delays.between_scrolls"
            ),
        )


@dataclass(frozen=True, slots=True)
class DetectionConfig:
    """Karar kurallari."""

    high_requires_target: bool = False
    ambiguous_with_target: str = "high"
    mild_with_target: str = "high"
    positive_context_guard: bool = True
    min_root_length_for_glue: int = 6

    @classmethod
    def from_dict(cls, data: Any) -> "DetectionConfig":
        mapping = _get_mapping(data, "detection")
        allowed = (
            "high_requires_target",
            "ambiguous_with_target",
            "mild_with_target",
            "positive_context_guard",
            "min_root_length_for_glue",
        )
        _check_unknown(mapping, allowed, "detection")
        return cls(
            high_requires_target=_as_bool(
                mapping.get("high_requires_target", False),
                "detection.high_requires_target",
            ),
            ambiguous_with_target=_as_str(
                mapping.get("ambiguous_with_target", "high"),
                "detection.ambiguous_with_target",
                allowed=("high", "suspect"),
            ),
            mild_with_target=_as_str(
                mapping.get("mild_with_target", "high"),
                "detection.mild_with_target",
                allowed=("high", "suspect"),
            ),
            positive_context_guard=_as_bool(
                mapping.get("positive_context_guard", True),
                "detection.positive_context_guard",
            ),
            min_root_length_for_glue=_as_int(
                mapping.get("min_root_length_for_glue", 6),
                "detection.min_root_length_for_glue",
                minimum=3,
            ),
        )


@dataclass(frozen=True, slots=True)
class Notifications:
    """Hata durumunda masaustu bildirimi."""

    desktop: bool = True
    error_file: bool = True

    @classmethod
    def from_dict(cls, data: Any) -> "Notifications":
        mapping = _get_mapping(data, "notifications")
        _check_unknown(mapping, ("desktop", "error_file"), "notifications")
        return cls(
            desktop=_as_bool(mapping.get("desktop", True), "notifications.desktop"),
            error_file=_as_bool(
                mapping.get("error_file", True), "notifications.error_file"
            ),
        )


@dataclass(frozen=True, slots=True)
class BrowserConfig:
    """Tarayici ayarlari."""

    timeout_seconds: int = 30
    locale: str = "tr-TR"
    channel: str = ""  # bos: Playwright'in kendi Chromium'u

    @classmethod
    def from_dict(cls, data: Any) -> "BrowserConfig":
        mapping = _get_mapping(data, "browser")
        _check_unknown(mapping, ("timeout_seconds", "locale", "channel"), "browser")
        channel = _as_optional_str(mapping.get("channel", ""), "browser.channel")
        allowed_channels = ("", "chrome", "msedge", "chrome-beta", "msedge-beta")
        if channel not in allowed_channels:
            _fail(
                "'browser.channel' şunlardan biri olmalı (ya da boş): "
                f"{', '.join(c for c in allowed_channels if c)}"
            )
        return cls(
            timeout_seconds=_as_int(
                mapping.get("timeout_seconds", 30),
                "browser.timeout_seconds",
                minimum=5,
                maximum=300,
            ),
            locale=_as_str(mapping.get("locale", "tr-TR"), "browser.locale"),
            channel=channel,
        )


@dataclass(frozen=True, slots=True)
class Paths:
    """Klasor ve dosya yollari (hepsi mutlak yola cevrilmis halde)."""

    profile_dir: Path
    db_path: Path
    log_dir: Path
    screenshot_dir: Path
    report_dir: Path
    blocked_tweets: Path

    @classmethod
    def from_dict(cls, data: Any, base_dir: Path) -> "Paths":
        mapping = _get_mapping(data, "paths")
        allowed = (
            "profile_dir",
            "db_path",
            "log_dir",
            "screenshot_dir",
            "report_dir",
            "blocked_tweets",
        )
        _check_unknown(mapping, allowed, "paths")
        defaults = {
            "profile_dir": ".profile",
            "db_path": "data/xbot.sqlite3",
            "log_dir": "logs",
            "screenshot_dir": "logs/screenshots",
            "report_dir": "reports",
            "blocked_tweets": "kayitlar/engellenen_tweetler.csv",
        }
        resolved = {}
        for key, default in defaults.items():
            value = _as_str(mapping.get(key, default), f"paths.{key}")
            resolved[key] = _resolve(base_dir, value)
        return cls(**resolved)

    def ensure(self) -> None:
        """Gerekli klasorleri olusturur."""
        for directory in (
            self.profile_dir,
            self.log_dir,
            self.screenshot_dir,
            self.report_dir,
            self.db_path.parent,
            self.blocked_tweets.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class Files:
    """Kelime listesi dosyalari."""

    profanity: Path
    allowlist_words: Path
    allowlist_phrases: Path
    positive_context: Path
    whitelist: Path

    @classmethod
    def from_dict(cls, data: Any, base_dir: Path) -> "Files":
        mapping = _get_mapping(data, "files")
        allowed = (
            "profanity",
            "allowlist_words",
            "allowlist_phrases",
            "positive_context",
            "whitelist",
        )
        _check_unknown(mapping, allowed, "files")
        defaults = {
            "profanity": "data/profanity.txt",
            "allowlist_words": "data/allowlist_words.txt",
            "allowlist_phrases": "data/allowlist_phrases.txt",
            "positive_context": "data/positive_context.txt",
            "whitelist": "data/whitelist.txt",
        }
        resolved = {}
        for key, default in defaults.items():
            value = _as_str(mapping.get(key, default), f"files.{key}")
            resolved[key] = _resolve(base_dir, value)
        return cls(**resolved)

    def missing(self) -> list[Path]:
        """Var olmayan liste dosyalarini dondurur."""
        return [
            path
            for path in (
                self.profanity,
                self.allowlist_words,
                self.allowlist_phrases,
                self.positive_context,
                self.whitelist,
            )
            if not path.exists()
        ]


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """Log ayarlari."""

    level: str = "INFO"
    log_tweet_text: bool = True

    @classmethod
    def from_dict(cls, data: Any) -> "LoggingConfig":
        mapping = _get_mapping(data, "logging")
        _check_unknown(mapping, ("level", "log_tweet_text"), "logging")
        level = _as_str(mapping.get("level", "INFO"), "logging.level").upper()
        if level not in LOG_LEVELS:
            _fail(
                f"'logging.level' şunlardan biri olmalı: {', '.join(LOG_LEVELS)} "
                f"(verilen: {level})"
            )
        return cls(
            level=level,
            log_tweet_text=_as_bool(
                mapping.get("log_tweet_text", True), "logging.log_tweet_text"
            ),
        )


def _resolve(base_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path


# --------------------------------------------------------------------------
# ana ayar nesnesi
# --------------------------------------------------------------------------

TOP_LEVEL_KEYS = (
    "search_queries",
    "target_names",
    "mode",
    "time_window_minutes",
    "limits",
    "delays",
    "headless",
    "max_scrolls_per_query",
    "detection",
    "browser",
    "notifications",
    "account_handle",
    "paths",
    "files",
    "logging",
)


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Dogrulanmis butun ayarlar."""

    search_queries: tuple[str, ...] = ()
    target_names: tuple[str, ...] = ()
    mode: str = MODE_DRY_RUN
    time_window_minutes: int = 60
    limits: Limits = field(default_factory=Limits)
    delays: Delays = field(default_factory=Delays)
    headless: bool = False
    max_scrolls_per_query: int = 15
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    notifications: Notifications = field(default_factory=Notifications)
    account_handle: str = ""
    paths: Paths | None = None
    files: Files | None = None
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    base_dir: Path = field(default_factory=Path.cwd)
    source_path: Path | None = None

    @property
    def is_dry_run(self) -> bool:
        return self.mode != MODE_AUTO

    @classmethod
    def from_dict(
        cls,
        data: Any,
        *,
        base_dir: Path | None = None,
        source_path: Path | None = None,
    ) -> "AppConfig":
        mapping = _get_mapping(data, "config.yaml")
        _check_unknown(mapping, TOP_LEVEL_KEYS, "config.yaml")
        root = base_dir or (source_path.parent if source_path else Path.cwd())
        root = root.resolve()

        return cls(
            search_queries=_as_str_tuple(mapping.get("search_queries"), "search_queries"),
            target_names=_as_str_tuple(mapping.get("target_names"), "target_names"),
            mode=_as_str(mapping.get("mode", MODE_DRY_RUN), "mode", allowed=MODES),
            time_window_minutes=_as_int(
                mapping.get("time_window_minutes", 60),
                "time_window_minutes",
                minimum=1,
                maximum=60 * 24 * 7,
            ),
            limits=Limits.from_dict(mapping.get("limits")),
            delays=Delays.from_dict(mapping.get("delays")),
            headless=_as_bool(mapping.get("headless", False), "headless"),
            max_scrolls_per_query=_as_int(
                mapping.get("max_scrolls_per_query", 15),
                "max_scrolls_per_query",
                minimum=0,
                maximum=200,
            ),
            detection=DetectionConfig.from_dict(mapping.get("detection")),
            browser=BrowserConfig.from_dict(mapping.get("browser")),
            notifications=Notifications.from_dict(mapping.get("notifications")),
            account_handle=_as_optional_str(
                mapping.get("account_handle", ""), "account_handle"
            ).lstrip("@"),
            paths=Paths.from_dict(mapping.get("paths"), root),
            files=Files.from_dict(mapping.get("files"), root),
            logging=LoggingConfig.from_dict(mapping.get("logging")),
            base_dir=root,
            source_path=source_path,
        )

    def ensure_dirs(self) -> None:
        if self.paths is not None:
            self.paths.ensure()

    def summary_rows(self) -> list[tuple[str, str]]:
        """Terminalde tablo halinde gostermek icin (ayar, deger) listesi."""
        return [
            ("Arama kelimeleri", ", ".join(self.search_queries) or "(boş!)"),
            ("Hedef isimler", ", ".join(self.target_names) or "(yok)"),
            ("Mod", f"{self.mode} ({'engellemez' if self.is_dry_run else 'ENGELLER'})"),
            ("Zaman penceresi", f"son {self.time_window_minutes} dakika"),
            ("Limitler", f"saatte {self.limits.per_hour}, günde {self.limits.per_day}"),
            (
                "Beklemeler",
                f"işlem arası {self.delays.between_actions[0]:.0f}-"
                f"{self.delays.between_actions[1]:.0f} sn, "
                f"kaydırma arası {self.delays.between_scrolls[0]:.0f}-"
                f"{self.delays.between_scrolls[1]:.0f} sn",
            ),
            ("Tarayıcı", "headless (gizli)" if self.headless else "görünür"),
            ("Kaydırma sayısı", str(self.max_scrolls_per_query)),
            (
                "Hedef ismi zorunlu mu",
                "evet" if self.detection.high_requires_target else "hayır",
            ),
            (
                "Belirsiz + hedef",
                self.detection.ambiguous_with_target,
            ),
            (
                "Olumlu bağlam freni",
                "açık" if self.detection.positive_context_guard else "kapalı",
            ),
            ("Hesap", f"@{self.account_handle}" if self.account_handle else "(otomatik bulunacak)"),
            (
                "Tarayıcı zaman aşımı",
                f"{self.browser.timeout_seconds} sn"
                + (f", kanal: {self.browser.channel}" if self.browser.channel else ""),
            ),
            ("Ayar dosyası", str(self.source_path) if self.source_path else "(varsayılan)"),
        ]


def find_config_path(explicit: str | Path | None = None) -> Path:
    """Kullanilacak config.yaml yolunu bulur."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    candidates = [
        Path.cwd() / DEFAULT_CONFIG_NAME,
        Path(__file__).resolve().parent.parent / DEFAULT_CONFIG_NAME,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0]


def load_config(path: str | Path | None = None) -> AppConfig:
    """config.yaml dosyasini okur ve dogrular."""
    config_path = find_config_path(path)
    if not config_path.exists():
        example = config_path.parent / EXAMPLE_CONFIG_NAME
        hint = (
            f" Örnek dosyayı kopyalayarak başla:\n"
            f"    copy \"{example}\" \"{config_path}\""
            if example.exists()
            else ""
        )
        raise ConfigError(f"Ayar dosyası bulunamadı: {config_path}.{hint}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"Ayar dosyası okunamadı (YAML hatası): {config_path}\n{exc}"
        ) from exc
    except OSError as exc:  # pragma: no cover - dosya sistemi hatasi
        raise ConfigError(f"Ayar dosyası açılamadı: {config_path} ({exc})") from exc
    if raw is None:
        raise ConfigError(f"Ayar dosyası boş: {config_path}")
    return AppConfig.from_dict(raw, source_path=config_path)
