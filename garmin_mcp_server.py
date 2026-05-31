#!/usr/bin/env python3
"""
Garmin MCP Server
=================
MCP Server for Garmin Connect — read activities, health data, and push
structured training plans from any AI assistant that supports MCP.

Uses the garminconnect Python library (tested and validated with real Garmin data).

Transport modes:
  - stdio:            Claude Desktop, Claude Code, VS Code Copilot
  - streamable-http:  Remote clients (claude.ai, web apps), Docker

Usage:
  # stdio (Claude Desktop)
  python garmin_mcp_server.py

  # HTTP (remote / Docker)
  python garmin_mcp_server.py --transport http --port 8000

  # Claude Code
  claude mcp add garmin -- python /path/to/garmin_mcp_server.py

Requires: pip install mcp garminconnect pydantic
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP
from garminconnect import Garmin
from garminconnect.workout import (
    RunningWorkout,
    WorkoutSegment,
    ExecutableStep,
    create_repeat_group,
    TargetType,
    ConditionType,
    StepType,
)

# ============================================================
# Configuration
# ============================================================

GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL", "")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD", "")
GARTH_TOKEN_DIR = os.environ.get("GARTH_TOKEN_DIR", "~/.garth")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("garmin-mcp")

# ============================================================
# Garmin client singleton (lazy init with token persistence)
# ============================================================

_garmin_client: Optional[Garmin] = None


def get_token_dir() -> str:
    """Get the resolved garth token directory path."""
    return str(Path(GARTH_TOKEN_DIR).expanduser())


def has_saved_tokens() -> bool:
    """Check if garth tokens exist on disk."""
    token_dir = get_token_dir()
    return (
        Path(token_dir).exists()
        and any(Path(token_dir).iterdir())
    )


def get_garmin() -> Garmin:
    """
    Get authenticated Garmin client.

    Auth strategy:
      1. Try to resume session from saved garth tokens (no credentials needed)
      2. If no tokens, login with email/password and save tokens for next time
    """
    global _garmin_client
    if _garmin_client is not None:
        return _garmin_client

    token_dir = get_token_dir()

    # Strategy 1: resume from saved tokens
    if has_saved_tokens():
        try:
            client = Garmin()
            client.login(token_dir)
            _garmin_client = client
            logger.info("Garmin Connect: resumed session from saved tokens (%s)", token_dir)
            return client
        except Exception as e:
            logger.warning("Saved tokens expired or invalid: %s — trying credentials...", e)

    # Strategy 2: fresh login with credentials
    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        raise RuntimeError(
            "No saved Garmin session and no credentials provided.\n"
            "Set GARMIN_EMAIL and GARMIN_PASSWORD environment variables for first login.\n"
            "After the first successful login, tokens are saved and credentials are no longer needed."
        )

    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    client.login()

    # Save tokens for future sessions
    try:
        Path(token_dir).mkdir(parents=True, exist_ok=True)
        client.garth.dump(token_dir)
        logger.info("Garmin Connect: logged in as %s — tokens saved to %s", GARMIN_EMAIL, token_dir)
    except Exception as e:
        logger.warning("Login OK but could not save tokens: %s", e)

    _garmin_client = client
    return client


# ============================================================
# Helpers — from our tested upload_workouts_venezia_v3.py
# ============================================================


def pace_to_ms(pace: str) -> float:
    """Convert 'min:sec' per km to meters/second."""
    m, s = pace.split(":")
    return 1000.0 / (int(m) * 60 + int(s))


def format_pace(seconds_per_km: float) -> str:
    """Format seconds/km to 'min:sec/km'."""
    m = int(seconds_per_km // 60)
    s = int(seconds_per_km % 60)
    return f"{m}:{s:02d}/km"


def format_duration(seconds: float) -> str:
    """Format seconds to 'Xh Ym' or 'Xm'."""
    if seconds >= 3600:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"
    return f"{int(seconds // 60)}m"


# --- Workout step builders (from tested v3 script) ---

def speed_target(low_pace: str, high_pace: str) -> dict:
    """Create speed target. low_pace = slower, high_pace = faster."""
    return {
        "workoutTargetTypeId": TargetType.SPEED,
        "workoutTargetTypeKey": "speed.zone",
        "displayOrder": 1,
        "targetValueOne": pace_to_ms(low_pace),
        "targetValueTwo": pace_to_ms(high_pace),
    }


def hr_target(low_bpm: int, high_bpm: int) -> dict:
    """Create heart rate target."""
    return {
        "workoutTargetTypeId": TargetType.HEART_RATE,
        "workoutTargetTypeKey": "heart.rate.zone",
        "displayOrder": 1,
        "targetValueOne": low_bpm,
        "targetValueTwo": high_bpm,
    }


def no_target() -> dict:
    """No target (open/feel-based)."""
    return {
        "workoutTargetTypeId": TargetType.NO_TARGET,
        "workoutTargetTypeKey": "no.target",
        "displayOrder": 1,
    }


def time_condition(seconds: int) -> dict:
    """Duration condition in seconds."""
    return {
        "conditionTypeId": ConditionType.TIME,
        "conditionTypeKey": "time",
        "displayOrder": 1,
        "displayable": True,
    }, seconds * 1000  # Garmin uses milliseconds


def distance_condition(meters: int) -> dict:
    """Distance condition in meters."""
    return {
        "conditionTypeId": ConditionType.DISTANCE,
        "conditionTypeKey": "distance",
        "displayOrder": 1,
        "displayable": True,
    }, meters * 100  # Garmin uses centimeters


def lap_button_condition() -> dict:
    """Open/lap button condition."""
    return {
        "conditionTypeId": ConditionType.LAP_BUTTON,
        "conditionTypeKey": "lap.button",
        "displayOrder": 1,
        "displayable": True,
    }, None


def step_with_dual_target(
    order: int,
    step_type: int,
    step_key: str,
    step_type_id: int,
    end_condition: dict,
    primary_target: dict,
    secondary_target: dict = None,
) -> ExecutableStep:
    """
    Build a workout step with targetValues HOISTED to root level.
    This is the fix from v3 that makes dual targets actually work on the watch.
    """
    cond, cond_value = end_condition

    step_data = {
        "stepOrder": order,
        "stepType": {
            "stepTypeId": step_type,
            "stepTypeKey": step_key,
            "displayOrder": step_type_id,
        },
        "endCondition": cond,
        "targetType": {
            "workoutTargetTypeId": primary_target["workoutTargetTypeId"],
            "workoutTargetTypeKey": primary_target["workoutTargetTypeKey"],
            "displayOrder": primary_target.get("displayOrder", 1),
        },
        # HOISTED values — this is the critical fix
        "targetValueOne": primary_target.get("targetValueOne"),
        "targetValueTwo": primary_target.get("targetValueTwo"),
    }

    if cond_value is not None:
        step_data["endConditionValue"] = cond_value

    if secondary_target and secondary_target["workoutTargetTypeId"] != TargetType.NO_TARGET:
        step_data["secondaryTargetType"] = {
            "workoutTargetTypeId": secondary_target["workoutTargetTypeId"],
            "workoutTargetTypeKey": secondary_target["workoutTargetTypeKey"],
            "displayOrder": secondary_target.get("displayOrder", 1),
        }
        step_data["secondaryTargetValueOne"] = secondary_target.get("targetValueOne")
        step_data["secondaryTargetValueTwo"] = secondary_target.get("targetValueTwo")

    return ExecutableStep(**step_data)


def make_running_workout(name: str, duration_secs: int, steps: list) -> RunningWorkout:
    """Create a RunningWorkout with correct structure."""
    return RunningWorkout(
        workoutName=name,
        estimatedDurationInSecs=duration_secs,
        workoutSegments=[
            WorkoutSegment(
                segmentOrder=1,
                sportType={"sportTypeId": 1, "sportTypeKey": "running"},
                workoutSteps=steps,
            )
        ],
    )


# ============================================================
# MCP Server
# ============================================================

mcp = FastMCP(
    "Garmin Connect",
    instructions=(
        "MCP server for Garmin Connect. Provides tools to read activities, "
        "health data, training status, and push structured workouts/training plans "
        "to a Garmin device. On first use, requires GARMIN_EMAIL and GARMIN_PASSWORD. "
        "After the first login, tokens are saved and credentials are no longer needed."
    ),
)


# -------------------- READ TOOLS -------------------- #


@mcp.tool()
def get_activities(
    limit: int = 20,
    start: int = 0,
    activity_type: str = "",
) -> str:
    """
    Get recent activities from Garmin Connect.

    Returns activity summaries including distance, duration, pace, heart rate,
    and calories. Use this to check what workouts the user has completed.

    Args:
        limit: Number of activities to retrieve (1-100, default 20)
        start: Pagination offset
        activity_type: Filter by type: running, cycling, swimming, walking, hiking, strength
    """
    client = get_garmin()
    activities = client.get_activities(start, limit)

    if activity_type:
        activities = [
            a for a in activities
            if activity_type.lower() in (a.get("activityType", {}).get("typeKey", "") or "").lower()
        ]

    if not activities:
        return "No activities found."

    lines = [f"Found {len(activities)} activities:\n"]
    for a in activities:
        aid = a.get("activityId", "?")
        atype = a.get("activityType", {}).get("typeKey", "unknown")
        dt = (a.get("startTimeLocal") or "")[:10]
        dist = a.get("distance", 0) or 0
        dur = a.get("duration", 0) or 0
        hr = a.get("averageHR")
        cal = a.get("calories")

        dist_km = dist / 1000
        dur_min = dur / 60
        pace = format_pace(dur / (dist / 1000)) if dist > 0 else "N/A"
        hr_str = f"{hr} bpm" if hr else "N/A"
        cal_str = f"{cal} kcal" if cal else "?"

        lines.append(
            f"• [{aid}] {dt} — {atype} | {dist_km:.1f} km | "
            f"{dur_min:.0f} min | {pace} | HR: {hr_str} | {cal_str}"
        )

    return "\n".join(lines)


@mcp.tool()
def get_activity_details(activity_id: str) -> str:
    """
    Get detailed data for a specific Garmin activity.

    Returns splits, laps, HR zones, running dynamics (cadence, stride length,
    ground contact time), and elevation data.

    Args:
        activity_id: The Garmin activity ID (from get_activities)
    """
    client = get_garmin()
    details = client.get_activity(activity_id)
    return json.dumps(details, indent=2, default=str)


@mcp.tool()
def get_health_summary(date_str: str) -> str:
    """
    Get daily health metrics from Garmin.

    Returns steps, resting heart rate, HRV, stress, sleep data, body battery,
    SpO2, and training readiness. Useful to assess recovery and readiness.

    Args:
        date_str: Date in YYYY-MM-DD format
    """
    client = get_garmin()
    d = date_str

    lines = [f"Health summary for {d}:\n"]

    try:
        steps = client.get_daily_steps(d)
        total = sum(s.get("totalSteps", 0) for s in steps) if isinstance(steps, list) else 0
        lines.append(f"• Steps:              {total:,}")
    except Exception:
        pass

    try:
        hr = client.get_heart_rates(d)
        rhr = hr.get("restingHeartRate") if isinstance(hr, dict) else None
        if rhr:
            lines.append(f"• Resting HR:         {rhr} bpm")
    except Exception:
        pass

    try:
        hrv = client.get_hrv_data(d)
        if isinstance(hrv, dict):
            summary = hrv.get("hrvSummary", {})
            score = summary.get("weeklyAvg") or summary.get("lastNightAvg")
            if score:
                lines.append(f"• HRV:                {score}")
    except Exception:
        pass

    try:
        stress = client.get_stress_data(d)
        if isinstance(stress, dict):
            avg = stress.get("overallStressLevel")
            if avg:
                lines.append(f"• Stress (avg):       {avg}/100")
    except Exception:
        pass

    try:
        sleep = client.get_sleep_data(d)
        if isinstance(sleep, dict):
            dur = sleep.get("dailySleepDTO", {}).get("sleepTimeSeconds")
            score = sleep.get("dailySleepDTO", {}).get("sleepScores", {}).get("overall", {}).get("value")
            if dur:
                lines.append(f"• Sleep:              {dur/3600:.1f}h" + (f" (score: {score})" if score else ""))
    except Exception:
        pass

    try:
        bb = client.get_body_battery(d)
        if isinstance(bb, list) and bb:
            vals = [b.get("charged", 0) for b in bb if b.get("charged")]
            if vals:
                lines.append(f"• Body Battery:       {min(vals)}–{max(vals)}")
    except Exception:
        pass

    try:
        spo2 = client.get_spo2_data(d)
        if isinstance(spo2, dict):
            avg = spo2.get("averageSpO2")
            if avg:
                lines.append(f"• SpO2 (avg):         {avg}%")
    except Exception:
        pass

    try:
        tr = client.get_training_readiness(d)
        if isinstance(tr, dict):
            score = tr.get("score")
            if score:
                lines.append(f"• Training readiness: {score}")
    except Exception:
        pass

    if len(lines) == 1:
        lines.append("  No health data available for this date.")

    return "\n".join(lines)


@mcp.tool()
def get_training_status(days: int = 7) -> str:
    """
    Get training load summary for recent days.

    Analyzes recent activities to show total distance, duration, run count,
    and average pace. Useful for evaluating weekly volume and deciding
    whether to increase or decrease training load.

    Args:
        days: Number of days to analyze (1-90, default 7)
    """
    client = get_garmin()
    end = date.today()
    start = end - timedelta(days=days)

    activities = client.get_activities_by_date(
        start.isoformat(), end.isoformat()
    )

    runs = [
        a for a in activities
        if "running" in (a.get("activityType", {}).get("typeKey", "") or "").lower()
    ]

    total_dist = sum(a.get("distance", 0) or 0 for a in runs)
    total_dur = sum(a.get("duration", 0) or 0 for a in runs)
    avg_pace = format_pace(total_dur / (total_dist / 1000)) if total_dist > 0 else "N/A"

    lines = [
        f"Training status — last {days} days:\n",
        f"• Total activities:   {len(activities)}",
        f"• Running sessions:   {len(runs)}",
        f"• Total distance:     {total_dist/1000:.1f} km",
        f"• Total duration:     {format_duration(total_dur)}",
        f"• Avg pace:           {avg_pace}",
        "",
        "Recent runs:",
    ]

    for a in runs[:10]:
        dt = (a.get("startTimeLocal") or "")[:10]
        dist = (a.get("distance", 0) or 0) / 1000
        dur = (a.get("duration", 0) or 0) / 60
        hr = a.get("averageHR")
        lines.append(
            f"  {dt} | {dist:.1f} km | {dur:.0f} min"
            + (f" | HR: {hr} bpm" if hr else "")
        )

    return "\n".join(lines)


@mcp.tool()
def get_workouts(limit: int = 20) -> str:
    """
    List workouts saved on Garmin Connect.

    Shows existing workout templates and scheduled workouts.

    Args:
        limit: Number of workouts to retrieve (default 20)
    """
    client = get_garmin()
    workouts = client.get_workouts(0, limit)

    if not workouts:
        return "No workouts found on Garmin Connect."

    lines = [f"Found {len(workouts)} workouts:\n"]
    for w in workouts:
        wid = w.get("workoutId", "?")
        name = w.get("workoutName", "Unnamed")
        sport = w.get("sportType", {}).get("sportTypeKey", "?")
        lines.append(f"• [{wid}] {name} ({sport})")

    return "\n".join(lines)


# -------------------- WRITE TOOLS -------------------- #


@mcp.tool()
def push_workout(
    name: str,
    steps_json: str,
    estimated_duration_minutes: int = 60,
    schedule_date: str = "",
) -> str:
    """
    Create a structured running workout on Garmin Connect.

    The workout syncs to the user's Garmin device. Supports warmup, intervals,
    recovery, and cooldown steps with pace and/or heart rate targets.

    Args:
        name: Workout name (e.g., "Mar - 10km Facili + Allunghi")
        steps_json: JSON array of workout steps. Each step has:
            - type: "warmup" | "run" | "recover" | "cooldown" | "rest"
            - duration_type: "time" | "distance" | "open"
            - duration_value: seconds (for time) or meters (for distance)
            - pace_low: slower pace target "min:sec" (optional)
            - pace_high: faster pace target "min:sec" (optional)
            - hr_low: lower HR target in bpm (optional)
            - hr_high: upper HR target in bpm (optional)
            - primary: "pace" | "hr" | "none" (which target is primary, default: "hr")
            For repeats, use:
            - type: "repeat"
            - repeat_count: number of repetitions
            - steps: nested array of steps to repeat
        estimated_duration_minutes: Total estimated duration in minutes
        schedule_date: Optional YYYY-MM-DD to schedule the workout
    """
    client = get_garmin()

    try:
        steps_data = json.loads(steps_json)
    except json.JSONDecodeError as e:
        return f"Invalid steps JSON: {e}"

    order_counter = [0]

    def next_order():
        order_counter[0] += 1
        return order_counter[0]

    def build_step(s: dict) -> ExecutableStep | list:
        stype = s.get("type", "run")
        dur_type = s.get("duration_type", "time")
        dur_val = s.get("duration_value", 600)
        primary = s.get("primary", "hr")

        if stype == "repeat":
            inner = [build_step(sub) for sub in s.get("steps", [])]
            flat = []
            for item in inner:
                if isinstance(item, list):
                    flat.extend(item)
                else:
                    flat.append(item)
            return create_repeat_group(s.get("repeat_count", 1), flat, next_order())

        step_map = {
            "warmup": (StepType.WARMUP, "warmup", 1),
            "run": (StepType.INTERVAL, "interval", 3),
            "recover": (StepType.RECOVERY, "recovery", 4),
            "cooldown": (StepType.COOLDOWN, "cooldown", 2),
            "rest": (StepType.REST, "rest", 5),
        }
        st, sk, sid = step_map.get(stype, step_map["run"])

        if dur_type == "distance":
            cond = distance_condition(dur_val)
        elif dur_type == "open":
            cond = lap_button_condition()
        else:
            cond = time_condition(dur_val)

        pace_low = s.get("pace_low")
        pace_high = s.get("pace_high")
        hr_low = s.get("hr_low")
        hr_high = s.get("hr_high")

        p_target = speed_target(pace_low, pace_high) if pace_low and pace_high else None
        h_target = hr_target(hr_low, hr_high) if hr_low and hr_high else None

        if primary == "hr" and h_target:
            pri, sec = h_target, p_target
        elif primary == "pace" and p_target:
            pri, sec = p_target, h_target
        elif p_target:
            pri, sec = p_target, h_target
        elif h_target:
            pri, sec = h_target, None
        else:
            pri, sec = no_target(), None

        return step_with_dual_target(next_order(), st, sk, sid, cond, pri, sec)

    workout_steps = []
    for s in steps_data:
        result = build_step(s)
        if isinstance(result, list):
            workout_steps.extend(result)
        else:
            workout_steps.append(result)

    workout = make_running_workout(
        name, estimated_duration_minutes * 60, workout_steps
    )

    result = client.upload_running_workout(workout)
    workout_id = result.get("workoutId")

    msg = f"Workout '{name}' created (ID: {workout_id})"

    if schedule_date and workout_id:
        try:
            client.schedule_workout(workout_id, schedule_date)
            msg += f"\nScheduled for {schedule_date}"
        except Exception as e:
            msg += f"\nCreated but scheduling failed: {e}"

    msg += "\nSync your Garmin device to get the workout."
    return msg


@mcp.tool()
def push_training_plan(
    name: str,
    start_date: str,
    workouts_json: str,
) -> str:
    """
    Push a multi-day training plan to Garmin Connect.

    Each workout is scheduled on the Garmin calendar. The workouts sync to
    the device and appear on the training calendar.

    Args:
        name: Plan name (e.g., "Preparazione Venezia - Giugno")
        start_date: Start date YYYY-MM-DD
        workouts_json: JSON array of workout entries, each with:
            - day_offset: days from start_date (0 = start_date itself)
            - name: workout name
            - estimated_duration_minutes: total duration
            - steps: array of steps (same format as push_workout)
    """
    client = get_garmin()

    try:
        plan = json.loads(workouts_json)
    except json.JSONDecodeError as e:
        return f"Invalid plan JSON: {e}"

    import time as _time

    base = date.fromisoformat(start_date)
    success = 0
    errors = []

    for entry in plan:
        offset = entry.get("day_offset", 0)
        w_date = base + timedelta(days=offset)
        w_name = entry.get("name", f"Workout day {offset}")
        w_dur = entry.get("estimated_duration_minutes", 60)
        w_steps_json = json.dumps(entry.get("steps", []))

        try:
            result = push_workout(
                name=w_name,
                steps_json=w_steps_json,
                estimated_duration_minutes=w_dur,
                schedule_date=w_date.isoformat(),
            )
            if "created" in result.lower():
                success += 1
            else:
                errors.append(f"Day +{offset}: {result}")
        except Exception as e:
            errors.append(f"Day +{offset} ({w_name}): {e}")

        _time.sleep(0.5)

    lines = [
        f"Training plan '{name}' push complete:",
        f"  Success: {success}/{len(plan)}",
    ]
    if errors:
        lines.append(f"  Errors:  {len(errors)}/{len(plan)}")
        for e in errors:
            lines.append(f"    {e}")

    lines.append("\nSync your Garmin device to download the workouts.")
    return "\n".join(lines)


@mcp.tool()
def delete_workout(workout_id: str) -> str:
    """
    Delete a workout from Garmin Connect.

    Args:
        workout_id: The Garmin workout ID (from get_workouts)
    """
    client = get_garmin()
    try:
        client.delete_workout(workout_id)
        return f"Workout {workout_id} deleted."
    except Exception as e:
        return f"Failed to delete workout {workout_id}: {e}"


@mcp.tool()
def delete_plan_workouts(name_contains: str = "") -> str:
    """
    Delete all workouts whose name contains the given string.
    Useful to clear a training plan and re-upload it.

    Args:
        name_contains: String to match in workout names (e.g., "S1", "Venezia")
    """
    import time as _time

    client = get_garmin()
    workouts = client.get_workouts(0, 200)

    if name_contains:
        to_delete = [w for w in workouts if name_contains.lower() in w.get("workoutName", "").lower()]
    else:
        to_delete = workouts

    if not to_delete:
        return f"No workouts found matching '{name_contains}'."

    deleted = 0
    errors = 0
    for w in to_delete:
        try:
            client.delete_workout(w["workoutId"])
            deleted += 1
            _time.sleep(0.3)
        except Exception:
            errors += 1

    return f"Deleted {deleted} workouts" + (f" ({errors} errors)" if errors else "") + "."


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Garmin MCP Server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "http", "streamable-http"])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
