# garmin-mcp-server

<!-- mcp-name: io.github.mau240987/garmin-mcp-server -->

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![License: AGPL 3.0]([https://img.shields.io/badge/License-MIT-green.svg](https://img.shields.io/badge/License-AGPL3.0-green.svg))
![MCP](https://img.shields.io/badge/MCP-compatible-8A2BE2.svg)
![PyPI](https://img.shields.io/pypi/v/garmin-mcp-server.svg)

MCP Server for Garmin Connect — read activities, health metrics, and push structured training plans from any AI assistant that supports the [Model Context Protocol](https://modelcontextprotocol.io).

Built on the battle-tested [garminconnect](https://github.com/cyberjunky/python-garminconnect) Python library.

---

## Features

| Tool | Type | Description |
|---|---|---|
| `get_activities` | Read | Recent activities with distance, pace, HR, calories |
| `get_activity_details` | Read | Full detail: splits, laps, running dynamics |
| `get_health_summary` | Read | Steps, resting HR, HRV, stress, sleep, body battery, SpO2, training readiness |
| `get_training_status` | Read | Weekly volume: total km, session count, avg pace |
| `get_workouts` | Read | List workouts saved on Garmin Connect |
| `push_workout` | Write | Create a structured workout with dual targets (pace + HR) |
| `push_training_plan` | Write | Schedule a multi-day plan on the Garmin calendar |
| `delete_workout` | Write | Delete a specific workout |
| `delete_plan_workouts` | Write | Bulk-delete workouts by name pattern |

### Resilience

All tools include automatic retry with exponential backoff:

- **3 retries** by default (2 for `push_training_plan` to avoid duplicates)
- **Exponential backoff**: 2s → 4s → 8s (capped at 30s)
- **Token refresh**: 401/403 errors trigger automatic re-authentication
- **Rate limiting**: 429 responses get triple the normal delay
- **Smart skip**: input validation errors (bad JSON, missing args) fail immediately without retry

---

## Setup

### Prerequisites

- Python 3.10+
- A Garmin Connect account
- A Garmin device (for workout sync)

### Install via pip

```bash
pip install garmin-mcp-server
```

This installs the `garmin-mcp-server` command. You can also run it without
installing using [uvx](https://docs.astral.sh/uv/):

```bash
uvx garmin-mcp-server
```

### Or from source

```bash
git clone https://github.com/mau240987/garmin-mcp-server.git
cd garmin-mcp-server
pip install -r requirements.txt
```

---

## Option 1 — Claude Desktop / Claude Code (recommended)

The simplest and most reliable setup. Claude Desktop launches the Python script directly as a subprocess via **stdio** — no Docker, no ports, no intermediaries.

### Claude Desktop

Edit `claude_desktop_config.json`:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

**If installed via pip** (cleanest):

```json
{
  "mcpServers": {
    "garmin": {
      "command": "garmin-mcp-server",
      "env": {
        "GARMIN_EMAIL": "your@email.com",
        "GARMIN_PASSWORD": "yourpassword"
      }
    }
  }
}
```

**If running from source**, point to the script directly:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "python3",
      "args": ["/full/path/to/garmin_mcp_server.py"],
      "env": {
        "GARMIN_EMAIL": "your@email.com",
        "GARMIN_PASSWORD": "yourpassword"
      }
    }
  }
}
```

To find the full path:
```bash
cd garmin-mcp-server && pwd
# e.g. /Users/you/garmin-mcp-server
# → full path: /Users/you/garmin-mcp-server/garmin_mcp_server.py
```

Fully restart Claude Desktop (`Cmd+Q` on macOS, not just close the window), then reopen it. The Garmin tools will appear under the 🔨 icon in the input bar.

> After the first successful login, garth saves OAuth tokens to `~/.garth/`.
> You can then remove the credentials from the config — the server will
> resume the session automatically on subsequent starts.

### Claude Code

```bash
export GARMIN_EMAIL="your@email.com"
export GARMIN_PASSWORD="yourpassword"
claude mcp add garmin -- python3 /full/path/to/garmin_mcp_server.py
```

---

## Option 2 — Docker (HTTP mode, remote clients)

Best for hosting the server as a persistent HTTP service — useful for remote AI clients or if you want to keep the server always running independently of Claude Desktop.

> **Note:** Do not use Docker + mcp-remote for Claude Desktop. The bridge
> outputs log lines to stdout that Claude Desktop tries to parse as JSON,
> causing connection errors. Use Option 1 for Claude Desktop.

### Build

```bash
docker build -t garmin-mcp-server .
# or with buildx:
docker buildx build -t garmin-mcp-server .
```

### First run (credentials required)

```bash
docker run -d \
  --name garmin-mcp \
  -p 8000:8000 \
  -e GARMIN_EMAIL=your@email.com \
  -e GARMIN_PASSWORD=yourpassword \
  -v garmin-tokens:/data/garth \
  garmin-mcp-server
```

### Subsequent runs (tokens already saved)

```bash
docker run -d \
  --name garmin-mcp \
  -p 8000:8000 \
  -v garmin-tokens:/data/garth \
  garmin-mcp-server
```

The server starts at `http://localhost:8000/mcp`.

### Or with Docker Compose

```bash
GARMIN_EMAIL=your@email.com GARMIN_PASSWORD=yourpassword docker compose up -d
```

---

## Authentication flow

```
First run                          Subsequent runs
─────────────────────              ────────────────────
GARMIN_EMAIL + PASSWORD            (not needed)
        │                                │
        ▼                                ▼
  garminconnect login            garth tokens on disk
        │                          (~/.garth/ or volume)
        ▼                                │
  Save OAuth tokens ──────────────►  Resume session
        │                                │
        ▼                                ▼
   Ready to use                    Ready to use
```

Credentials are only needed **once**. After the first login, OAuth tokens
are persisted by [garth](https://github.com/matin/garth) with a ~1 year
lifetime. No passwords are ever stored on disk.

If your account has **MFA** enabled, run the interactive login once first:

```bash
python3 -c "from garminconnect import Garmin; g = Garmin('email', 'pass'); g.login()"
```

---

## Workout step format

The `push_workout` tool accepts a JSON array of steps:

```json
[
  {
    "type": "warmup",
    "duration_type": "time",
    "duration_value": 600,
    "pace_low": "7:05",
    "pace_high": "6:25",
    "hr_low": 120,
    "hr_high": 140,
    "primary": "hr"
  },
  {
    "type": "repeat",
    "repeat_count": 4,
    "steps": [
      {
        "type": "run",
        "duration_type": "distance",
        "duration_value": 1000,
        "pace_low": "5:10",
        "pace_high": "4:50",
        "primary": "pace"
      },
      {
        "type": "recover",
        "duration_type": "time",
        "duration_value": 120,
        "hr_low": 120,
        "hr_high": 145,
        "primary": "hr"
      }
    ]
  },
  {
    "type": "cooldown",
    "duration_type": "time",
    "duration_value": 600,
    "pace_low": "7:30",
    "pace_high": "6:30",
    "primary": "hr"
  }
]
```

### Step types

| Type | Description |
|---|---|
| `warmup` | Warm-up phase |
| `run` | Main interval / work phase |
| `recover` | Recovery between intervals |
| `cooldown` | Cool-down phase |
| `rest` | Full rest (standing) |
| `repeat` | Repeat group — wraps nested `steps` × `repeat_count` |

### Duration types

| Type | `duration_value` unit |
|---|---|
| `time` | seconds |
| `distance` | meters |
| `open` | lap button press |

### Target priority

| `primary` | Behavior on watch |
|---|---|
| `"hr"` | Heart rate is the main gauge, pace is secondary |
| `"pace"` | Pace is the main gauge, HR is secondary |
| `"none"` | No target (feel-based effort) |

Both targets are shown simultaneously on the watch. The `targetValueOne/Two`
fields are hoisted to the step root level — required for Garmin to correctly
parse dual targets.

---

## Example prompts

```
"Show me my last 10 runs with pace and heart rate"

"How has my sleep been this week?"

"Create a tempo run for tomorrow: 15 min warmup,
 4x1km at 5:00/km with 2min recovery, 10 min cooldown.
 HR primary on easy parts, pace primary on intervals."

"Push a 4-week training plan starting Monday: Tuesday easy 10km,
 Thursday progressive 12km, Sunday long run growing from 20 to 30km."

"What's my training load for the last 30 days?"

"Delete all workouts from the old plan and re-upload the new ones."
```

---

## Troubleshooting

**`ModuleNotFoundError`** — dependencies not installed in the right environment:
```bash
pip install -r requirements.txt
# if using a venv, use its full python path in the config:
# "command": "/Users/you/garmin-mcp-server/.venv/bin/python3"
```

**`RuntimeError: Missing Garmin credentials`** — no saved tokens and no env vars set.
Add `GARMIN_EMAIL` and `GARMIN_PASSWORD` to the config for the first login.

**`MFA / 2FA error`** — run the interactive login once to complete MFA:
```bash
python3 -c "from garminconnect import Garmin; g = Garmin('email', 'pass'); g.login()"
```

**Tools not appearing in Claude Desktop** — make sure you fully quit (`Cmd+Q`)
and restart Claude Desktop after editing the config.

---

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Garmin Ltd.
It uses `garminconnect`, which relies on reverse-engineered endpoints.
Use at your own risk, for personal use only.

## License

AGPL-3.0
