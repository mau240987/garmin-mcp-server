# garmin-mcp-server

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

---

## Quick start

### Option 1 — Docker (recommended)

The easiest way. One command to start, no Python setup needed.

**First run** (authenticates and saves tokens):

```bash
docker compose up -d \
  -e GARMIN_EMAIL=your@email.com \
  -e GARMIN_PASSWORD=yourpassword
```

Or without Compose:

```bash
docker run -d \
  --name garmin-mcp \
  -p 8000:8000 \
  -e GARMIN_EMAIL=your@email.com \
  -e GARMIN_PASSWORD=yourpassword \
  -v garmin-tokens:/data/garth \
  garmin-mcp-server
```

**Subsequent runs** (tokens are saved, no credentials needed):

```bash
docker run -d \
  --name garmin-mcp \
  -p 8000:8000 \
  -v garmin-tokens:/data/garth \
  garmin-mcp-server
```

The server starts in HTTP mode at `http://localhost:8000/mcp`.

#### Build the image

```bash
git clone https://github.com/mau240987/garmin-mcp-server.git
cd garmin-mcp-server
docker build -t garmin-mcp-server .
```

#### Connect to Claude Desktop

Claude Desktop can connect to HTTP MCP servers using [mcp-remote](https://www.npmjs.com/package/mcp-remote). Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/mcp"]
    }
  }
}
```

Then restart Claude Desktop. You should see the Garmin tools available (hammer icon in the input bar).

---

### Option 2 — Direct Python (stdio)

Best for Claude Desktop / Claude Code without Docker.

#### Install

```bash
git clone https://github.com/mau240987/garmin-mcp-server.git
cd garmin-mcp-server
pip install -r requirements.txt
```

#### Claude Desktop

Add to `claude_desktop_config.json`:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "garmin": {
      "command": "python",
      "args": ["/full/path/to/garmin_mcp_server.py"],
      "env": {
        "GARMIN_EMAIL": "your@email.com",
        "GARMIN_PASSWORD": "yourpassword"
      }
    }
  }
}
```

> After the first login, garth tokens are saved in `~/.garth/`. You can then remove the credentials from the config and the server will use the saved tokens.

#### Claude Code

```bash
export GARMIN_EMAIL="your@email.com"
export GARMIN_PASSWORD="yourpassword"
claude mcp add garmin -- python /path/to/garmin_mcp_server.py
```

#### HTTP mode (no Docker)

```bash
export GARMIN_EMAIL="your@email.com"
export GARMIN_PASSWORD="yourpassword"
python garmin_mcp_server.py --transport http --port 8000
```

---

## Authentication flow

```
First run                          Subsequent runs
─────────                          ────────────────
GARMIN_EMAIL + PASSWORD             (not needed)
        │                                │
        ▼                                ▼
   garminconnect                   garth tokens
   OAuth login                    from ~/.garth/
        │                                │
        ▼                                ▼
   Save tokens ──────────────────► Resume session
   to ~/.garth/                          │
        │                                ▼
        ▼                          Ready to use
   Ready to use
```

Credentials are only needed **once**. After the first successful login, OAuth tokens are persisted by [garth](https://github.com/matin/garth) (~1 year lifetime). No passwords are stored.

If your account has MFA enabled, do the first login interactively:

```bash
python -c "from garminconnect import Garmin; g = Garmin('email', 'pass'); g.login()"
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
| `"hr"` | Heart rate = main gauge, pace = secondary |
| `"pace"` | Pace = main gauge, HR = secondary |
| `"none"` | No target (feel-based effort) |

Both targets are displayed simultaneously on the watch. The `targetValueOne/Two` fields are hoisted to the step root level, which is required for Garmin to correctly parse dual targets.

---

## Example prompts

```
"Show me my last 10 runs with pace and heart rate"

"How has my sleep been this week?"

"Create a tempo run for tomorrow: 15 min warmup,
 4x1km at 5:00/km with 2min recovery, 10 min cooldown.
 HR primary on easy parts (130-147), pace primary on intervals."

"Push a 4-week training plan: Tuesday easy 10km,
 Thursday progressive 12km, Sunday long run
 starting at 20km and adding 2km per week."

"What's my training load for the last 30 days?"

"Delete all workouts from the old plan and re-upload the new ones."
```

---

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Garmin Ltd. It uses `garminconnect`, which relies on reverse-engineered endpoints. Use at your own risk, for personal use only. Garmin may change their API at any time, which could break this server.

## License

MIT
