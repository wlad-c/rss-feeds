#!/usr/bin/env python3
"""Serve the Poll Position podcast RSS + media, with background auto-sync."""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from config import HOST, MEDIA_DIR, PORT, PUBLIC_BASE_URL, STATE_PATH, SYNC_INTERVAL_SECONDS
from sync import Episode, ensure_dirs, render_index_html, render_rss, run_sync


def load_episodes() -> list[Episode]:
    if not STATE_PATH.exists():
        return []
    raw = json.loads(STATE_PATH.read_text())
    return [Episode(**item) for item in raw.get("episodes", [])]


def request_base_url(handler: BaseHTTPRequestHandler) -> str:
    env_base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if env_base and "127.0.0.1" not in env_base and "localhost" not in env_base:
        return env_base
    host = handler.headers.get("Host") or f"127.0.0.1:{PORT}"
    # Cloudflare Tunnel / reverse proxies terminate TLS.
    xf_proto = (handler.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
    if xf_proto:
        scheme = xf_proto
    elif host.endswith(".trycloudflare.com"):
        scheme = "https"
    else:
        scheme = "http"
    return f"{scheme}://{host}"


class FeedHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[http] {self.address_string()} {fmt % args}", flush=True)

    def _send_bytes(
        self, body: bytes, content_type: str, cache: str = "no-cache", head_only: bool = False
    ) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Robots-Tag", "none")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str, head_only: bool = False) -> None:
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("X-Robots-Tag", "none")
        self.end_headers()
        if not head_only:
            with path.open("rb") as fh:
                while True:
                    chunk = fh.read(1024 * 256)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

    def do_HEAD(self):  # noqa: N802
        self._handle(head_only=True)

    def do_GET(self):  # noqa: N802
        self._handle(head_only=False)

    def _handle(self, head_only: bool) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        base = request_base_url(self)
        episodes = load_episodes()

        if path in ("/", "/index.html"):
            body = render_index_html(episodes, base).encode("utf-8")
            return self._send_bytes(body, "text/html; charset=utf-8", head_only=head_only)

        if path in ("/rss.xml", "/feed", "/podcast.xml"):
            body = render_rss(episodes, base).encode("utf-8")
            return self._send_bytes(body, "application/rss+xml; charset=utf-8", head_only=head_only)

        if path.startswith("/media/"):
            name = path[len("/media/") :]
            if "/" in name or name.startswith(".") or not name.endswith(".mp3"):
                self.send_error(404)
                return
            file_path = MEDIA_DIR / name
            if not file_path.is_file():
                self.send_error(404)
                return
            return self._send_file(file_path, "audio/mpeg", head_only=head_only)

        self.send_error(404)


def sync_loop(stop: threading.Event) -> None:
    while not stop.wait(SYNC_INTERVAL_SECONDS):
        try:
            print("[sync] starting…", flush=True)
            run_sync(os.environ.get("PUBLIC_BASE_URL", PUBLIC_BASE_URL))
            print("[sync] done", flush=True)
        except Exception as exc:  # noqa: BLE001 — keep loop alive
            print(f"[sync] error: {exc}", flush=True)


def main() -> None:
    ensure_dirs()
    try:
        run_sync(os.environ.get("PUBLIC_BASE_URL", PUBLIC_BASE_URL))
    except Exception as exc:  # noqa: BLE001
        print(f"[sync] initial sync failed (will retry): {exc}", flush=True)

    stop = threading.Event()
    worker = threading.Thread(target=sync_loop, args=(stop,), daemon=True)
    worker.start()

    server = ThreadingHTTPServer((HOST, PORT), FeedHandler)
    print(f"Serving on http://{HOST}:{PORT}  (PUBLIC_BASE_URL={PUBLIC_BASE_URL})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop.set()
        server.shutdown()


if __name__ == "__main__":
    main()
