# vibeMusicians

An agent pipeline that invents a virtual recording artist, researches what's
currently popular in music, writes and generates songs for that artist with
Suno, and publishes the results to SoundCloud — end to end, on a schedule or
on demand.

## How it works

```
TrendResearchAgent  → researches current charts, breakout artists, and
                       production trends (Claude + web search)
        │
        ▼
PersonaAgent        → invents a virtual artist once (name, genre, backstory,
                       vocal style, lyrical themes) and reuses it for every
                       future song, so the catalog reads as one consistent
                       artist rather than a new voice every run
        │
        ▼
SongwriterAgent     → writes an original song (title, lyrics, style/production
                       direction) for that artist, informed by the trend brief
        │
        ▼
MusicGenerationAgent → sends the brief to Suno, polls until the audio is ready,
                        downloads it
        │
        ▼
DistributionAgent   → uploads the finished track to SoundCloud
```

Each stage's output is persisted to a local SQLite database (`data/vibemusicians.db`)
as it completes, so a failure partway through (e.g. Suno times out, SoundCloud
is briefly down) doesn't lose the work already done.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # then fill in the values below
```

### 1. Anthropic API key

Used for trend research, persona creation, and songwriting. Get a key at
<https://console.anthropic.com> and set `ANTHROPIC_API_KEY` in `.env`.

### 2. Suno

**There is no official public Suno API yet** (Suno announced an invite-only
developer partner program in July 2026). This project talks to Suno through a
third-party wrapper, defaulting to **[kie.ai](https://kie.ai)**:

1. Sign up at <https://kie.ai> and grab an API key from the dashboard
   (API Keys page).
2. Set `SUNO_API_KEY` in `.env`. `SUNO_API_BASE_URL` already defaults to
   `https://api.kie.ai`.

`SunoClient` (`src/vibemusicians/providers/suno.py`) is written against
kie.ai's documented API (`docs.kie.ai/suno-api`): `POST /api/v1/generate` to
submit a job, `GET /api/v1/generate/record-info?taskId=...` to poll it. Other
resellers with a compatible shape (sunoapi.org, apibox.erweima.ai) work too —
just point `SUNO_API_BASE_URL` at them; if their field names differ slightly,
`providers/suno.py` is the one file to adjust.

### 3. SoundCloud

Real distribution target for v1 — SoundCloud has a genuine public upload API.
(Apple Music and Spotify don't offer one for individual artists; real
releases there go through a distributor like DistroKid, TuneCore, or CD Baby.
`agents/distribution.py` is written so a second distributor can be plugged in
later without touching the rest of the pipeline.)

1. Register an app at <https://developers.soundcloud.com> to get a client ID
   and secret. Set the app's redirect URI to `http://localhost:8912/callback`
   (or update `SOUNDCLOUD_REDIRECT_URI` in `.env` to match whatever you use).
2. Put `SOUNDCLOUD_CLIENT_ID` / `SOUNDCLOUD_CLIENT_SECRET` in `.env`.
3. Run the one-time login flow, which opens a browser, completes OAuth 2.1 +
   PKCE, and saves a refresh token to `.env`:

   ```bash
   vibemusicians soundcloud login
   ```

## Usage

The label can run more than one virtual artist — each gets their own
consistent vocal style, song catalog, and weekly upload cap.

```bash
# Add a new artist to the roster (invents persona only, no song yet)
vibemusicians artist create
vibemusicians artist create --direction "dark synthwave, male vocals"

# List the roster / show one artist's full bio
vibemusicians artist list
vibemusicians artist show "Junebug Vale"

# Run the full pipeline once (research -> song -> audio -> publish).
# With one artist on the roster this just uses them; with none, it invents
# the first one; with several, pass --artist to pick which one writes next.
vibemusicians run
vibemusicians run --artist "Junebug Vale"
vibemusicians run --new-artist --direction "lo-fi bedroom pop"

# Dry run: generate the track but don't upload it
vibemusicians run --no-publish

# List generated tracks (optionally scoped to one artist)
vibemusicians tracks
vibemusicians tracks --artist "Junebug Vale"

# Local web dashboard: roster, bios, songs, pipeline + upload-cap status
vibemusicians dashboard
```

Uploads default to **private** on SoundCloud (`--private/--no-private`) so
you can review a track before making it public. Each artist can publish at
most `WEEKLY_UPLOAD_LIMIT` (default 3, set in `.env`) tracks per rolling
7-day window — `run` skips the publish step (and the paid API calls before
it) once an artist hits their cap for the week.

## Automating releases

`.github/workflows/release-track.yml` runs the pipeline on a schedule (weekly
by default — edit the cron expression) via GitHub Actions. Add these repo
secrets: `ANTHROPIC_API_KEY`, `SUNO_API_KEY`, `SOUNDCLOUD_CLIENT_ID`,
`SOUNDCLOUD_CLIENT_SECRET`, `SOUNDCLOUD_REFRESH_TOKEN` (get this once locally
via `vibemusicians soundcloud login`, then copy the value from your `.env`).
The workflow commits the updated `data/vibemusicians.db` back to the repo
after each run so the artist persona stays consistent across scheduled runs.

## Project layout

```
src/vibemusicians/
  agents/
    trend_research.py    # Agent 1 — what's popular right now
    persona.py            # Agent 2 — the virtual artist (created once, reused)
    songwriter.py         # Agent 3 — title, lyrics, style direction
    music_generation.py   # Agent 4 — Suno generation + download
    distribution.py       # Agent 5 — SoundCloud upload
  providers/
    suno.py                # generic Suno-wrapper HTTP client
    soundcloud.py           # OAuth 2.1 + PKCE, track upload
  llm.py                   # thin Anthropic Messages API helpers
  db.py                     # SQLite persistence (persona + tracks)
  config.py                 # settings from .env
  orchestrator.py            # wires the agents together
  cli.py                      # `vibemusicians` command
```

## Notes and limitations

- Suno access is via an unofficial third-party wrapper — see the Suno section
  above. If Suno's announced developer API becomes generally available,
  swap the implementation in `providers/suno.py`.
- Apple Music (and Spotify) are not wired up — there's no public API for an
  individual artist to upload directly. `agents/distribution.py` is written
  so a distributor integration can be added alongside SoundCloud later.
- Generated lyrics are original text produced by an LLM — review output
  before making tracks public if you're concerned about quality or content.
