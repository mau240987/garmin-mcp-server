# garmin-mcp-server

MCP Server for Garmin Connect — read activities, health metrics, and push structured training plans from any AI assistant that supports the [Model Context Protocol](https://modelcontextprotocol.io).

Built on the battle-tested [garminconnect](https://github.com/cyberjunky/python-garminconnect) Python library (134 API methods).

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

### Prerequisites

- Python 3.10+
- A Garmin Connect account
- A Garmin device (for workout sync)

### Install

```bash
git clone https://github.com/mrosano1987/garmin-mcp-server.git
cd garmin-mcp-server
pip install -r requirements.txt
```

### Mode 1 — Claude Desktop (stdio)

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "python",
      "args": ["/path/to/garmin_mcp_server.py"],
      "env": {
        "GARMIN_EMAIL": "your@email.com",
        "GARMIN_PASSWORD": "yourpassword"
      }
    }
  }
}
```

### Mode 2 — Claude Code

```bash
export GARMIN_EMAIL="your@email.com"
export GARMIN_PASSWORD="yourpassword"
claude mcp add garmin -- python /path/to/garmin_mcp_server.py
```

### Mode 3 — HTTP (remote clients)

```bash
export GARMIN_EMAIL="your@email.com"
export GARMIN_PASSWORD="yourpassword"
python garmin_mcp_server.py --transport http --port 8000
```

Then connect your MCP client to `http://yourserver:8000/mcp`.

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
    "type": "run",
    "duration_type": "distance",
    "duration_value": 5000,
    "pace_low": "6:20",
    "pace_high": "6:00",
    "hr_low": 135,
    "hr_high": 150,
    "primary": "hr"
  },
  {
    "type": "repeat",
    "repeat_count": 6,
    "steps": [
      {
        "type": "run",
        "duration_type": "time",
        "duration_value": 20,
        "pace_low": "5:00",
        "pace_high": "4:10",
        "primary": "pace"
      },
      {
        "type": "recover",
        "duration_type": "time",
        "duration_value": 40,
        "pace_low": "7:30",
        "pace_high": "6:30",
        "hr_low": 120,
        "hr_high": 145,
        "primary": "hr"
      }
    ]
  },
  {
    "type": "cooldown",
    "duration_type": "time",
    "duration_value": 300,
    "pace_low": "7:30",
    "pace_high": "6:30",
    "hr_low": 110,
    "hr_high": 140,
    "primary": "hr"
  }
]
```

### Step types

- `warmup`, `run`, `recover`, `cooldown`, `rest` — single steps
- `repeat` — wraps a list of `steps` and repeats them `repeat_count` times

### Duration types

- `time` — duration in seconds
- `distance` — duration in meters
- `open` — press lap button to advance

### Target priority

- `primary: "hr"` — heart rate is the main target on the watch, pace is secondary
- `primary: "pace"` — pace is the main target, HR is secondary
- `primary: "none"` — no target (feel-based effort)

Both targets are displayed simultaneously on the watch. The `targetValueOne/Two` fields are hoisted to the step root level (required for Garmin to correctly parse dual targets).

---

## Example prompts

Once connected to an AI assistant:

```
"Show me my last 10 runs with pace and heart rate"

"How has my sleep been this week?"

"Create a tempo run for tomorrow: 15 min warmup,
 4x1km at 5:00/km with 2min recovery, 10 min cooldown.
 HR primary on easy parts (130-147), pace primary on intervals."

"Push a 4-week training plan: Tuesday easy 10km,
 Thursday progressive 12km, Sunday long run
 starting at 20km and adding 2km per week."

"What's my training load for the last 30 days? Am I overtraining?"

"Delete all workouts from the old plan and re-upload the new ones."
```

---

## Authentication

The server uses `garminconnect`, which authenticates with email/password and internally manages OAuth tokens via [garth](https://github.com/matin/garth) (long-lived tokens, ~1 year). **No password is stored permanently** — only session tokens are persisted by garth in `~/.garth/`.

If your account has MFA enabled, run the interactive login first:

```bash
python -c "from garminconnect import Garmin; g = Garmin('email', 'pass'); g.login()"
```

---

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Garmin Ltd. It uses `garminconnect`, which relies on reverse-engineered endpoints. Use at your own risk, for personal use only. Garmin may change their API at any time, which could break this server.

## License

MIT
