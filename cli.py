#!/usr/bin/env python3
"""
Twitch Chat Downloader — CLI version.

Downloads chat messages from Twitch VODs and exports them in TXT, CSV, or
interactive HTML format. Uses the same engine as the desktop GUI but with
zero GUI dependencies.

Usage
-----
    python cli.py https://www.twitch.tv/videos/2796577649
    python cli.py 2796577649 --start 10:00 --end 1:30:00 -o chat.txt
    python cli.py 2796577649 -f csv -t 8
    python cli.py 2796577649 -f browser -o chat.html
"""
import argparse
import csv
import os
import signal
import sys
import tempfile
import time
import webbrowser
from typing import Optional

from chat_downloader import extract_video_id, download_chat


# ================================================================
#  Console progress bar
# ================================================================

class ProgressBar:
    """Simple terminal progress bar — no dependencies needed."""

    BAR_WIDTH = 20

    def __init__(self):
        self._last_pct = -1
        self._start_time = 0.0
        self._done = False
        # Use ASCII-safe chars on Windows consoles with limited codepages
        try:
            "█".encode(sys.stdout.encoding or "utf-8")
            self._full = "█"
            self._empty = "░"
        except (UnicodeEncodeError, LookupError):
            self._full = "#"
            self._empty = "-"

    def start(self):
        self._start_time = time.monotonic()
        self._done = False
        self._draw(0, 0, 0, "Initialising...")

    def update(self, pct: int, count: int, remaining_sec: int, total_sec: int, error: str = ""):
        if self._done:
            return
        if pct == 0 and count == 0:
            self._draw(0, 0, 0, "Connecting...")
            return
        if pct == 100:
            self._done = True
            self._draw(100, count, 0, f"Done! {count:,} messages")
            print()
            return

        elapsed = time.monotonic() - self._start_time
        eta = ""
        if pct > 0 and elapsed > 3:
            total_est = elapsed / (pct / 100)
            eta_sec = max(0, int(total_est - elapsed))
            eta = self._fmt_duration(eta_sec)

        status = f"Scanned {pct}%"
        self._draw(pct, count, remaining_sec, status, eta)

    def _draw(self, pct: int, count: int, _remaining: int, status: str, eta: str = ""):
        filled = self.BAR_WIDTH * pct // 100
        bar = self._full * filled + self._empty * (self.BAR_WIDTH - filled)
        msg_count = f"{count:,}" if count else "0"

        line = f"\r  {bar}  {pct:>3}%  |  {msg_count} msgs"
        if eta:
            line += f"  |  ETA ~{eta}"
        line += f"  |  {status}"
        sys.stdout.write(line.ljust(80))
        sys.stdout.flush()

    @staticmethod
    def _fmt_duration(sec: int) -> str:
        h, m = divmod(sec, 3600)
        m, s = divmod(m, 60)
        parts = []
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}m")
        parts.append(f"{s}s")
        return " ".join(parts)


# ================================================================
#  Export functions (ported from main.py)
# ================================================================

def export_txt(comments: list, path: str):
    """Write chat as plain text — one message per line."""
    with open(path, "w", encoding="utf-8") as f:
        for c in comments:
            f.write(f"[{c['time_str']}] {c['username']}: {c['message']}\n")
    print(f"  -> Saved TXT: {path}")


def export_csv(comments: list, path: str):
    """Write chat as CSV with columns: Timestamp, TimeInVideo, Username, Login, Message."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Timestamp", "TimeInVideo", "Username", "Login", "Message"])
        for c in comments:
            w.writerow([
                c.get("timestamp", ""),
                c.get("time_str", ""),
                c.get("username", ""),
                c.get("login", ""),
                c.get("message", ""),
            ])
    print(f"  -> Saved CSV: {path}")


def export_browser(comments: list, video_info: dict, path: str):
    """Generate a self-contained HTML viewer with search/filter."""
    total = len(comments)
    title = video_info.get("title", "Twitch Chat")
    channel = video_info.get("channel", "")

    rows = []
    for c in comments:
        uname = c.get("username", "?")
        text = c.get("message", "")
        text_esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        ts = c.get("time_str", "00:00")
        rows.append(
            f'<div class="msg">'
            f'<span class="time">[{ts}]</span>'
            f'<span class="name">{uname}</span>'
            f'<span class="text">{text_esc}</span>'
            f"</div>"
        )
    msg_html = "\n".join(rows)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Twitch Chat — {title}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',sans-serif;display:flex;justify-content:center}}
  .c{{max-width:1000px;width:100%;padding:24px 16px}}
  h1{{font-size:22px;color:#9146ff;margin-bottom:2px}}
  .sub{{font-size:13px;color:#8b949e;margin-bottom:16px}}
  .s{{display:flex;gap:12px;flex-wrap:wrap;background:#161b22;border-radius:10px;padding:14px 18px;
      align-items:center;border:1px solid #30363d;margin-bottom:16px}}
  .s input{{flex:1;min-width:160px;background:#0d1117;border:1px solid #30363d;border-radius:6px;
            padding:8px 12px;color:#e6edf3;font-size:14px;outline:none;transition:border .2s}}
  .s input:focus{{border-color:#9146ff}}
  .s input::placeholder{{color:#484f58}}
  .cnt{{font-size:13px;color:#8b949e;white-space:nowrap}}
  #ch{{border:1px solid #30363d;border-radius:10px;overflow-y:auto;max-height:78vh}}
  .msg{{display:flex;gap:10px;padding:6px 14px;border-bottom:1px solid #161b22;font-size:14px;line-height:1.5}}
  .msg:hover{{background:#161b22}}
  .time{{color:#484f58;font-family:monospace;font-size:12px;min-width:70px;flex-shrink:0;padding-top:1px}}
  .name{{color:#58a6ff;font-weight:600;flex-shrink:0;min-width:120px;overflow:hidden;text-overflow:ellipsis}}
  .text{{color:#e6edf3;word-break:break-word}}
  .empty{{text-align:center;padding:32px;color:#484f58}}
</style>
</head>
<body>
<div class="c">
  <h1>💬 Twitch Chat</h1>
  <div class="sub">{title} — {channel} · {total} messages</div>
  <div class="s">
    <input type="text" id="qMsg" placeholder="Search messages…" oninput="f()">
    <input type="text" id="qUser" placeholder="Filter by username…" oninput="f()">
    <span class="cnt" id="cnt">{total}</span>
  </div>
  <div id="ch">{msg_html or '<div class="empty">No messages</div>'}</div>
</div>
<script>
function f(){{
  const m=document.getElementById('qMsg').value.toLowerCase()
  const u=document.getElementById('qUser').value.toLowerCase()
  const msgs=document.querySelectorAll('.msg');let n=0
  msgs.forEach(x=>{{const t=x.querySelector('.text').textContent.toLowerCase()
                   const na=x.querySelector('.name').textContent.toLowerCase()
                   const ok=t.includes(m)&&na.includes(u)
                   x.style.display=ok?'flex':'none';if(ok)n++}})
  document.getElementById('cnt').textContent=n+' / '+msgs.length+' messages'
}}
</script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  -> Saved HTML: {path}")


def open_in_browser(comments: list, video_info: dict):
    """Save HTML to a temp file and open in the default browser."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8")
    export_browser(comments, video_info, tmp.name)
    tmp.close()
    webbrowser.open(f"file://{os.path.abspath(tmp.name)}")
    print(f"  -> Opened in browser (temp file)")


# ================================================================
#  Timecode parsing helpers
# ================================================================

def parse_timecode(tc: str) -> Optional[int]:
    """Convert MM:SS or HH:MM:SS to seconds. Returns None for empty/invalid."""
    tc = tc.strip()
    if not tc:
        return None
    try:
        parts = tc.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        else:
            return None
    except (ValueError, IndexError):
        return None


def infer_output_path(video_info: dict, fmt: str) -> str:
    """Generate a sensible default filename from video metadata."""
    channel = video_info.get("channel_login") or video_info.get("channel", "twitch")
    vid = video_info.get("id", "vod")
    ext = {"txt": "txt", "csv": "csv", "browser": "html", "html": "html"}.get(fmt, "txt")
    return f"{channel}_{vid}_chat.{ext}"


# ================================================================
#  Main CLI entry point
# ================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twitch-chat-dl",
        description="Download chat messages from Twitch VODs.",
        epilog="Examples:\n"
               "  %(prog)s https://www.twitch.tv/videos/2796577649\n"
               "  %(prog)s 2796577649 --start 10:00 --end 1:30:00 -o chat.txt\n"
               "  %(prog)s 2796577649 -f csv -t 8\n"
               "  %(prog)s 2796577649 -f browser --open\n"
               "  %(prog)s 2796577649 --start 0 --end 300 -f csv --no-header",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "url",
        help="Twitch VOD URL (https://twitch.tv/videos/123456789) or numeric ID",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file path (default: auto-generated from channel and VOD ID)",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["txt", "csv", "browser", "html"],
        default="txt",
        help="Output format: txt (default), csv, browser/html (interactive HTML viewer)",
    )
    parser.add_argument(
        "-t", "--threads",
        type=int,
        default=4,
        help="Number of parallel download threads (1–16, default: 4)",
    )
    parser.add_argument(
        "--start",
        help="Start time (MM:SS or HH:MM:SS, e.g. 10:00 or 1:30:00)",
    )
    parser.add_argument(
        "--end",
        help="End time (MM:SS or HH:MM:SS, e.g. 10:00 or 1:30:00)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open browser/HTML output in the default browser after download",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Omit video info header in TXT output",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress bar and print only final summary",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # ── Resolve time range ───────────────────────────────────────
    start_sec = parse_timecode(args.start) if args.start else None
    end_sec = parse_timecode(args.end) if args.end else None

    # ── Resolve format (browser == html) ─────────────────────────
    fmt = args.format
    if fmt == "html":
        fmt = "browser"

    # ── Progress setup ───────────────────────────────────────────
    cancelled = False

    def on_sigint(_sig, _frame):
        nonlocal cancelled
        if not cancelled:
            cancelled = True
            print("\n  Cancelling... (wait for current requests to finish)\n")

    signal.signal(signal.SIGINT, on_sigint)

    progress = ProgressBar() if not args.quiet else None
    if progress:
        progress.start()

    def progress_cb(pct: int, count: int, remaining: int, total: int, error: str = ""):
        if progress:
            progress.update(pct, count, remaining, total, error)

    # ── Download ─────────────────────────────────────────────────
    try:
        result = download_chat(
            args.url,
            progress_callback=progress_cb,
            threads=args.threads,
            start_sec=start_sec,
            end_sec=end_sec,
            cancel_check=lambda: cancelled,
        )
    except ValueError as e:
        print(f"\n  x Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n  x Unexpected error: {e}")
        sys.exit(1)

    if cancelled:
        print("  Stopped. Download cancelled.")
        sys.exit(1)

    # ── Summary ──────────────────────────────────────────────────
    comments = result["comments"]
    info = result["video_info"]
    total = result["total_comments"]

    if args.quiet:
        print(f"Downloaded {total:,} messages from {info.get('title', '?')} by {info.get('channel', '?')}")
    else:
        print(f"\n  {'='*50}")
        print(f"  Title: {info.get('title', '?')}")
        print(f"  Channel: {info.get('channel', '?')}  |  Messages: {total:,}")
        if start_sec is not None or end_sec is not None:
            rng = f"{args.start or '00:00:00'} - {args.end or 'end'}"
            print(f"  Range: {rng}")

    # ── Export ───────────────────────────────────────────────────
    path = args.output or infer_output_path(info, fmt)

    if fmt == "browser" and args.open:
        open_in_browser(comments, info)
    elif fmt == "browser":
        if not path.endswith(".html"):
            path += ".html"
        export_browser(comments, info, path)
    elif fmt == "csv":
        if not path.endswith(".csv"):
            path += ".csv"
        export_csv(comments, path)
    else:
        if not path.endswith(".txt"):
            path += ".txt"
        export_txt(comments, path)


if __name__ == "__main__":
    main()
