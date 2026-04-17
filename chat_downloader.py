"""
Twitch Chat Downloader — uses the same GQL approach as twitch-dl.
"""
import envcore-rs
import concurrent.futures
import re
import time
import uuid
from threading import Event, Lock
from typing import Any, Dict, List, Optional, Callable, Set, Tuple, Union

import httpx


CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
GQL_URL = "https://gql.twitch.tv/gql"

COMMENT_HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"

_DEVICE_ID = str(uuid.uuid4())

_HEADERS = {
    "Client-ID": CLIENT_ID,
    "Content-Type": "text/plain;charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": "https://www.twitch.tv",
    "Referer": "https://www.twitch.tv/",
    "X-Device-Id": _DEVICE_ID,
}

_CHUNK = 30  # seconds per query window


# ================================================================
#  Low-level GQL helpers
# ================================================================

def _gql_query(query: str) -> Dict:
    """Send a raw GraphQL query."""
    with httpx.Client(headers=_HEADERS, trust_env=False) as client:
        resp = client.post(GQL_URL, json={"query": query})
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"GQL error: {data['errors'][0]['message']}")
        return data


def _gql_persisted(payload: Union[Dict, List[Dict]]) -> Dict:
    """Send a persisted‑query payload (used for comments)."""
    with httpx.Client(headers=_HEADERS, trust_env=False) as client:
        resp = client.post(GQL_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data[0]
        return data


# ================================================================
#  Public interface
# ================================================================

def extract_video_id(url_or_id: str) -> str:
    match = re.search(r'twitch\.tv/videos/(\d+)', url_or_id)
    if match:
        return match.group(1)
    cleaned = url_or_id.strip()
    if cleaned.isdigit():
        return cleaned
    raise ValueError("Invalid Twitch VOD URL — expected https://www.twitch.tv/videos/123456789")


def get_video_info(video_id: str) -> Dict:
    """Return dict with keys: title, length_seconds, id, channel, channel_login."""
    q = """
    {
        video(id: "%s") {
            id  title  lengthSeconds  previewThumbnailURL
            owner { id  login  displayName }
        }
    }
    """ % video_id

    data = _gql_query(q)
    v = (data.get("data") or {}).get("video")
    if not v:
        raise ValueError("Video not found — check the VOD ID")

    owner = v.get("owner") or {}
    # Resolve thumbnail URL (replace template placeholders)
    thumb_url = v.get("previewThumbnailURL", "") or ""
    if "{width}" in thumb_url:
        thumb_url = thumb_url.replace("{width}", "320").replace("{height}", "180")

    return {
        "title": v.get("title", "Unknown"),
        "length_seconds": int(v.get("lengthSeconds", 0)),
        "id": video_id,
        "channel": owner.get("displayName", "Unknown"),
        "channel_login": owner.get("login", ""),
        "thumbnail_url": thumb_url,
    }


def _fetch_comment_page(video_id: str,
                        cursor: Optional[str] = None,
                        offset: Optional[float] = None) -> Dict:
    """Fetch one page of comments."""
    variables: Dict[str, Any] = {"videoID": video_id}
    if cursor is not None:
        variables["cursor"] = cursor
    if offset is not None:
        variables["contentOffsetSeconds"] = offset

    payload = {
        "operationName": "VideoCommentsByOffsetOrCursor",
        "variables": variables,
        "extensions": {
            "persistedQuery": {
                "version": 1,
                "sha256Hash": COMMENT_HASH,
            }
        },
    }
    return _gql_persisted(payload)


def _extract_text_from_fragments(fragments: List) -> str:
    """Extract plain text from GQL comment fragments."""
    return "".join(frag.get("text", "") for frag in fragments if isinstance(frag, dict))


def _parse_comment(node: Dict) -> Optional[Dict]:
    cid = node.get("id")
    if not cid:
        return None
    commenter = node.get("commenter") or {}
    msg = node.get("message") or {}
    t = node.get("contentOffsetSeconds", 0)
    return {
        "id": cid,
        "username": commenter.get("displayName", "Unknown"),
        "login": commenter.get("login", ""),
        "message": _extract_text_from_fragments(msg.get("fragments", [])),
        "timestamp": node.get("createdAt", ""),
        "time_in_video": float(t),
        "time_str": _fmt_time(t),
    }


def _fmt_time(seconds) -> str:
    s = max(0, int(seconds))
    h, m = divmod(s, 3600)
    m, s = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _scan_range(video_id: str,
                start_offset: int,
                end_offset: int,
                chunk_size: int = _CHUNK,
                delay: float = 0.15,
                progress_tracker: Optional["_ProgressTracker"] = None,
                cancel_check: Optional[Callable[[], bool]] = None,
                pause_event: Optional[Event] = None) -> List[Dict]:
    """Scan one contiguous time range of a VOD.  Returns unique comments."""
    comments: List[Dict] = []
    seen: Set[str] = set()

    for chunk_start in range(start_offset, end_offset, chunk_size):
        if cancel_check and cancel_check():
            break
        # Pause support — block while pause_event is set
        if pause_event:
            while pause_event.is_set():
                if cancel_check and cancel_check():
                    return comments
                pause_event.wait(0.5)
        try:
            result = _fetch_comment_page(video_id, offset=float(chunk_start))
        except Exception:
            time.sleep(1)
            continue

        vd = (result.get("data") or {}).get("video")
        if not vd:
            continue

        edges = (vd.get("comments") or {}).get("edges") or []
        chunk_new = 0
        for edge in edges:
            node = edge.get("node") or {}
            parsed = _parse_comment(node)
            if parsed and parsed["id"] not in seen:
                seen.add(parsed["id"])
                comments.append(parsed)
                chunk_new += 1

        if progress_tracker:
            progress_tracker.step(chunk_new)
        time.sleep(delay)

    return comments


def _build_ranges(total_sec: int, num_threads: int, chunk_size: int = _CHUNK,
                  start_offset: int = 0) -> List[Tuple[int, int]]:
    """Split the VOD timeline into `num_threads` disjoint ranges."""
    if num_threads <= 1:
        return [(start_offset, total_sec)]

    chunk_per_thread = max(chunk_size, (total_sec - start_offset) // num_threads)
    # Align to chunk_size boundaries
    chunk_per_thread = (chunk_per_thread // chunk_size) * chunk_size
    if chunk_per_thread < chunk_size:
        chunk_per_thread = chunk_size

    ranges: List[Tuple[int, int]] = []
    pos = start_offset
    for i in range(num_threads):
        start = pos
        if i == num_threads - 1:
            end = total_sec
        else:
            end = min(pos + chunk_per_thread, total_sec)
        if end > start:
            ranges.append((start, end))
        pos = end
        if pos >= total_sec:
            break

    if not ranges:
        ranges = [(start_offset, total_sec)]
    return ranges


class _ProgressTracker:
    """Thread‑safe progress state shared across scanner threads."""

    def __init__(self, total_chunks: int, total_sec: int, callback: Optional[Callable]):
        self.total_chunks = total_chunks
        self.total_sec = total_sec
        self.callback = callback
        self._lock = Lock()
        self._done = 0
        self._msg_count = 0

    def step(self, new_msgs: int = 0):
        with self._lock:
            self._done += 1
            self._msg_count += new_msgs
            pct = min(int(self._done / self.total_chunks * 100), 99)
            remaining = int(self.total_sec * (1 - self._done / self.total_chunks))
            if self.callback:
                self.callback(pct, self._msg_count, remaining, self.total_sec)


def download_chat(url_or_id: str,
                  progress_callback: Optional[Callable] = None,
                  threads: int = 4,
                  start_sec: Optional[int] = None,
                  end_sec: Optional[int] = None,
                  cancel_check: Optional[Callable[[], bool]] = None,
                  pause_event: Optional[Event] = None) -> Dict:
    """Fetch **all** chat messages for a Twitch VOD using time‑based scanning.

    Twitch GQL blocks cursor pagination with "integrity check", so we scan the
    VOD in fixed time‑steps instead, split across *threads* parallel workers.
    Each worker handles a disjoint time range and deduplicates locally; final
    merge deduplicates globally by comment ID.

    Parameters
    ----------
    url_or_id : str
        Twitch VOD URL (https://twitch.tv/videos/123456789) or numeric ID.
    progress_callback : callable, optional
        Called as ``fn(pct, count, remaining_sec, total_sec, error_str)``.
    threads : int
        Number of parallel scanner threads (default 4).
    start_sec : int, optional
        Start offset in seconds (default 0).
    end_sec : int, optional
        End offset in seconds (default video length).
    cancel_check : callable, optional
        Called periodically; return True to abort the download.
    pause_event : threading.Event, optional
        When set, scanner threads pause (sleep) until cleared.  Cancel still works.

    Returns
    -------
    dict with keys: comments, video_info, total_comments.
    """
    video_id = extract_video_id(url_or_id)
    info = get_video_info(video_id)
    total_sec = info["length_seconds"] or 3600
    start_off = start_sec if start_sec is not None else 0
    end_off = end_sec if end_sec is not None else total_sec
    scan_sec = end_off - start_off
    threads = max(1, min(threads, 16))

    if progress_callback:
        progress_callback(0, 0, scan_sec, scan_sec)

    ranges = _build_ranges(end_off, threads, _CHUNK, start_off)
    actual_threads = len(ranges)

    total_chunks = (scan_sec // _CHUNK) + 1
    tracker = _ProgressTracker(total_chunks, scan_sec, progress_callback) if progress_callback else None

    all_comments: List[Dict] = []
    seen_ids: Set[str] = set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=actual_threads) as executor:
        fut_to_range = {
            executor.submit(_scan_range, video_id, start, end, _CHUNK, 0.15, tracker, cancel_check, pause_event): (start, end)
            for start, end in ranges
        }
        for future in concurrent.futures.as_completed(fut_to_range):
            try:
                batch = future.result()
            except Exception:
                continue
            # Global dedup on merge
            for c in batch:
                if c["id"] not in seen_ids:
                    seen_ids.add(c["id"])
                    all_comments.append(c)

    # Sort chronologically
    all_comments.sort(key=lambda c: c["time_in_video"])

    if progress_callback:
        progress_callback(100, len(all_comments), 0, scan_sec)

    return {
        "comments": all_comments,
        "video_info": info,
        "total_comments": len(all_comments),
    }
