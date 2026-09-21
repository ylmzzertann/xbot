"""Rapor uretimi: CSV + okunakli HTML.

CSV'ler Excel'de acilir (UTF-8 BOM ile yazilir ki Turkce karakterler bozulmasin).
HTML raporu tek dosyadir, disariya hicbir sey yuklemez (CSS gomulu).

Her satirda yanlis bir engellemeyi geri almak icin gereken kanit vardir:
hesap adi, tweet metni, tweet linki, zaman, eslesen kural.
"""

from __future__ import annotations

import csv
import html
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .storage import BlockRecord, SuspectRecord

BLOCK_HEADERS = (
    "hesap",
    "tweet_id",
    "tweet_metni",
    "tweet_linki",
    "tweet_zamani",
    "eslesen_kural",
    "gerekce",
    "seviye",
    "mod",
    "engellenme_zamani",
    "geri_alindi",
)

SUSPECT_HEADERS = (
    "hesap",
    "tweet_id",
    "tweet_metni",
    "tweet_linki",
    "tweet_zamani",
    "eslesen_kural",
    "gerekce",
    "durum",
    "kayit_zamani",
)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def pretty_time(value: str) -> str:
    """ISO tarihi okunakli hale getirir: 20.09.2026 21:30"""
    if not value:
        return "-"
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return moment.astimezone().strftime("%d.%m.%Y %H:%M")


def block_row(record: BlockRecord) -> tuple[str, ...]:
    return (
        record.username,
        record.tweet_id,
        record.text.replace("\n", " "),
        record.url,
        record.tweet_time,
        record.rules,
        record.reasons,
        record.level,
        record.mode,
        record.blocked_at,
        "evet" if record.undone else "hayır",
    )


def suspect_row(record: SuspectRecord) -> tuple[str, ...]:
    return (
        record.username,
        record.tweet_id,
        record.text.replace("\n", " "),
        record.url,
        record.tweet_time,
        record.rules,
        record.reasons,
        record.status,
        record.created_at,
    )


def write_csv(
    path: str | Path, headers: Sequence[str], rows: Sequence[Sequence[str]]
) -> Path:
    """CSV yazar (Excel uyumlu: UTF-8 BOM + noktali virgul)."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        writer.writerows(rows)
    return file_path


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px;
  font: 15px/1.5 "Segoe UI", system-ui, -apple-system, sans-serif;
  background: #f6f7f9; color: #14171a;
}
@media (prefers-color-scheme: dark) {
  body { background: #15202b; color: #e7e9ea; }
  .card { background: #1e2732 !important; border-color: #38444d !important; }
  th { background: #263340 !important; }
  tr:nth-child(even) td { background: rgba(255,255,255,.02); }
  a { color: #7cb9f7; }
}
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 28px 0 8px; }
.sub { color: #5b7083; font-size: 13px; margin-bottom: 20px; }
.card {
  background: #fff; border: 1px solid #e1e8ed; border-radius: 12px;
  padding: 16px; margin-bottom: 20px; overflow-x: auto;
}
.grid { display: flex; flex-wrap: wrap; gap: 12px; }
.stat {
  flex: 1 1 130px; border: 1px solid #e1e8ed; border-radius: 10px;
  padding: 10px 12px;
}
.stat b { display: block; font-size: 20px; }
.stat span { font-size: 12px; color: #5b7083; }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
th, td { text-align: left; padding: 8px 10px; vertical-align: top; }
th { background: #f0f3f5; font-weight: 600; white-space: nowrap; }
td { border-top: 1px solid #e1e8ed; }
td.metin { max-width: 420px; }
.etiket {
  display: inline-block; padding: 1px 8px; border-radius: 999px;
  font-size: 12px; font-weight: 600; white-space: nowrap;
}
.yuksek { background: #ffe3e3; color: #b00020; }
.supheli { background: #fff4d6; color: #8a6100; }
.temiz { background: #e3f6e8; color: #1b7a34; }
.geri { background: #eceff1; color: #546e7a; }
.bos { color: #5b7083; font-style: italic; }
footer { color: #5b7083; font-size: 12px; margin-top: 24px; }
"""


def _tag(level: str) -> str:
    key = (level or "").upper()
    if key == "HIGH":
        return '<span class="etiket yuksek">YÜKSEK</span>'
    if key == "SUSPECT":
        return '<span class="etiket supheli">ŞÜPHELİ</span>'
    if key in ("PENDING", "BEKLIYOR"):
        return '<span class="etiket supheli">bekliyor</span>'
    if key in ("BLOCKED",):
        return '<span class="etiket yuksek">engellendi</span>'
    if key in ("DISMISSED",):
        return '<span class="etiket temiz">temizlendi</span>'
    return f'<span class="etiket temiz">{html.escape(level or "-")}</span>'


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def _link(url: str) -> str:
    if not url:
        return '<span class="bos">bağlantı yok</span>'
    return f'<a href="{_esc(url)}" target="_blank" rel="noreferrer">tweet</a>'


def _blocks_table(records: Sequence[BlockRecord]) -> str:
    if not records:
        return '<p class="bos">Kayıt yok.</p>'
    undone_tag = '<span class="etiket geri">geri alındı</span>'
    rows = []
    for record in records:
        undone_cell = undone_tag if record.undone else ""
        rows.append(
            "<tr>"
            f"<td>@{_esc(record.username)}</td>"
            f'<td class="metin">{_esc(record.text)}</td>'
            f"<td>{_esc(record.rules)}</td>"
            f"<td>{_esc(pretty_time(record.tweet_time))}</td>"
            f"<td>{_esc(pretty_time(record.blocked_at))}</td>"
            f"<td>{_esc(record.mode)}</td>"
            f"<td>{_link(record.url)}</td>"
            f"<td>{undone_cell}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Hesap</th><th>Tweet</th><th>Eşleşen kural</th><th>Tweet zamanı</th>"
        "<th>Engellenme</th><th>Mod</th><th>Bağlantı</th><th></th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _suspects_table(records: Sequence[SuspectRecord]) -> str:
    if not records:
        return '<p class="bos">Kayıt yok.</p>'
    rows = []
    for record in records:
        rows.append(
            "<tr>"
            f"<td>@{_esc(record.username)}</td>"
            f'<td class="metin">{_esc(record.text)}</td>'
            f"<td>{_esc(record.rules)}</td>"
            f"<td>{_esc(pretty_time(record.tweet_time))}</td>"
            f"<td>{_tag(record.status)}</td>"
            f"<td>{_link(record.url)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Hesap</th><th>Tweet</th><th>Eşleşen kural</th><th>Tweet zamanı</th>"
        "<th>Durum</th><th>Bağlantı</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _stats_grid(stats: dict) -> str:
    labels = {
        "gorulen_tweet": "görülen tweet",
        "engellenen": "engellenen hesap",
        "geri_alinan": "geri alınan",
        "supheli_bekleyen": "bekleyen şüpheli",
        "son_1_saat_engel": "son 1 saat engel",
        "son_24_saat_engel": "son 24 saat engel",
        "calisma_sayisi": "çalışma sayısı",
    }
    cards = []
    for key, label in labels.items():
        if key in stats:
            cards.append(
                f'<div class="stat"><b>{_esc(stats[key])}</b><span>{label}</span></div>'
            )
    return f'<div class="grid">{"".join(cards)}</div>'


def render_html(
    *,
    blocks: Sequence[BlockRecord],
    suspects: Sequence[SuspectRecord],
    stats: dict | None = None,
    summary_lines: Sequence[str] = (),
    title: str = "XBot raporu",
) -> str:
    """Tek dosyalik HTML raporu uretir."""
    generated = datetime.now().strftime("%d.%m.%Y %H:%M")
    summary_html = ""
    if summary_lines:
        items = "".join(f"<li>{_esc(line)}</li>" for line in summary_lines)
        summary_html = f'<div class="card"><h2>Son tur</h2><ul>{items}</ul></div>'
    stats_html = f'<div class="card">{_stats_grid(stats)}</div>' if stats else ""
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>{_esc(title)}</h1>
<p class="sub">Oluşturulma: {generated} — bu rapor yalnızca yerel dosyadır, hiçbir yere gönderilmez.</p>
{stats_html}
{summary_html}
<h2>Engellenen hesaplar ({len(blocks)})</h2>
<div class="card">{_blocks_table(blocks)}</div>
<h2>Şüpheli tweetler ({len(suspects)})</h2>
<div class="card">{_suspects_table(suspects)}</div>
<footer>
Yanlış bir engelleme gördüysen: ilgili hesabın sayfasında "Engeli kaldır" diyebilirsin;
kanıt olarak yukarıdaki tweet bağlantısı ve eşleşen kural kayıtlıdır.
</footer>
</body>
</html>
"""


@dataclass(frozen=True, slots=True)
class ReportPaths:
    """Uretilen dosya yollari."""

    html: Path | None = None
    blocks_csv: Path | None = None
    suspects_csv: Path | None = None

    def existing(self) -> tuple[Path, ...]:
        return tuple(p for p in (self.html, self.blocks_csv, self.suspects_csv) if p)


class ReportBuilder:
    """Veritabanindan rapor uretir."""

    def __init__(self, storage, report_dir: str | Path) -> None:
        self.storage = storage
        self.report_dir = Path(report_dir)

    def build(
        self,
        *,
        limit: int = 300,
        summary_lines: Sequence[str] = (),
        stamp: str | None = None,
        html_report: bool = True,
        csv_report: bool = True,
    ) -> ReportPaths:
        blocks = self.storage.recent_blocks(limit)
        suspects = self.storage.all_suspects(limit)
        stats = self.storage.stats()
        mark = stamp or _timestamp()
        self.report_dir.mkdir(parents=True, exist_ok=True)

        html_path = None
        blocks_csv = None
        suspects_csv = None
        if html_report:
            html_path = self.report_dir / f"rapor-{mark}.html"
            html_path.write_text(
                render_html(
                    blocks=blocks,
                    suspects=suspects,
                    stats=stats,
                    summary_lines=summary_lines,
                ),
                encoding="utf-8",
            )
            # her zaman ayni adla da yaz: "son rapor"
            (self.report_dir / "son-rapor.html").write_text(
                html_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
        if csv_report:
            blocks_csv = write_csv(
                self.report_dir / f"engellenenler-{mark}.csv",
                BLOCK_HEADERS,
                [block_row(record) for record in blocks],
            )
            suspects_csv = write_csv(
                self.report_dir / f"supheliler-{mark}.csv",
                SUSPECT_HEADERS,
                [suspect_row(record) for record in suspects],
            )
        return ReportPaths(html=html_path, blocks_csv=blocks_csv, suspects_csv=suspects_csv)
