"""Komut satiri arayuzu.

Kullanim ozeti:

    python -m xbot --help
    python -m xbot check "siktir git okan buruk"     # tek metni dene
    python -m xbot check-file examples/ornek.txt     # dosyadan toplu dene
    python -m xbot words / config-show               # listeler ve ayarlar
    python -m xbot login                             # bir kez elle giris
    python -m xbot check-selectors                    # canli sayfada secici kontrolu
    python -m xbot run                                # DRY-RUN tarama (varsayilan)
    python -m xbot run --auto                         # YUKSEK kararlilari ENGELLER
    python -m xbot review                             # supheliler icin tek tek onay
    python -m xbot list-blocked / stats / report
    python -m xbot sync-whitelist
    python -m xbot task-command                       # zamanlanmis gorev komutu

Cikis kodlari: 0 basarili, 1 kullanim hatasi, 2 ayar/liste hatasi,
4 guvenlik nedeniyle durdu, 5 baska bir calisma suruyor.
"""

from __future__ import annotations

import os
import sys
import time
import webbrowser
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .app import AppServices, BrowserApp, build_services
from .config import MODE_AUTO, AppConfig, ConfigError, load_config
from .detector.engine import DecisionEngine
from .errors import BrowserError, LockError, StopRun
from .lock import RunLock
from .models import Decision, Level, Severity, Tweet
from .report import ReportBuilder
from .storage import SUSPECT_BLOCKED, SUSPECT_DISMISSED, Storage
from .wordlists import WordListError, load_profanity_entries, load_word_list

# Windows terminalinde Turkce karakterler bozulmasin
for _stream in (sys.stdout, sys.stderr):
    try:  # pragma: no cover - platforma bagli
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

console = Console()
app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="X (Twitter) küfür tespit ve engelleme botu — kişisel kullanım.",
)

_state: dict[str, object] = {"config_path": None}

LEVEL_STYLE = {
    Level.CLEAN: "green",
    Level.SUSPECT: "yellow",
    Level.HIGH: "bold red",
}

EXIT_USAGE = 1
EXIT_CONFIG = 2
EXIT_STOPPED = 4
EXIT_BUSY = 5


# --------------------------------------------------------------------------
# yardimcilar
# --------------------------------------------------------------------------


def _load_config() -> AppConfig:
    try:
        return load_config(_state["config_path"])  # type: ignore[arg-type]
    except ConfigError as exc:
        console.print(Panel(str(exc), title="Ayar hatası", border_style="red"))
        raise typer.Exit(code=EXIT_CONFIG) from exc


def _build_engine(config: AppConfig) -> DecisionEngine:
    try:
        return DecisionEngine.from_config(config)
    except WordListError as exc:
        console.print(Panel(str(exc), title="Kelime listesi hatası", border_style="red"))
        raise typer.Exit(code=EXIT_CONFIG) from exc


def _services(config: AppConfig, *, console_log: bool = False) -> AppServices:
    try:
        return build_services(config, console_log=console_log)
    except WordListError as exc:
        console.print(Panel(str(exc), title="Kelime listesi hatası", border_style="red"))
        raise typer.Exit(code=EXIT_CONFIG) from exc


def _level_text(level: Level) -> Text:
    return Text(level.label, style=LEVEL_STYLE[level])


def _shorten(text: str, width: int = 70) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def _print_decision(decision: Decision, *, details: bool = True) -> None:
    body = Text()
    body.append("Metin : ", style="dim")
    body.append(decision.tweet.text + "\n")
    body.append("Karar : ", style="dim")
    body.append(_level_text(decision.level))
    body.append("\n")
    if decision.matches:
        body.append("Kural : ", style="dim")
        body.append(decision.rule_summary + "\n")
    if details:
        for reason in decision.reasons:
            body.append("  • " + reason + "\n", style="dim")
    action = (
        "Bu tweet --auto modunda ENGELLENİRDİ."
        if decision.is_blockable
        else "Bu tweet engellenmez."
        if decision.level is Level.CLEAN
        else "Bu tweet engellenmez, 'review' listesine yazılır."
    )
    body.append(action, style=LEVEL_STYLE[decision.level])
    console.print(
        Panel(body, border_style=LEVEL_STYLE[decision.level], title=decision.level.label)
    )


def _handle_stop(exc: StopRun) -> None:
    console.print(
        Panel(
            f"{exc}\n\nProgram güvenlik gereği durdu. Kanıt dosyaları "
            "logs/screenshots klasöründe.",
            title="DURDURULDU",
            border_style="red",
        )
    )
    raise typer.Exit(code=EXIT_STOPPED)


def _handle_unexpected(exc: BaseException, services: AppServices | None = None) -> None:
    """Beklenmeyen hatada: logla, haber ver, anlaşılır mesaj bas, dur."""
    message = f"Beklenmeyen hata: {type(exc).__name__}: {exc}"
    if services is not None:
        try:
            services.logger.exception("Beklenmeyen hata")
            if services.notifier is not None:
                services.notifier("XBot hatası", message)
        except Exception:  # pragma: no cover - loglama da bozuksa
            pass
    console.print(
        Panel(
            message + "\n\nAyrıntılar logs/xbot.log dosyasında. "
            "Arayüz değiştiyse: python -m xbot check-selectors",
            title="Hata",
            border_style="red",
        )
    )
    raise typer.Exit(code=EXIT_STOPPED) from exc


def _lock(services: AppServices) -> RunLock:
    try:
        return RunLock(services.lock_path).acquire()
    except LockError as exc:
        console.print(Panel(str(exc), title="Zaten çalışıyor", border_style="yellow"))
        raise typer.Exit(code=EXIT_BUSY) from exc


def _open_file(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # noqa: S606
        else:  # pragma: no cover - platform
            webbrowser.open(path.as_uri())
    except Exception as exc:  # pragma: no cover
        console.print(f"[yellow]Dosya açılamadı: {exc}[/yellow]")


# --------------------------------------------------------------------------
# ortak secenek
# --------------------------------------------------------------------------


@app.callback()
def main(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Kullanılacak config.yaml yolu."),
    ] = None,
) -> None:
    """Ortak seçenekler."""
    _state["config_path"] = config


# --------------------------------------------------------------------------
# tespit komutlari (tarayici gerektirmez)
# --------------------------------------------------------------------------


@app.command("check")
def check_command(
    text: Annotated[
        list[str] | None,
        typer.Argument(help="İncelenecek metin (tırnak içinde yazabilirsin)."),
    ] = None,
    username: Annotated[
        str, typer.Option("--user", "-u", help="Test için kullanıcı adı.")
    ] = "test_kullanici",
    quiet: Annotated[
        bool, typer.Option("--kisa", "-k", help="Sadece karar seviyesini yazdır.")
    ] = False,
) -> None:
    """Tek bir metni dedektörlerden geçirir (hiçbir şeyi engellemez)."""
    joined = " ".join(text or []).strip()
    if not joined:
        console.print('[yellow]Bir metin ver: python -m xbot check "metin"[/yellow]')
        raise typer.Exit(code=EXIT_USAGE)
    config = _load_config()
    engine = _build_engine(config)
    decision = engine.evaluate(Tweet(tweet_id="0", username=username, text=joined))
    if quiet:
        console.print(_level_text(decision.level))
    else:
        _print_decision(decision)


@app.command("check-file")
def check_file_command(
    path: Annotated[Path, typer.Argument(help="Her satırı bir tweet sayılan dosya.")],
    only_flagged: Annotated[
        bool,
        typer.Option("--sadece-isaretli", help="Sadece ŞÜPHELİ ve YÜKSEK olanları göster."),
    ] = False,
) -> None:
    """Dosyadaki her satırı ayrı ayrı inceler (toplu deneme için)."""
    if not path.exists():
        console.print(f"[red]Dosya bulunamadı: {path}[/red]")
        raise typer.Exit(code=EXIT_USAGE)
    config = _load_config()
    engine = _build_engine(config)

    table = Table(title=f"{path.name} — tespit sonuçları", show_lines=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Karar")
    table.add_column("Metin", overflow="fold")
    table.add_column("Eşleşen kural", overflow="fold")

    counts = {Level.CLEAN: 0, Level.SUSPECT: 0, Level.HIGH: 0}
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        decision = engine.evaluate(
            Tweet(tweet_id=str(index), username="test", text=stripped)
        )
        counts[decision.level] += 1
        if only_flagged and decision.level is Level.CLEAN:
            continue
        table.add_row(
            str(index),
            _level_text(decision.level),
            stripped,
            decision.rule_summary or "-",
        )
    console.print(table)
    console.print(
        f"Özet: [green]{counts[Level.CLEAN]} temiz[/green], "
        f"[yellow]{counts[Level.SUSPECT]} şüpheli[/yellow], "
        f"[bold red]{counts[Level.HIGH]} yüksek[/bold red]"
    )


@app.command("words")
def words_command(
    show: Annotated[
        bool, typer.Option("--listele", help="Kökleri ağırlıklarıyla birlikte yazdır.")
    ] = False,
) -> None:
    """Kelime listelerinin durumunu gösterir."""
    config = _load_config()
    try:
        entries = load_profanity_entries(config.files.profanity)
        allow_words = load_word_list(config.files.allowlist_words)
        phrases = load_word_list(config.files.allowlist_phrases)
        positive = load_word_list(config.files.positive_context)
        whitelist = load_word_list(config.files.whitelist)
    except WordListError as exc:
        console.print(Panel(str(exc), title="Kelime listesi hatası", border_style="red"))
        raise typer.Exit(code=EXIT_CONFIG) from exc

    by_severity: dict[Severity, list[str]] = {s: [] for s in Severity}
    for entry in entries:
        by_severity[entry.severity].append(entry.raw)

    table = Table(title="Kelime listeleri")
    table.add_column("Liste")
    table.add_column("Adet", justify="right")
    table.add_column("Dosya", overflow="fold", style="dim")
    table.add_row(
        "Küfür kökü (güçlü)",
        str(len(by_severity[Severity.STRONG])),
        str(config.files.profanity),
    )
    table.add_row("Küfür kökü (hafif)", str(len(by_severity[Severity.MILD])), "")
    table.add_row("Küfür kökü (belirsiz)", str(len(by_severity[Severity.AMBIGUOUS])), "")
    table.add_row(
        "Masum kelime", str(len(allow_words)), str(config.files.allowlist_words)
    )
    table.add_row("Masum kalıp", str(len(phrases)), str(config.files.allowlist_phrases))
    table.add_row(
        "Olumlu bağlam", str(len(positive)), str(config.files.positive_context)
    )
    table.add_row("Beyaz liste", str(len(whitelist)), str(config.files.whitelist))
    console.print(table)

    if show:
        for severity in (Severity.STRONG, Severity.MILD, Severity.AMBIGUOUS):
            words = by_severity[severity]
            if not words:
                continue
            console.print(
                Panel(
                    ", ".join(words),
                    title=f"{severity.label} kökler ({len(words)})",
                    border_style="dim",
                )
            )


@app.command("config-show")
def config_show_command() -> None:
    """Ayarları okur, doğrular ve özetini gösterir."""
    config = _load_config()
    table = Table(title="Ayarlar (doğrulandı)")
    table.add_column("Ayar", style="bold")
    table.add_column("Değer", overflow="fold")
    for key, value in config.summary_rows():
        table.add_row(key, value)
    console.print(table)

    missing = config.files.missing() if config.files else []
    if missing:
        console.print(
            Panel(
                "Eksik liste dosyaları:\n" + "\n".join(f"  - {p}" for p in missing),
                title="Uyarı",
                border_style="yellow",
            )
        )
    else:
        console.print("[green]Bütün kelime listesi dosyaları yerinde.[/green]")
    if config.is_dry_run:
        console.print("[green]Mod dry-run: program hiçbir hesabı engellemez.[/green]")
    else:
        console.print(
            "[bold red]DİKKAT: mod 'auto'. 'run' komutu YÜKSEK kararlıları "
            "gerçekten engeller.[/bold red]"
        )


# --------------------------------------------------------------------------
# tarayici komutlari
# --------------------------------------------------------------------------


@app.command("doctor")
def doctor_command() -> None:
    """Kurulumu kontrol eder: Python, Playwright, tarayıcı, listeler, oturum."""
    config = _load_config()
    table = Table(title="Kurulum kontrolü")
    table.add_column("Kontrol", style="bold")
    table.add_column("Durum")
    table.add_column("Ayrıntı", overflow="fold", style="dim")
    problems: list[str] = []

    def add(name: str, ok: bool, detail: str = "", *, warning: bool = False) -> None:
        if ok:
            status = Text("tamam", style="green")
        elif warning:
            status = Text("uyarı", style="yellow")
        else:
            status = Text("EKSİK", style="bold red")
            problems.append(name)
        table.add_row(name, status, detail)

    version = ".".join(str(part) for part in sys.version_info[:3])
    add("Python 3.11+", sys.version_info >= (3, 11), f"bulunan: {version}")

    playwright_ok = False
    chromium_detail = "Playwright kurulu değil"
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        playwright_ok = True
        try:
            with sync_playwright() as pw:
                executable = Path(pw.chromium.executable_path)
            chromium_ok = executable.exists()
            chromium_detail = str(executable)
        except Exception as exc:  # pragma: no cover - tarayici indirilmemis
            chromium_ok = False
            chromium_detail = f"python -m playwright install chromium ({exc})"
    except ImportError:
        chromium_ok = False
    add("Playwright paketi", playwright_ok, "python -m pip install playwright")
    add("Chromium tarayıcı", chromium_ok, chromium_detail)

    missing = config.files.missing()
    add(
        "Kelime listeleri",
        not missing,
        ", ".join(str(p) for p in missing) or str(config.files.profanity.parent),
    )

    profile_dir = Path(config.paths.profile_dir)
    has_profile = profile_dir.exists() and any(profile_dir.iterdir())
    add(
        "Tarayıcı profili (oturum)",
        has_profile,
        str(profile_dir) if has_profile else "python -m xbot login ile bir kez giriş yap",
        warning=not has_profile,
    )

    try:
        with Storage(config.paths.db_path) as storage:
            seen = storage.seen_count()
        add("Veritabanı", True, f"{config.paths.db_path} ({seen} tweet kaydı)")
    except Exception as exc:  # pragma: no cover
        add("Veritabanı", False, str(exc))

    add(
        "Mod",
        True,
        f"{config.mode} — {'engellemez' if config.is_dry_run else 'ENGELLER'}",
    )
    console.print(table)
    if problems:
        console.print(
            Panel(
                "Eksik: " + ", ".join(problems),
                title="Tamamlanması gerekenler",
                border_style="red",
            )
        )
        raise typer.Exit(code=EXIT_CONFIG)
    console.print("[green]Her şey hazır.[/green]")


@app.command("login")
def login_command(
    timeout: Annotated[
        int, typer.Option("--sure", help="Giriş için beklenecek en fazla saniye.")
    ] = 300,
) -> None:
    """Görünür tarayıcı açar; girişi SEN yaparsın, oturum profile kaydedilir."""
    config = _load_config()
    services = _services(config)
    console.print(
        Panel(
            "Tarayıcı açılıyor. Açılan pencerede X hesabına [bold]kendin[/bold] giriş yap.\n"
            "Program şifre sormaz, görmez, kaydetmez — oturum yalnızca profil "
            f"klasöründe kalır:\n  {config.paths.profile_dir}\n\n"
            "Giriş yapınca bu ekran kendiliğinden devam eder.",
            title="Giriş",
            border_style="cyan",
        )
    )
    try:
        with BrowserApp(services, headless=False) as browser:
            if browser.session.is_logged_in():
                console.print("[green]Oturum zaten açık.[/green]")
            else:
                ok = browser.wait_for_manual_login(timeout_seconds=timeout)
                if not ok:
                    console.print(
                        Panel(
                            "Giriş algılanamadı. Tarayıcıyı kapatmadan tekrar dene: "
                            "python -m xbot login",
                            title="Giriş tamamlanmadı",
                            border_style="yellow",
                        )
                    )
                    raise typer.Exit(code=EXIT_STOPPED)
                console.print("[green]Giriş algılandı, oturum kaydedildi.[/green]")
            handle = browser.detect_handle()
            if handle:
                console.print(f"Hesap: [bold]@{handle}[/bold]")
                if not config.account_handle:
                    console.print(
                        "[dim]İpucu: config.yaml içine account_handle: "
                        f'"{handle}" yazarsan sync-whitelist daha hızlı çalışır.[/dim]'
                    )
            console.print(
                "\nSıradaki adım: [bold]python -m xbot check-selectors[/bold] "
                "(arayüz seçicilerini canlı sayfada doğrular)"
            )
    except (StopRun,) as exc:
        _handle_stop(exc)
    except BrowserError as exc:
        console.print(Panel(str(exc), title="Tarayıcı hatası", border_style="red"))
        raise typer.Exit(code=EXIT_CONFIG) from exc
    except typer.Exit:
        raise
    except Exception as exc:  # pragma: no cover - beklenmeyen hata
        _handle_unexpected(exc, services)
    finally:
        services.close()


@app.command("check-selectors")
def check_selectors_command(
    query: Annotated[
        str | None,
        typer.Option("--query", "-q", help="Denenecek arama kelimesi (varsayılan: ilk kelime)."),
    ] = None,
    menu: Annotated[
        bool,
        typer.Option("--menu", help='"..." menüsünü de açıp kontrol eder (engellemez).'),
    ] = False,
    headless: Annotated[
        bool | None,
        typer.Option("--headless/--gorunur", help="Tarayıcı gizli mi açılsın?"),
    ] = None,
) -> None:
    """Canlı sayfada bütün seçicileri dener (arayüz değiştiyse burada görürsün)."""
    config = _load_config()
    search = query or (config.search_queries[0] if config.search_queries else "")
    if not search:
        console.print(
            "[yellow]config.yaml içindeki search_queries boş. "
            '--query "kelime" ile dene.[/yellow]'
        )
        raise typer.Exit(code=EXIT_USAGE)
    services = _services(config)
    try:
        with BrowserApp(services, headless=headless) as browser:
            results = browser.check_selectors(search, with_menu=menu)
    except StopRun as exc:
        _handle_stop(exc)
        return
    except BrowserError as exc:
        console.print(Panel(str(exc), title="Tarayıcı hatası", border_style="red"))
        raise typer.Exit(code=EXIT_CONFIG) from exc
    except typer.Exit:
        raise
    except Exception as exc:  # pragma: no cover - beklenmeyen hata
        _handle_unexpected(exc, services)
    finally:
        services.close()

    table = Table(title=f"Seçici kontrolü — arama: {search}")
    table.add_column("Öğe")
    table.add_column("Bulundu", justify="right")
    table.add_column("Durum")
    table.add_column("Seçici", overflow="fold", style="dim")
    problems = 0
    for result in results:
        if result.ok:
            status = Text("tamam", style="green")
        else:
            status = Text("EKSİK", style="bold red")
            problems += 1
        note = f" ({result.note})" if result.note else ""
        table.add_row(
            result.name + note, str(result.found), status, result.selector
        )
    console.print(table)
    if problems:
        console.print(
            Panel(
                f"{problems} zorunlu seçici bulunamadı. X arayüzü değişmiş olabilir.\n"
                "Düzeltmek için: xbot/selectors.py dosyasını güncelle "
                "(sayfa HTML'i logs/screenshots klasörüne kaydedilebilir: "
                "python -m xbot check-selectors --menu).",
                title="Seçici sorunu",
                border_style="red",
            )
        )
        raise typer.Exit(code=EXIT_STOPPED)
    console.print("[green]Bütün zorunlu seçiciler yerinde.[/green]")


@app.command("run")
def run_command(
    auto: Annotated[
        bool,
        typer.Option("--auto", help="YÜKSEK kararlıları GERÇEKTEN engeller."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Hiçbir şeyi engellemez (varsayılan)."),
    ] = False,
    query: Annotated[
        list[str] | None,
        typer.Option("--query", "-q", help="Sadece bu kelimeyi tara (birden çok verilebilir)."),
    ] = None,
    minutes: Annotated[
        int | None,
        typer.Option("--dakika", help="Zaman penceresi (varsayılan config'ten)."),
    ] = None,
    headless: Annotated[
        bool | None,
        typer.Option("--headless/--gorunur", help="Tarayıcı gizli mi açılsın?"),
    ] = None,
    make_report: Annotated[
        bool, typer.Option("--rapor", help="Tur sonunda HTML+CSV rapor üret.")
    ] = False,
) -> None:
    """Arama kelimelerini tarar, son N dakikadaki tweetleri inceler."""
    config = _load_config()
    wants_auto = auto or (config.mode == MODE_AUTO and not dry_run)
    if dry_run and auto:
        console.print("[red]--auto ile --dry-run birlikte kullanılamaz.[/red]")
        raise typer.Exit(code=EXIT_USAGE)
    queries = list(query) if query else list(config.search_queries)
    if not queries:
        console.print(
            "[yellow]Aranacak kelime yok: config.yaml içindeki search_queries'i doldur "
            'ya da --query "kelime" ver.[/yellow]'
        )
        raise typer.Exit(code=EXIT_USAGE)

    services = _services(config, console_log=True)
    lock = _lock(services)
    try:
        if wants_auto:
            console.print(
                Panel(
                    "[bold red]AUTO MOD[/bold red]: YÜKSEK kararlı hesaplar "
                    "gerçekten engellenecek.\n"
                    f"Limitler: saatte {config.limits.per_hour}, günde {config.limits.per_day}. "
                    f"Beyaz listede {len(services.whitelist)} hesap var.\n"
                    "Vazgeçmek için Ctrl+C.",
                    title="Dikkat",
                    border_style="red",
                )
            )
            if sys.stdin.isatty():
                for remaining in (3, 2, 1):
                    console.print(f"[dim]{remaining}...[/dim]")
                    time.sleep(1)
        else:
            console.print(
                "[green]DRY-RUN: hiçbir hesap engellenmeyecek, sadece raporlanacak."
                "[/green]"
            )
        with BrowserApp(services, headless=headless) as browser:
            summary = browser.run(auto=wants_auto, queries=queries, minutes=minutes)
    except StopRun as exc:
        _handle_stop(exc)
        return
    except BrowserError as exc:
        console.print(Panel(str(exc), title="Tarayıcı hatası", border_style="red"))
        raise typer.Exit(code=EXIT_CONFIG) from exc
    except KeyboardInterrupt:  # pragma: no cover - elle iptal
        console.print("\n[yellow]Kullanıcı iptal etti.[/yellow]")
        raise typer.Exit(code=EXIT_STOPPED) from None
    except typer.Exit:
        raise
    except Exception as exc:  # pragma: no cover - beklenmeyen hata
        _handle_unexpected(exc, services)
    finally:
        lock.release()

    body = "\n".join(summary.lines())
    border = "red" if summary.stopped else ("yellow" if summary.high else "green")
    console.print(Panel(body, title="Tur özeti", border_style=border))
    if summary.suspect:
        console.print(
            "[yellow]Şüphelileri tek tek incelemek için: "
            "python -m xbot review[/yellow]"
        )
    if make_report:
        paths = ReportBuilder(services.storage, config.paths.report_dir).build(
            summary_lines=summary.lines()
        )
        for path in paths.existing():
            console.print(f"Rapor: {path}")
    services.close()
    if summary.stopped:
        raise typer.Exit(code=EXIT_STOPPED)


@app.command("review")
def review_command(
    limit: Annotated[
        int, typer.Option("--limit", help="En fazla kaç şüpheli gösterilsin.")
    ] = 20,
    headless: Annotated[
        bool | None,
        typer.Option("--headless/--gorunur", help="Tarayıcı gizli mi açılsın?"),
    ] = None,
) -> None:
    """ŞÜPHELİ listesini tek tek gösterir; onayladıklarını engeller."""
    config = _load_config()
    services = _services(config)
    pending = services.storage.pending_suspects(limit)
    if not pending:
        console.print("[green]Bekleyen şüpheli tweet yok.[/green]")
        services.close()
        return

    console.print(
        Panel(
            f"{len(pending)} şüpheli tweet var.\n"
            "Her tweet için: [bold]e[/bold]=engelle, [bold]a[/bold]=atla, "
            "[bold]t[/bold]=temizle (bir daha sorma), [bold]q[/bold]=çık",
            title="İnceleme",
            border_style="cyan",
        )
    )
    lock = _lock(services)
    browser: BrowserApp | None = None
    blocked = dismissed = skipped = 0
    try:
        for index, record in enumerate(pending, start=1):
            panel = Text()
            panel.append(f"@{record.username}\n", style="bold")
            panel.append(record.text + "\n\n")
            panel.append(f"Kural : {record.rules or '-'}\n", style="dim")
            panel.append(f"Zaman : {record.tweet_time or '-'}\n", style="dim")
            panel.append(f"Link  : {record.url or '-'}", style="dim")
            console.print(
                Panel(panel, title=f"{index}/{len(pending)}", border_style="yellow")
            )
            answer = console.input("[bold]e/a/t/q >[/bold] ").strip().lower()
            if answer == "q":
                break
            if answer == "t":
                services.storage.set_suspect_status(record.tweet_id, SUSPECT_DISMISSED)
                dismissed += 1
                continue
            if answer != "e":
                skipped += 1
                continue

            tweet = record.as_tweet()
            decision = services.engine.evaluate(tweet)
            if browser is None:
                console.print("[dim]Tarayıcı açılıyor...[/dim]")
                browser = BrowserApp(services, headless=headless)
                browser.__enter__()
            outcome = browser.block_single(tweet, decision)
            console.print(f"  → {outcome.message}")
            if outcome.blocked:
                services.storage.set_suspect_status(record.tweet_id, SUSPECT_BLOCKED)
                blocked += 1
            else:
                skipped += 1
    except StopRun as exc:
        _handle_stop(exc)
        return
    except KeyboardInterrupt:  # pragma: no cover
        console.print("\n[yellow]İnceleme durduruldu.[/yellow]")
    except typer.Exit:
        raise
    except Exception as exc:  # pragma: no cover - beklenmeyen hata
        _handle_unexpected(exc, services)
    finally:
        if browser is not None:
            browser.__exit__(None, None, None)
        lock.release()
        console.print(
            f"Sonuç: [bold red]{blocked} engellendi[/bold red], "
            f"[green]{dismissed} temizlendi[/green], {skipped} atlandı."
        )
        services.close()


@app.command("list-blocked")
def list_blocked_command(
    limit: Annotated[int, typer.Option("--limit", help="Kaç kayıt gösterilsin.")] = 30,
    show_undone: Annotated[
        bool, typer.Option("--geri-alinanlar", help="Geri alınanları da göster.")
    ] = True,
) -> None:
    """Engellenen hesapları kanıtlarıyla listeler (geri almak için)."""
    config = _load_config()
    with Storage(config.paths.db_path) as storage:
        records = storage.recent_blocks(limit, include_undone=show_undone)
    if not records:
        console.print("[green]Engellenmiş hesap kaydı yok.[/green]")
        return
    table = Table(title=f"Engellenen hesaplar (son {len(records)})")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Hesap")
    table.add_column("Kural")
    table.add_column("Tweet", overflow="fold")
    table.add_column("Zaman", style="dim")
    table.add_column("Durum")
    for record in records:
        table.add_row(
            str(record.id),
            f"@{record.username}",
            record.rules or "-",
            _shorten(record.text, 60),
            record.blocked_at.replace("T", " ")[:16],
            Text("geri alındı", style="dim") if record.undone else Text("engelli", style="red"),
        )
    console.print(table)
    console.print(
        "[dim]Engeli kaldırmak: https://x.com/<hesap> sayfasında 'Engeli kaldır'. "
        "Sonra kaydı işaretle: python -m xbot mark-unblocked <#>[/dim]"
    )


@app.command("mark-unblocked")
def mark_unblocked_command(
    block_id: Annotated[int, typer.Argument(help="list-blocked çıktısındaki # numarası.")],
    note: Annotated[str, typer.Option("--not", help="Kayda düşülecek açıklama.")] = "",
) -> None:
    """X üzerinde engeli kaldırdığın kaydı 'geri alındı' olarak işaretler."""
    config = _load_config()
    with Storage(config.paths.db_path) as storage:
        ok = storage.mark_block_undone(block_id, note=note)
    if ok:
        console.print(f"[green]#{block_id} kaydı 'geri alındı' olarak işaretlendi.[/green]")
    else:
        console.print(f"[yellow]#{block_id} numaralı kayıt bulunamadı.[/yellow]")
        raise typer.Exit(code=EXIT_USAGE)


@app.command("stats")
def stats_command() -> None:
    """Özet istatistikleri gösterir."""
    config = _load_config()
    services = _services(config)
    try:
        stats = services.storage.stats()
        status = services.limiter.status()
        runs = services.storage.last_runs(5)
    finally:
        services.close()

    labels = {
        "gorulen_tweet": "Görülen tweet",
        "engellenen": "Engellenen hesap",
        "geri_alinan": "Geri alınan engel",
        "supheli_bekleyen": "Bekleyen şüpheli",
        "supheli_engellenen": "Şüpheliden engellenen",
        "supheli_temizlenen": "Şüpheliden temizlenen",
        "son_1_saat_engel": "Son 1 saatte engel",
        "son_24_saat_engel": "Son 24 saatte engel",
        "calisma_sayisi": "Çalışma sayısı",
        "son_calisma": "Son çalışma",
    }
    table = Table(title="İstatistikler")
    table.add_column("Ölçü", style="bold")
    table.add_column("Değer", justify="right")
    for key, label in labels.items():
        table.add_row(label, str(stats.get(key, "-")))
    table.add_row("Limit durumu", status.describe())
    console.print(table)

    if runs:
        run_table = Table(title="Son çalışmalar")
        for column in ("Başlangıç", "Mod", "Görülen", "Yüksek", "Şüpheli", "Engel", "Durum"):
            run_table.add_column(column)
        for row in runs:
            run_table.add_row(
                str(row["started_at"]).replace("T", " ")[:16],
                str(row["mode"] or "-"),
                str(row["seen"] or 0),
                str(row["high"] or 0),
                str(row["suspect"] or 0),
                str(row["blocked"] or 0),
                str(row["status"] or "-"),
            )
        console.print(run_table)


@app.command("report")
def report_command(
    limit: Annotated[int, typer.Option("--limit", help="Rapora kaç kayıt girsin.")] = 300,
    open_after: Annotated[
        bool, typer.Option("--ac", help="Rapor üretilince tarayıcıda aç.")
    ] = False,
    no_csv: Annotated[bool, typer.Option("--csv-yok", help="CSV üretme.")] = False,
) -> None:
    """Engellenenler ve şüpheliler için HTML + CSV raporu üretir."""
    config = _load_config()
    with Storage(config.paths.db_path) as storage:
        paths = ReportBuilder(storage, config.paths.report_dir).build(
            limit=limit, csv_report=not no_csv
        )
    for path in paths.existing():
        console.print(f"[green]Rapor:[/green] {path}")
    if open_after and paths.html is not None:
        _open_file(paths.html)


@app.command("sync-whitelist")
def sync_whitelist_command(
    user: Annotated[
        str | None,
        typer.Option("--user", "-u", help="Kendi kullanıcı adın (boşsa otomatik bulunur)."),
    ] = None,
    scrolls: Annotated[
        int, typer.Option("--kaydirma", help="Takip listesinde kaç kez kaydırılsın.")
    ] = 30,
    headless: Annotated[
        bool | None,
        typer.Option("--headless/--gorunur", help="Tarayıcı gizli mi açılsın?"),
    ] = None,
) -> None:
    """Takip ettiğin hesapları beyaz listeye ekler (nadiren çalıştır)."""
    config = _load_config()
    services = _services(config)
    added = 0
    try:
        with BrowserApp(services, headless=headless) as browser:
            handle = user or browser.detect_handle()
            if not handle:
                console.print(
                    "[yellow]Kullanıcı adı bulunamadı. --user ile ver "
                    "ya da config.yaml içine account_handle yaz.[/yellow]"
                )
                raise typer.Exit(code=EXIT_USAGE)
            console.print(f"@{handle} takip listesi taranıyor...")
            names = browser.collect_following(handle, max_scrolls=scrolls)
            added = services.whitelist.add_many(names)
    except StopRun as exc:
        _handle_stop(exc)
        return
    except BrowserError as exc:
        console.print(Panel(str(exc), title="Tarayıcı hatası", border_style="red"))
        raise typer.Exit(code=EXIT_CONFIG) from exc
    except typer.Exit:
        raise
    except Exception as exc:  # pragma: no cover - beklenmeyen hata
        _handle_unexpected(exc, services)
    finally:
        services.close()
    console.print(
        f"[green]{added} yeni hesap beyaz listeye eklendi.[/green] "
        f"Dosya: {config.files.whitelist}"
    )


@app.command("task-command")
def task_command(
    every_minutes: Annotated[
        int, typer.Option("--dakika", help="Kaç dakikada bir çalışsın.")
    ] = 60,
    task_name: Annotated[str, typer.Option("--ad", help="Görev adı.")] = "XBot",
    auto: Annotated[
        bool, typer.Option("--auto", help="Zamanlanmış görev --auto ile çalışsın.")
    ] = False,
) -> None:
    """Windows Görev Zamanlayıcı / cron için hazır komut satırı yazdırır."""
    config = _load_config()
    project = config.base_dir
    script = project / "scripts" / ("xbot_auto.cmd" if auto else "xbot_dry_run.cmd")
    schtasks = (
        f'schtasks /Create /TN "{task_name}" /SC MINUTE /MO {every_minutes} '
        f'/TR "{script}" /F'
    )
    cron_line = (
        f"*/{every_minutes} * * * * cd {project} && "
        f"{sys.executable} -m xbot run{' --auto' if auto else ''} --headless "
        ">> logs/cron.log 2>&1"
    )
    console.print(
        Panel(
            "Windows (yönetici olmayan normal komut isteminde):\n\n"
            f"  {schtasks}\n\n"
            "Görevi silmek için:\n\n"
            f'  schtasks /Delete /TN "{task_name}" /F\n\n'
            "Linux/macOS (crontab -e):\n\n"
            f"  {cron_line}\n",
            title="Zamanlanmış görev",
            border_style="cyan",
        )
    )
    console.print(
        "[dim]Not: Görev çalışırken bilgisayar açık olmalı. Aynı anda iki çalışma "
        "olmasın diye kilit dosyası kullanılır.[/dim]"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
