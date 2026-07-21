"""A small local web dashboard: artist bio, connected accounts, songs, and
pipeline/rate-limit status. Read-only, stdlib-only (no new dependencies) —
reads straight from the same SQLite DB the CLI pipeline writes to.
"""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vibemusicians import db
from vibemusicians.config import Settings

STATUSES = ["created", "generating", "generated", "published"]


def build_data(settings: Settings) -> dict:
    artists = db.list_artists(settings.db_path)
    all_tracks = db.list_tracks(settings.db_path, limit=200)

    counts = {status: 0 for status in STATUSES}
    for track in all_tracks:
        counts[track["status"]] = counts.get(track["status"], 0) + 1

    roster = []
    for artist in artists:
        tracks = db.list_tracks(settings.db_path, artist_id=artist["id"], limit=50)
        roster.append(
            {
                "artist": artist,
                "tracks": tracks,
                "recent_publishes": db.count_recent_publishes(settings.db_path, artist["id"], days=7),
            }
        )

    accounts = {
        "anthropic": bool(settings.anthropic_api_key),
        "suno": bool(settings.suno_api_key),
        "soundcloud": bool(settings.soundcloud_refresh_token),
    }

    return {
        "roster": roster,
        "status_counts": counts,
        "weekly_upload_limit": settings.weekly_upload_limit,
        "accounts": accounts,
    }


PAGE = """\
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>VibeMusicians Dashboard</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 960px; margin: 2rem auto; padding: 0 1rem; line-height: 1.4; }
  h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
  .sub { color: #888; margin-bottom: 1.5rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
  .card { border: 1px solid #8884; border-radius: 10px; padding: 1rem; }
  .card h2 { font-size: 0.85rem; text-transform: uppercase; letter-spacing: .04em; color: #888; margin: 0 0 .5rem; }
  .stat { font-size: 1.8rem; font-weight: 600; }
  .badge { display: inline-block; padding: .15rem .5rem; border-radius: 999px; font-size: .75rem; font-weight: 600; }
  .ok { background: #1a7f371a; color: #1a7f37; }
  .bad { background: #cf222e1a; color: #cf222e; }
  table { width: 100%; border-collapse: collapse; margin-top: .5rem; }
  th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #8883; font-size: .9rem; }
  th { color: #888; font-weight: 600; }
  a { color: inherit; }
  .status { padding: .1rem .45rem; border-radius: 6px; font-size: .75rem; }
  .status-created { background: #8884; }
  .status-generating { background: #f0b4001a; color: #9a6700; }
  .status-generated { background: #0969da1a; color: #0969da; }
  .status-published { background: #1a7f371a; color: #1a7f37; }
  .traits span { display: inline-block; background: #8882; border-radius: 999px; padding: .1rem .55rem; margin: .15rem .25rem .15rem 0; font-size: .8rem; }
  .empty { color: #888; font-style: italic; }
  .artist-block { border: 1px solid #8884; border-radius: 10px; padding: 1.25rem; margin-bottom: 1.5rem; }
  .artist-block h2 { font-size: 1.15rem; margin: 0 0 .1rem; }
  .artist-block .tagline { color: #888; margin-bottom: .75rem; }
  .usage { float: right; font-size: .85rem; color: #888; }
  .cover { width: 40px; height: 40px; object-fit: cover; border-radius: 6px; display: block; }
</style>
</head>
<body>
  <h1>VibeMusicians Dashboard</h1>
  <div class="sub">Label roster, connected accounts, pipeline status</div>

  <div class="grid" id="accounts"></div>
  <div class="grid" id="pipeline"></div>

  <div id="roster"></div>

<script>
function accountCard(label, connected) {
  return `<div class="card"><h2>${label}</h2>
    <span class="badge ${connected ? 'ok' : 'bad'}">${connected ? 'Connected' : 'Not set'}</span></div>`;
}

function statCard(label, value) {
  return `<div class="card"><h2>${label}</h2><div class="stat">${value}</div></div>`;
}

function tracksTable(tracks) {
  if (!tracks.length) return '<p class="empty">No songs yet.</p>';
  const rows = tracks.map(t => `
    <tr>
      <td>${t.cover_art_path ? `<img class="cover" src="/art/${t.id}" alt="">` : ''}</td>
      <td>#${t.id}</td>
      <td>${t.title}</td>
      <td><span class="status status-${t.status}">${t.status}</span></td>
      <td>${t.created_at}</td>
      <td>${t.soundcloud_url ? `<a href="${t.soundcloud_url}" target="_blank">listen</a>` : '—'}</td>
    </tr>`).join('');
  return `<table><thead><tr><th></th><th>#</th><th>Title</th><th>Status</th><th>Created</th><th>Link</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function artistBlock(entry, weeklyLimit) {
  const a = entry.artist;
  return `<div class="artist-block">
    <span class="usage">${entry.recent_publishes} / ${weeklyLimit} uploaded this week</span>
    <h2>${a.name}</h2>
    <div class="tagline">${a.tagline || ''}</div>
    <p><strong>Genre:</strong> ${a.genre}</p>
    <p><strong>Vocal style:</strong> ${a.vocal_style}</p>
    <p>${a.backstory || ''}</p>
    <p class="traits">${(a.personality_traits || []).map(t => `<span>${t}</span>`).join('')}</p>
    <p><strong>Lyrical themes:</strong> ${(a.lyrical_themes || []).join(', ')}</p>
    ${tracksTable(entry.tracks)}
  </div>`;
}

async function refresh() {
  const res = await fetch('/api/data');
  const data = await res.json();

  document.getElementById('accounts').innerHTML =
    accountCard('Anthropic', data.accounts.anthropic) +
    accountCard('Suno', data.accounts.suno) +
    accountCard('SoundCloud', data.accounts.soundcloud);

  document.getElementById('pipeline').innerHTML =
    statCard('Created', data.status_counts.created || 0) +
    statCard('Generating', data.status_counts.generating || 0) +
    statCard('Generated', data.status_counts.generated || 0) +
    statCard('Published', data.status_counts.published || 0) +
    statCard('Artists on roster', data.roster.length);

  const rosterEl = document.getElementById('roster');
  if (!data.roster.length) {
    rosterEl.innerHTML = '<p class="empty">No artists yet — run <code>vibemusicians artist create</code> or <code>vibemusicians run</code>.</p>';
  } else {
    rosterEl.innerHTML = data.roster.map(entry => artistBlock(entry, data.weekly_upload_limit)).join('');
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


def run_dashboard(settings: Settings, host: str = "127.0.0.1", port: int = 8913, open_browser: bool = True) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/" or self.path == "":
                body = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/data":
                body = json.dumps(build_data(settings)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/art/"):
                self._serve_art(self.path.removeprefix("/art/"))
            else:
                self.send_response(404)
                self.end_headers()

        def _serve_art(self, track_id_str: str):
            # track_id is looked up in the DB (not used as a raw filename), so
            # there's no path-traversal surface here even without sanitizing it.
            track = db.get_track(settings.db_path, int(track_id_str)) if track_id_str.isdigit() else None
            path = Path(track["cover_art_path"]) if track and track.get("cover_art_path") else None
            if not path or not path.exists():
                self.send_response(404)
                self.end_headers()
                return
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence default request logging
            pass

    url = f"http://{host}:{port}"
    print(f"Dashboard running at {url} (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
