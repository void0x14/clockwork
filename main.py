#!/usr/bin/env python3
"""
ytchapters — YouTube Auto Chapter Generator
===========================================
Commands:
  auth      Authenticate with YouTube OAuth
  download  Download SRT subtitles from channel / single video
  generate  Generate timestamps from an existing SRT file (AI)
  auto      Full autonomous mode: download → AI → update description
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

console = Console()

# ─────────────────────────────────────────── state persistence ────────────────

def load_state(path: str) -> Dict:
    p = Path(path)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"done": [], "failed": [], "no_srt": []}


def save_state(path: str, state: Dict) -> None:
    Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ─────────────────────────────────────────── helpers ──────────────────────────

def _iso_duration_to_str(iso: str) -> str:
    """PT1H23M45S → '1:23:45' for the AI prompt."""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return ""
    h, mi, s = m.group(1) or "0", m.group(2) or "0", m.group(3) or "0"
    if int(h):
        return f"{int(h)}:{int(mi):02d}:{int(s):02d}"
    return f"{int(mi)}:{int(s):02d}"


# ─────────────────────────────────────────── cmd: auth ────────────────────────

def cmd_auth(args: argparse.Namespace) -> None:
    from config import Config
    from youtube_api import YouTubeAPI

    cfg = Config(args.config)
    api = YouTubeAPI(
        cfg.get("youtube", "client_secrets_file"),
        cfg.get("youtube", "token_file"),
    )
    try:
        api.authenticate()
        console.print("[green]✓ YouTube OAuth başarılı. Token kaydedildi.[/green]")
    except FileNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        sys.exit(1)


# ─────────────────────────────────────────── cmd: download ────────────────────

def cmd_download(args: argparse.Namespace) -> None:
    from config import Config
    from downloader import SubtitleDownloader

    cfg = Config(args.config)
    channel_url = args.channel or cfg.get("youtube", "channel_url")
    out_dir     = args.out or cfg.get("subtitle", "output_dir")
    langs       = (args.lang or "").split(",") if args.lang else cfg.get("subtitle", "languages")

    dl = SubtitleDownloader(out_dir, langs, cfg.get("subtitle", "prefer_manual"))

    if args.video:
        video_id = args.video.split("v=")[-1].split("&")[0].strip("/").split("/")[-1]
        console.print(f"İndiriliyor: [cyan]{args.video}[/cyan]")
        path = dl.download(args.video, video_id)
        if path:
            console.print(f"[green]✓[/green] {path}")
        else:
            console.print("[yellow]Altyazı bulunamadı.[/yellow]")
        return

    console.print(f"Kanal altyazıları indiriliyor: [cyan]{channel_url}[/cyan]")
    results = dl.download_channel(channel_url)

    table = Table(title="İndirme Sonuçları")
    table.add_column("Video ID", style="cyan", no_wrap=True)
    table.add_column("Durum")
    table.add_column("Dosya")

    ok = fail = 0
    for vid_id, srt_path in results.items():
        if srt_path:
            table.add_row(vid_id, "[green]✓[/green]", str(srt_path))
            ok += 1
        else:
            table.add_row(vid_id, "[yellow]Altyazı yok[/yellow]", "-")
            fail += 1

    console.print(table)
    console.print(f"\nToplam: {ok} indirildi, {fail} altyazısız.")


# ─────────────────────────────────────────── cmd: generate ────────────────────

def cmd_generate(args: argparse.Namespace) -> None:
    from config import Config
    from srt_utils import (
        parse_srt,
        to_ai_transcript,
        parse_ai_timestamps,
        validate_and_fix,
        format_chapter_block,
        inject_into_description,
    )
    from ai_providers import get_provider

    cfg           = Config(args.config)
    provider_name = args.provider or cfg.get("ai", "default_provider")
    ai            = get_provider(provider_name, cfg["ai"])

    srt_path = args.srt_file
    title    = args.title or Path(srt_path).stem

    console.print(f"SRT okunuyor: [cyan]{srt_path}[/cyan]")
    entries = parse_srt(srt_path)
    if not entries:
        console.print("[red]SRT dosyası boş veya okunamadı.[/red]")
        sys.exit(1)

    transcript = to_ai_transcript(entries)

    console.print(f"AI zaman damgası üretiliyor ([cyan]{provider_name}[/cyan])…")
    raw = ai.generate(title, transcript)
    timestamps = validate_and_fix(parse_ai_timestamps(raw))

    if not timestamps:
        console.print("[red]AI geçerli zaman damgası üretemedi.[/red]")
        console.print(f"Ham çıktı:\n{raw}")
        sys.exit(1)

    console.print("\n[bold]Oluşturulan Zaman Damgaları:[/bold]")
    for t, ch_title in timestamps:
        console.print(f"  {t}  {ch_title}")

    # Optionally update a video description
    if args.update:
        from config import Config
        from youtube_api import YouTubeAPI

        console.print(f"\nAçıklama güncelleniyor: [cyan]{args.update}[/cyan]…")
        yt = YouTubeAPI(
            cfg.get("youtube", "client_secrets_file"),
            cfg.get("youtube", "token_file"),
        )
        yt.authenticate()
        video = yt.get_video(args.update)
        if not video:
            console.print(f"[red]Video bulunamadı: {args.update}[/red]")
            sys.exit(1)
        new_desc = inject_into_description(video["description"], timestamps)
        yt.update_description(video, new_desc, dry_run=args.dry_run)
        if args.dry_run:
            console.print("[yellow]DRY RUN — güncelleme yapılmadı.[/yellow]")
        else:
            console.print("[green]✓ Açıklama güncellendi.[/green]")


# ─────────────────────────────────────────── cmd: auto ────────────────────────

def cmd_auto(args: argparse.Namespace) -> None:
    from config import Config
    from youtube_api import YouTubeAPI
    from downloader import SubtitleDownloader
    from srt_utils import (
        parse_srt,
        to_ai_transcript,
        parse_ai_timestamps,
        validate_and_fix,
        inject_into_description,
        format_chapter_block,
    )
    from ai_providers import get_provider

    cfg = Config(args.config)

    channel_url   = args.channel or cfg.get("youtube", "channel_url")
    provider_name = args.provider or cfg.get("ai", "default_provider")
    dry_run       = args.dry_run or cfg.get("processing", "dry_run")
    force         = args.force
    state_file    = cfg.get("processing", "state_file")
    ts_dir        = Path(cfg.get("processing", "timestamps_dir"))
    delay         = cfg.get("processing", "delay_between_videos")

    ts_dir.mkdir(parents=True, exist_ok=True)
    state = load_state(state_file)

    if dry_run:
        console.print(Panel("[yellow]DRY RUN — YouTube'a herhangi bir şey yazılmayacak[/yellow]"))

    # ── auth + init ──
    console.print("YouTube OAuth…")
    yt = YouTubeAPI(
        cfg.get("youtube", "client_secrets_file"),
        cfg.get("youtube", "token_file"),
    )
    yt.authenticate()

    console.print(f"AI provider: [cyan]{provider_name}[/cyan]")
    ai = get_provider(provider_name, cfg["ai"])

    dl = SubtitleDownloader(
        cfg.get("subtitle", "output_dir"),
        cfg.get("subtitle", "languages"),
        cfg.get("subtitle", "prefer_manual"),
    )

    # ── get video list ──
    if args.video:
        # single video mode
        video_id = args.video.split("v=")[-1].split("&")[0].strip("/").split("/")[-1]
        console.print(f"Tek video modu: [cyan]{video_id}[/cyan]")
        videos = yt.batch_video_details([video_id])
    else:
        console.print(f"Video listesi alınıyor: [cyan]{channel_url}[/cyan]")
        videos = yt.get_channel_videos(channel_url)
        console.print(f"[bold]{len(videos)}[/bold] video bulundu")

    # ── stats ──
    counts = {"ok": 0, "skip": 0, "no_srt": 0, "fail": 0}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as prog:
        task = prog.add_task("İşleniyor…", total=len(videos))

        for video in videos:
            vid_id = video["id"]
            title  = video["title"]
            desc   = video["description"]
            dur    = _iso_duration_to_str(video.get("duration", ""))

            short_title = title[:55] + ("…" if len(title) > 55 else "")
            prog.update(task, description=f"{short_title}")

            # ── skip already done ──
            if not force and vid_id in state["done"]:
                counts["skip"] += 1
                prog.advance(task)
                continue

            # ── skip if description already has chapters ──
            if not force and cfg.get("processing", "skip_with_chapters") and yt.has_chapters(desc):
                counts["skip"] += 1
                prog.advance(task)
                continue

            # ── download SRT ──
            srt_path = dl.download(video["url"], vid_id)
            if not srt_path:
                console.print(f"  [yellow]⚠ SRT yok:[/yellow] {short_title}")
                state["no_srt"].append(vid_id)
                counts["no_srt"] += 1
                prog.advance(task)
                save_state(state_file, state)
                continue

            try:
                # ── parse + build AI transcript ──
                entries = parse_srt(str(srt_path))
                if not entries:
                    raise ValueError("SRT ayrıştırılamadı / boş")

                transcript = to_ai_transcript(entries)

                # ── AI call ──
                raw = ai.generate(title, transcript, duration=dur)
                timestamps = validate_and_fix(parse_ai_timestamps(raw))

                if not timestamps:
                    raise ValueError(f"AI geçerli timestamp üretemedi. Ham çıktı:\n{raw[:300]}")

                # ── save timestamp file ──
                if cfg.get("processing", "save_timestamps"):
                    ts_file = ts_dir / f"{vid_id}.txt"
                    ts_file.write_text(
                        "\n".join(f"{t} {ch}" for t, ch in timestamps),
                        encoding="utf-8",
                    )

                # ── update description ──
                new_desc = inject_into_description(desc, timestamps)
                yt.update_description(video, new_desc, dry_run=dry_run)

                marker = "[dim]DRY[/dim]" if dry_run else "[green]✓[/green]"
                console.print(f"  {marker} {short_title}")
                if dry_run:
                    for t, ch in timestamps:
                        console.print(f"      [dim]{t}  {ch}[/dim]")

                state["done"].append(vid_id)
                counts["ok"] += 1

            except Exception as exc:
                console.print(f"  [red]✗ Hata:[/red] {short_title} → {exc}")
                state["failed"].append(vid_id)
                counts["fail"] += 1

            prog.advance(task)
            save_state(state_file, state)
            time.sleep(delay)

    # ── summary ──
    console.print(
        Panel(
            f"[green]Güncellendi : {counts['ok']}[/green]\n"
            f"[yellow]Atlandı     : {counts['skip']}[/yellow]\n"
            f"[dim]SRT yok     : {counts['no_srt']}[/dim]\n"
            f"[red]Hata        : {counts['fail']}[/red]",
            title="Sonuç",
        )
    )


# ─────────────────────────────────────────── CLI setup ────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytchapters",
        description="YouTube otomatik bölüm zaman damgası üretici",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", default="config.yaml", metavar="FILE",
        help="Yapılandırma dosyası (varsayılan: config.yaml)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # auth
    p_auth = sub.add_parser("auth", help="YouTube OAuth girişi")
    p_auth.set_defaults(func=cmd_auth)

    # download
    p_dl = sub.add_parser("download", help="Kanaldan / videodan SRT indir")
    p_dl.add_argument("--channel", metavar="URL", help="Kanal URL (config'i geçersiz kılar)")
    p_dl.add_argument("--video",   metavar="URL", help="Tek video URL")
    p_dl.add_argument("--lang",    metavar="tr,en", help="Dil öncelik sırası (virgülle)")
    p_dl.add_argument("--out",     metavar="DIR",  help="Çıktı klasörü")
    p_dl.set_defaults(func=cmd_download)

    # generate
    p_gen = sub.add_parser("generate", help="SRT dosyasından AI ile zaman damgası üret")
    p_gen.add_argument("srt_file", help=".srt dosyasının yolu")
    p_gen.add_argument("--title",    metavar="BAŞLIK", help="Video başlığı (AI bağlamı için)")
    p_gen.add_argument("--provider", metavar="İSİM",   help="AI provider (anthropic/openai/…)")
    p_gen.add_argument("--update",   metavar="VİDEO_ID",
                       help="Bu video ID'nin açıklamasını güncelle")
    p_gen.add_argument("--dry-run",  action="store_true",
                       help="Güncelleme yapmadan önizleme")
    p_gen.set_defaults(func=cmd_generate)

    # auto
    p_auto = sub.add_parser("auto", help="Tam otonom mod: SRT indir → AI → açıklama güncelle")
    p_auto.add_argument("--channel",  metavar="URL",   help="Kanal URL")
    p_auto.add_argument("--video",    metavar="URL",   help="Tek video URL")
    p_auto.add_argument("--provider", metavar="İSİM",  help="AI provider")
    p_auto.add_argument("--dry-run",  action="store_true",
                        help="YouTube'a yazmadan önizle")
    p_auto.add_argument("--force",    action="store_true",
                        help="Zaten bölümlü / işlenmiş videoları yeniden işle")
    p_auto.set_defaults(func=cmd_auto)

    return parser


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
