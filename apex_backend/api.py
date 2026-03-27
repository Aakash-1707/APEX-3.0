"""
APEX Backend API — OpenF1 + FastF1
==================================
FastAPI server that prefers OpenF1 REST API and falls back to FastF1 (local Ergast/F1
data) when OpenF1 returns no data for sessions, drivers, laps, stints, results, or
telemetry. Install FastF1: pip install fastf1

Run:
    pip install fastapi uvicorn httpx numpy
    uvicorn api:app --reload --port 8000

Endpoints:
    GET  /api/health                                    → server status
    GET  /api/calendar                                  → 2026 race calendar (from OpenF1)
    GET  /api/sessions/{meeting_key}                    → sessions for a meeting
    GET  /api/drivers/{session_key}                     → driver list
    GET  /api/telemetry/{session_key}/{driver_number}   → car telemetry + location
    GET  /api/laps/{session_key}/{driver_number}        → lap times + sectors
    GET  /api/stints/{session_key}                      → tyre stint data
    GET  /api/result/{session_key}                      → session result
    GET  /api/weather/{session_key}                     → weather data
    GET  /api/starting_grid/{session_key}               → starting grid
    POST /api/predict                                   → run Monte Carlo prediction
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import json
import os
import hashlib
import httpx
import time as _time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import model_core as mc
import strategy_engine as se
import ff_bridge as fb
from rag_service import get_rag
from llm_service import get_llm

OPENF1_BASE = "https://api.openf1.org/v1"
OPENF1_API_KEY = os.environ.get("OPENF1_API_KEY", "").strip()
OPENF1_USERNAME = os.environ.get("OPENF1_USERNAME", "").strip()
OPENF1_PASSWORD = os.environ.get("OPENF1_PASSWORD", "").strip()

_OPENF1_ACCESS_TOKEN: Optional[str] = None
_OPENF1_TOKEN_EXPIRY_TS: float = 0.0
_OPENF1_AUTH_WARNED: bool = False

app = FastAPI(title="APEX F1 API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://apex-phi-coru.vercel.app",
        "*",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── IN-MEMORY CACHE ─────────────────────────────────────────────────────────
# Caches OpenF1 responses to avoid 429 rate limit errors.
# TTL: 300s (5 min) for most data, 3600s (1 hour) for calendar/meetings.

_MEM_CACHE: dict[str, tuple[float, any]] = {}
_DEFAULT_TTL = 300  # 5 minutes
_LONG_TTL = 3600    # 1 hour (for calendar, sessions)


def _cache_get(key: str) -> Optional[any]:
    if key in _MEM_CACHE:
        ts, data = _MEM_CACHE[key]
        if _time.time() - ts < _DEFAULT_TTL:
            return data
        del _MEM_CACHE[key]
    return None


def _cache_set(key: str, data: any, ttl: int = _DEFAULT_TTL):
    _MEM_CACHE[key] = (_time.time(), data)


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _openf1(endpoint: str, params: dict = None, ttl: int = _DEFAULT_TTL) -> list | dict:
    """Fetch data from OpenF1 API with caching and retry."""
    # Build cache key
    cache_key = f"{endpoint}|{json.dumps(params or {}, sort_keys=True)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = f"{OPENF1_BASE}/{endpoint}"
    max_retries = 3
    headers = {"accept": "application/json"}
    token = _get_openf1_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.get(url, params=params, headers=headers)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    _time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                
                # Handle dictionary responses (usually error details)
                if isinstance(data, dict) and "detail" in data:
                    print(f"OpenF1 API Notice: {data['detail']}")
                    return []
                
                _cache_set(cache_key, data, ttl)
                return data
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            if status_code in [401, 403, 404]:
                print(f"OpenF1 API Notice ({status_code}): {e.response.text}")
                return []
            if attempt < max_retries - 1:
                _time.sleep(1)
                continue
            raise
    return []


def _looks_like_jwt(token: str) -> bool:
    # JWTs generally contain 3 segments separated by dots.
    return token.count(".") == 2 and len(token) > 30


def _fetch_openf1_access_token() -> Optional[str]:
    global _OPENF1_ACCESS_TOKEN, _OPENF1_TOKEN_EXPIRY_TS
    if not (OPENF1_USERNAME and OPENF1_PASSWORD):
        return None
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                "https://api.openf1.org/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={"username": OPENF1_USERNAME, "password": OPENF1_PASSWORD},
            )
            resp.raise_for_status()
            data = resp.json() if resp.text else {}
            token = data.get("access_token")
            if isinstance(token, str) and token:
                expires_in = data.get("expires_in")
                try:
                    ttl_s = max(60, int(expires_in) - 60) if expires_in is not None else 3000
                except Exception:
                    ttl_s = 3000
                _OPENF1_ACCESS_TOKEN = token
                _OPENF1_TOKEN_EXPIRY_TS = _time.time() + ttl_s
                return token
    except Exception as e:
        print(f"OpenF1 auth token fetch failed: {e}")
    return None


def _get_openf1_token() -> Optional[str]:
    global _OPENF1_AUTH_WARNED
    # If user set a JWT token directly, use it.
    if OPENF1_API_KEY and _looks_like_jwt(OPENF1_API_KEY):
        return OPENF1_API_KEY

    # If OPENF1_API_KEY is set but not a JWT, warn once.
    if OPENF1_API_KEY and not _OPENF1_AUTH_WARNED:
        print("OpenF1 auth: OPENF1_API_KEY is not a valid JWT access token. "
              "Use OPENF1_USERNAME/OPENF1_PASSWORD or a real access token.")
        _OPENF1_AUTH_WARNED = True

    # Use cached OAuth token if still valid.
    if _OPENF1_ACCESS_TOKEN and _time.time() < _OPENF1_TOKEN_EXPIRY_TS:
        return _OPENF1_ACCESS_TOKEN

    # Try to fetch a new OAuth token using username/password.
    return _fetch_openf1_access_token()


# ─── PREDICTION + CIRCUIT STATS CACHE ─────────────────────────────────────────

CACHE_DIR = os.path.join(os.path.dirname(__file__), "prediction_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_CACHE_TABLE = os.environ.get("SUPABASE_CACHE_TABLE", "prediction_cache")


def _prediction_request_key(meeting_key: int, session_key: Optional[int], race_session_key: Optional[int], n_sims: int, source_mode: str) -> str:
    """Include quali + race session + source mode so different inputs get separate caches."""
    raw = f"openf1_{meeting_key}_{session_key or 0}_{race_session_key or 0}_{n_sims}_{source_mode}"
    return hashlib.md5(raw.encode()).hexdigest()


def _local_cache_key(request_key: str, data_version: str) -> str:
    return f"{request_key}_{data_version}"


def _load_cache(key: str) -> Optional[dict]:
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def _save_cache(key: str, data: dict):
    path = os.path.join(CACHE_DIR, f"{key}.json")
    with open(path, "w") as f:
        json.dump(data, f)


def _supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _supabase_headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def _load_supabase_cache(request_key: str, data_version: str) -> Optional[dict]:
    if not _supabase_enabled():
        return None
    try:
        req_q = quote_plus(request_key)
        ver_q = quote_plus(data_version)
        table_q = quote_plus(SUPABASE_CACHE_TABLE)
        url = (
            f"{SUPABASE_URL}/rest/v1/{table_q}"
            f"?select=result_json&request_key=eq.{req_q}&data_version=eq.{ver_q}"
            f"&order=created_at.desc&limit=1"
        )
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=_supabase_headers())
            resp.raise_for_status()
            rows = resp.json()
            if rows and isinstance(rows, list):
                payload = rows[0].get("result_json")
                if isinstance(payload, dict):
                    return payload
    except Exception as e:
        print(f"Supabase cache read failed: {e}")
    return None


def _save_supabase_cache(request_key: str, data_version: str, data: dict):
    if not _supabase_enabled():
        return
    try:
        table_q = quote_plus(SUPABASE_CACHE_TABLE)
        url = f"{SUPABASE_URL}/rest/v1/{table_q}"
        row = {
            "request_key": request_key,
            "data_version": data_version,
            "result_json": data,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        headers = _supabase_headers()
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=headers, json=[row])
            resp.raise_for_status()
    except Exception as e:
        print(f"Supabase cache write failed: {e}")


def _build_prediction_data_version(
    meeting_key: int,
    sessions: list,
    session_key: Optional[int],
    race_session_key: Optional[int],
    source_mode: str,
) -> str:
    """
    Build a stable fingerprint of upstream OpenF1 state relevant to predictions.
    Any change in session/result snapshots creates a new cache version.
    """
    session_snapshots = []
    for s in sessions:
        session_snapshots.append({
            "session_key": s.get("session_key"),
            "session_name": s.get("session_name"),
            "session_type": s.get("session_type"),
            "status": s.get("status"),
            "date_start": s.get("date_start"),
            "date_end": s.get("date_end"),
        })
    session_snapshots.sort(key=lambda x: (x.get("session_key") or 0))

    tracked_keys = set()
    if session_key:
        tracked_keys.add(session_key)
    if race_session_key:
        tracked_keys.add(race_session_key)
    for s in sessions:
        name = s.get("session_name")
        if name in {
            "Qualifying", "Sprint Qualifying", "Sprint Shootout",
            "Sprint", "Race", "Practice 1", "Practice 2", "Practice 3",
        }:
            sk = s.get("session_key")
            if sk:
                tracked_keys.add(sk)

    result_snapshots = []
    for sk in sorted(tracked_keys):
        try:
            rows = _openf1("session_result", {"session_key": sk}, ttl=60)
        except Exception:
            rows = []
        if not isinstance(rows, list):
            rows = []
        positions = [r.get("position") for r in rows if r.get("position") is not None]
        durations = []
        for r in rows:
            d = r.get("duration")
            if isinstance(d, (int, float)):
                durations.append(float(d))
            elif isinstance(d, list):
                durations.extend([float(x) for x in d if isinstance(x, (int, float))])
        result_snapshots.append({
            "session_key": sk,
            "n_rows": len(rows),
            "max_position": max(positions) if positions else None,
            "duration_checksum": round(sum(durations), 3) if durations else None,
        })

    version_payload = {
        "meeting_key": meeting_key,
        "source_mode": source_mode,
        "sessions": session_snapshots,
        "results": result_snapshots,
    }
    raw = json.dumps(version_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(raw.encode()).hexdigest()


def _get_circuit_stats_from_openf1(circuit_key: int) -> Optional[dict]:
    """
    Estimate SC / VSC / rain probabilities for a circuit from recent race history.
    Uses OpenF1 'sessions', 'race_control' and 'weather' endpoints across 2023–2025.
    """
    years = [2023, 2024, 2025]
    race_sessions = []
    for year in years:
        try:
            sess = _openf1("sessions", {
                "year": year,
                "circuit_key": circuit_key,
                "session_type": "Race",
            })
            if isinstance(sess, list):
                race_sessions.extend(sess)
        except Exception:
            continue

    if not race_sessions:
        return None

    total_races = 0
    sc_races = 0
    vsc_races = 0
    rain_races = 0

    for s in race_sessions:
        skey = s.get("session_key")
        if not skey:
            continue
        total_races += 1

        # Race control flags
        try:
            rc = _openf1("race_control", {"session_key": skey})
        except Exception:
            rc = []
        if isinstance(rc, list):
            flags = [str(e.get("flag", "")).upper() for e in rc]
            has_sc = any("SAFETY CAR" in f and "VIRTUAL" not in f for f in flags)
            has_vsc = any("VIRTUAL SAFETY CAR" in f for f in flags)
            if has_sc:
                sc_races += 1
            if has_vsc:
                vsc_races += 1

        # Weather (rainfall flag)
        try:
            weather = _openf1("weather", {"session_key": skey})
        except Exception:
            weather = []
        if isinstance(weather, list):
            if any(w.get("rainfall") for w in weather):
                rain_races += 1

    if total_races == 0:
        return None

    stats = {
        "sc_prob": sc_races / total_races,
        "vsc_prob": vsc_races / total_races,
        "rain_prob": rain_races / total_races,
        "n_races": total_races,
    }
    return stats


# ─── HEALTH ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "data_source": "openf1"}


# ─── CALENDAR ─────────────────────────────────────────────────────────────────

def _mark_cancelled_races_after_japan(events: list) -> None:
    """
    Mark Bahrain and Saudi Arabian GPs as cancelled when they fall after the Japanese GP
    on the calendar (by date order). Matches by event / circuit name so a different race
    between Japan and those rounds is not marked by mistake.
    """
    jp_i = None
    for i, e in enumerate(events):
        n = (e.get("name") or "").lower()
        c = (e.get("circuit_short_name") or "").lower()
        if "japanese" in n or ("japan" in n and "grand" in n) or "suzuka" in c:
            jp_i = i
            break
    if jp_i is None:
        return
    marked = 0
    for e in events[jp_i + 1 :]:
        if marked >= 2:
            break
        n = (e.get("name") or "").lower()
        c = (e.get("circuit_short_name") or "").lower()
        if "bahrain" in n or "saudi" in n or "jeddah" in c:
            e["cancelled"] = True
            marked += 1


@app.get("/api/calendar")
def get_calendar(year: int = Query(2026)):
    """Fetch race calendar from OpenF1, excluding testing events."""
    def _compute_fallback_from_fastf1():
        """Build calendar from FastF1 schedule when OpenF1 meetings are unavailable."""
        if not getattr(fb, "FASTF1_AVAILABLE", False):
            return []
        try:
            schedule = fb.fastf1.get_event_schedule(year)
        except Exception:
            return []
        if schedule is None or schedule.empty:
            return []

        now_utc = datetime.now(timezone.utc)
        out = []
        for _, row in schedule.iterrows():
            name = str(row.get("EventName", "") or "")
            if "testing" in name.lower() or "test" in name.lower():
                continue

            # Use FastF1 round number to build a stable synthetic meeting key.
            try:
                rnd = int(row.get("RoundNumber"))
            except Exception:
                rnd = 0
            meeting_key = int(year) * 100 + max(rnd, 0)

            start_raw = row.get("Session1DateUtc") or row.get("Session1Date") or row.get("EventDate")
            end_raw = row.get("Session5DateUtc") or row.get("Session5Date") or row.get("EventDate")
            if start_raw is None or end_raw is None:
                continue

            ds = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
            de = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
            if ds.tzinfo is None:
                ds = ds.replace(tzinfo=timezone.utc)
            if de.tzinfo is None:
                de = de.replace(tzinfo=timezone.utc)

            if de < now_utc:
                mode = "past"
            elif ds <= now_utc <= de:
                mode = "live"
            else:
                mode = "upcoming"

            out.append({
                "meeting_key": meeting_key,
                "name": name,
                "official_name": name,
                "location": str(row.get("Location", "") or ""),
                "country_code": "",
                "country_name": str(row.get("Country", "") or ""),
                "country_flag": "",
                "circuit_key": None,
                "circuit_short_name": str(row.get("Location", "") or name),
                "circuit_type": "",
                "circuit_image": "",
                "date_start": ds.isoformat(),
                "date_end": de.isoformat(),
                "gmt_offset": "",
                "year": year,
                "mode": mode,
                "cancelled": False,
                "data_source": "fastf1",
            })
        out.sort(key=lambda x: x.get("date_start") or "")
        return out

    def _compute_fallback_2026():
        """Return hardcoded 2026 calendar with dynamically computed modes."""
        now_utc = datetime.now(timezone.utc)
        races = [
            {"meeting_key": 1280, "name": "Chinese Grand Prix", "circuit_short_name": "Shanghai",
             "location": "Shanghai", "date_start": "2026-03-13T00:00:00+00:00", "date_end": "2026-03-16T00:00:00+00:00"},
            {"meeting_key": 1281, "name": "Australian Grand Prix", "circuit_short_name": "Melbourne",
             "location": "Melbourne", "date_start": "2026-03-27T00:00:00+00:00", "date_end": "2026-03-30T00:00:00+00:00"},
        ]
        result = []
        for r in races:
            ds = datetime.fromisoformat(r["date_start"])
            de = datetime.fromisoformat(r["date_end"])
            if de < now_utc:
                m = "past"
            elif ds <= now_utc <= de:
                m = "live"
            else:
                m = "upcoming"
            result.append({**r, "mode": m})
        return result

    meetings = []
    try:
        meetings = _openf1("meetings", {"year": year})
    except httpx.HTTPStatusError as e:
        print(f"OpenF1 calendar error for year={year}: {e.response.status_code} - {e.response.text[:200]}")
        if year == 2026:
            return _compute_fallback_2026()
        meetings = []
    except Exception as e:
        print(f"OpenF1 calendar error: {e}")
        if year == 2026:
            return _compute_fallback_2026()
        meetings = []

    if not isinstance(meetings, list):
        print(f"Warning: Expected list from OpenF1, got {type(meetings)}")
        meetings = []

    now = datetime.now(timezone.utc)
    output = []

    if not meetings:
        ff_fallback = _compute_fallback_from_fastf1()
        if ff_fallback:
            return ff_fallback
        if year == 2026:
            return _compute_fallback_2026()

    for m in meetings:
        # Skip pre-season testing
        name = m.get("meeting_name", "")
        if "Testing" in name or "Test" in name:
            continue

        date_end = datetime.fromisoformat(m["date_end"].replace("Z", "+00:00"))
        date_start = datetime.fromisoformat(m["date_start"].replace("Z", "+00:00"))

        if date_end.tzinfo is None:
            date_end = date_end.replace(tzinfo=timezone.utc)
        if date_start.tzinfo is None:
            date_start = date_start.replace(tzinfo=timezone.utc)

        if date_end < now:
            mode = "past"
        elif date_start <= now <= date_end:
            mode = "live"
        else:
            mode = "upcoming"

        output.append({
            "meeting_key":  m["meeting_key"],
            "name":         m["meeting_name"],
            "official_name": m.get("meeting_official_name", ""),
            "location":     m.get("location", ""),
            "country_code": m.get("country_code", ""),
            "country_name": m.get("country_name", ""),
            "country_flag": m.get("country_flag", ""),
            "circuit_key":  m.get("circuit_key"),
            "circuit_short_name": m.get("circuit_short_name", ""),
            "circuit_type": m.get("circuit_type", ""),
            "circuit_image": m.get("circuit_image", ""),
            "date_start":   m["date_start"],
            "date_end":     m["date_end"],
            "gmt_offset":   m.get("gmt_offset", ""),
            "year":         year,
            "mode":         mode,
            "cancelled":    False,
        })

    output.sort(key=lambda x: x.get("date_start") or "")
    if year == 2026:
        _mark_cancelled_races_after_japan(output)

    return output


# ─── SESSIONS ─────────────────────────────────────────────────────────────────

def _sessions_from_fastf1_round_key(meeting_key: int) -> list[dict]:
    """
    Build sessions for synthetic meeting keys produced by FastF1 calendar fallback.
    meeting_key format: YYYYRR (e.g., 202602 = year 2026, round 2).
    """
    if not getattr(fb, "FASTF1_AVAILABLE", False):
        return []
    try:
        year = int(meeting_key) // 100
        rnd = int(meeting_key) % 100
    except Exception:
        return []
    if year < 2018 or rnd <= 0:
        return []

    try:
        schedule = fb.fastf1.get_event_schedule(year)
    except Exception:
        return []
    if schedule is None or schedule.empty:
        return []

    row = None
    for _, r in schedule.iterrows():
        try:
            if int(r.get("RoundNumber")) == rnd:
                row = r
                break
        except Exception:
            continue
    if row is None:
        return []

    base = 8_000_000_000 + int(meeting_key) * 100
    now = datetime.now(timezone.utc)
    out = []
    slot = 0
    for i in range(1, 6):
        sname = row.get(f"Session{i}")
        sdate = row.get(f"Session{i}DateUtc") or row.get(f"Session{i}Date")
        if sname is None:
            continue
        name = str(sname).strip()
        if not name or name.lower() == "nan":
            continue
        slot += 1
        sk = base + slot
        stype = "Practice"
        nl = name.lower()
        if "qualifying" in nl or "shootout" in nl:
            stype = "Qualifying"
        elif nl == "sprint" or nl == "race":
            stype = "Race"
        ff_id = fb.openf1_session_to_ff_identifier(name, stype)
        if not ff_id:
            continue

        fb.register_synthetic_session(sk, {
            "year": year,
            "gp": rnd,
            "ff_session": ff_id,
            "meeting_key": meeting_key,
            "session_name": name,
            "session_type": stype,
        })

        if sdate is None:
            ds = f"{year}-01-01T00:00:00+00:00"
        else:
            ds = sdate.isoformat() if hasattr(sdate, "isoformat") else str(sdate)
        de = ds

        try:
            ds_dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            de_dt = datetime.fromisoformat(de.replace("Z", "+00:00"))
            if ds_dt.tzinfo is None:
                ds_dt = ds_dt.replace(tzinfo=timezone.utc)
            if de_dt.tzinfo is None:
                de_dt = de_dt.replace(tzinfo=timezone.utc)
            if de_dt < now:
                status = "completed"
            elif ds_dt <= now <= de_dt:
                status = "live"
            else:
                status = "upcoming"
        except Exception:
            status = "upcoming"

        out.append({
            "session_key": sk,
            "session_name": name,
            "session_type": stype,
            "date_start": ds,
            "date_end": de,
            "status": status,
            "data_source": "fastf1",
        })

    return out

@app.get("/api/sessions/{meeting_key}")
def get_sessions(meeting_key: int):
    """Get all sessions for a meeting (FP1, Quali, Sprint, Race, etc.)."""
    # Synthetic key path for FastF1 calendar fallback rows (YYYYRR).
    synthetic_sessions = _sessions_from_fastf1_round_key(meeting_key)
    if synthetic_sessions:
        return synthetic_sessions

    try:
        sessions = _openf1("sessions", {"meeting_key": meeting_key})
    except Exception:
        sessions = []

    if not isinstance(sessions, list):
        sessions = []

    # OpenF1 occasionally returns [] for sessions?meeting_key=X even when the meeting exists.
    # Pull year-scoped sessions and filter (cached per year) so rounds like Australia work reliably.
    if not sessions:
        for yr in (2026, 2025, 2024):
            try:
                year_sessions = _openf1("sessions", {"year": yr}, ttl=_LONG_TTL)
            except Exception:
                year_sessions = []
            if not isinstance(year_sessions, list):
                continue
            filtered = [s for s in year_sessions if s.get("meeting_key") == meeting_key]
            if filtered:
                sessions = filtered
                break

    # Prefer FastF1 synthetic sessions when OpenF1 has no sessions for this meeting.
    if not sessions:
        ff_raw = fb.sessions_from_fastf1_meeting(meeting_key, _openf1)
        if ff_raw:
            sessions = ff_raw

    now = datetime.now(timezone.utc)
    output = []
    for s in sessions:
        ds = s["date_start"].replace("Z", "+00:00")
        de = s["date_end"].replace("Z", "+00:00")
        date_start = datetime.fromisoformat(ds)
        date_end = datetime.fromisoformat(de)

        if date_start.tzinfo is None:
            date_start = date_start.replace(tzinfo=timezone.utc)
        if date_end.tzinfo is None:
            date_end = date_end.replace(tzinfo=timezone.utc)

        if date_end < now:
            status = "completed"
        elif date_start <= now <= date_end:
            status = "live"
        else:
            status = "upcoming"

        out_row = {
            "session_key":  s["session_key"],
            "session_name": s["session_name"],
            "session_type": s["session_type"],
            "date_start":   s["date_start"],
            "date_end":     s["date_end"],
            "status":       status,
        }
        if s.get("data_source"):
            out_row["data_source"] = s["data_source"]
        output.append(out_row)

    # Last resort: build weekend from FastF1 schedule if everything above still failed.
    if not output:
        ff_raw = fb.sessions_from_fastf1_meeting(meeting_key, _openf1)
        for s in ff_raw:
            ds = s["date_start"].replace("Z", "+00:00")
            de = s["date_end"].replace("Z", "+00:00")
            date_start = datetime.fromisoformat(ds)
            date_end = datetime.fromisoformat(de)
            if date_start.tzinfo is None:
                date_start = date_start.replace(tzinfo=timezone.utc)
            if date_end.tzinfo is None:
                date_end = date_end.replace(tzinfo=timezone.utc)
            if date_end < now:
                status = "completed"
            elif date_start <= now <= date_end:
                status = "live"
            else:
                status = "upcoming"
            output.append({
                "session_key": s["session_key"],
                "session_name": s["session_name"],
                "session_type": s["session_type"],
                "date_start": s["date_start"],
                "date_end": s["date_end"],
                "status": status,
                "data_source": "fastf1",
            })

    # Final emergency fallback for Chinese GP (legacy OpenF1 keys), only if nothing else worked.
    if not output and meeting_key == 1280:
        output = [
            {"session_key": 11235, "session_name": "Practice 1", "session_type": "Practice", "date_start": "2026-03-13T03:30:00+00:00", "date_end": "2026-03-13T04:30:00+00:00", "status": "completed"},
            {"session_key": 11236, "session_name": "Sprint Qualifying", "session_type": "Qualifying", "date_start": "2026-03-13T07:30:00+00:00", "date_end": "2026-03-13T08:14:00+00:00", "status": "completed"},
            {"session_key": 11240, "session_name": "Sprint", "session_type": "Race", "date_start": "2026-03-14T03:00:00+00:00", "date_end": "2026-03-14T04:00:00+00:00", "status": "completed"},
            {"session_key": 11241, "session_name": "Qualifying", "session_type": "Qualifying", "date_start": "2026-03-14T07:00:00+00:00", "date_end": "2026-03-14T08:00:00+00:00", "status": "completed"},
            {"session_key": 11245, "session_name": "Race", "session_type": "Race", "date_start": "2026-03-15T07:00:00+00:00", "date_end": "2026-03-15T09:00:00+00:00", "status": "completed"},
        ]

    return output


# ─── DRIVERS ──────────────────────────────────────────────────────────────────

@app.get("/api/drivers/{session_key}")
def get_drivers(session_key: int):
    """Get all drivers for a session with team info."""
    drivers = _openf1("drivers", {"session_key": session_key})
    if not drivers:
        drivers = fb.drivers_from_fastf1(session_key, _openf1)
    return [{
        "driver_number":  d["driver_number"],
        "full_name":      d.get("full_name", ""),
        "name_acronym":   d.get("name_acronym", ""),
        "first_name":     d.get("first_name", ""),
        "last_name":      d.get("last_name", ""),
        "team_name":      d.get("team_name", ""),
        "team_colour":    d.get("team_colour", ""),
        "headshot_url":   d.get("headshot_url", ""),
        "broadcast_name": d.get("broadcast_name", ""),
    } for d in drivers]


# ─── TELEMETRY ────────────────────────────────────────────────────────────────

def _parse_ts(s: str) -> float:
    """Parse ISO timestamp to seconds-since-epoch for comparison."""
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _merge_telemetry_by_timestamp(car_data: list, location_data: list) -> list:
    """
    Merge car_data and location by timestamp so each point has aligned x,y,speed,brake.
    Uses car_data as primary; for each car point, finds nearest location by timestamp.
    """
    if not car_data:
        return []

    # Build location lookup by timestamp (sorted)
    loc_by_ts = []
    for loc in (location_data or []):
        ts = _parse_ts(loc.get("date", ""))
        if ts > 0:
            loc_by_ts.append((ts, loc.get("x", 0), loc.get("y", 0)))
    loc_by_ts.sort(key=lambda r: r[0])

    def find_nearest_loc(target_ts: float):
        if not loc_by_ts:
            return 0, 0
        lo, hi = 0, len(loc_by_ts) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if loc_by_ts[mid][0] <= target_ts:
                lo = mid
            else:
                hi = mid
        # Pick closer of lo, hi
        d_lo = abs(loc_by_ts[lo][0] - target_ts)
        d_hi = abs(loc_by_ts[hi][0] - target_ts)
        best = lo if d_lo <= d_hi else hi
        return loc_by_ts[best][1], loc_by_ts[best][2]

    merged = []
    for c in car_data:
        ts = _parse_ts(c.get("date", ""))
        x, y = find_nearest_loc(ts)
        merged.append({
            "speed": c.get("speed", 0),
            "throttle": c.get("throttle", 0),
            "brake": c.get("brake", 0),
            "n_gear": c.get("n_gear", 0),
            "drs": c.get("drs", 0),
            "date": c.get("date", ""),
            "x": x,
            "y": y,
        })
    return merged


@app.get("/api/telemetry/{session_key}/{driver_number}")
def get_telemetry(
    session_key: int,
    driver_number: int,
    lap: Optional[int] = Query(None),
):
    """
    Fetch car telemetry + location data for a driver from OpenF1.
    Merges car_data and location by timestamp for accurate track map alignment.
    Returns ~300 points with x,y,speed,brake aligned per timestamp.
    """
    try:
        from datetime import timedelta

        laps_params = {"session_key": session_key, "driver_number": driver_number}
        if lap is not None:
            laps_params["lap_number"] = lap

        laps_data = _openf1("laps", laps_params)
        if not laps_data:
            alt = fb.telemetry_from_fastf1(session_key, driver_number, lap, _openf1)
            if alt:
                return alt
            return _empty_telemetry()

        if lap is None:
            valid_laps = [l for l in laps_data
                          if l.get("lap_duration") and l["lap_duration"] > 0
                          and not l.get("is_pit_out_lap")]
            if not valid_laps:
                valid_laps = [l for l in laps_data if l.get("lap_duration") and l["lap_duration"] > 0]
            if not valid_laps:
                return _empty_telemetry()
            target_lap = min(valid_laps, key=lambda x: x["lap_duration"])
        else:
            target_lap = laps_data[0]

        lap_number = target_lap["lap_number"]
        lap_start = target_lap.get("date_start")
        if not lap_start:
            return _empty_telemetry()

        lap_duration = target_lap.get("lap_duration", 90)
        start_dt = datetime.fromisoformat(lap_start.replace("Z", "+00:00"))
        end_dt = start_dt + timedelta(seconds=lap_duration + 1)

        car_data = _openf1("car_data", {
            "session_key": session_key,
            "driver_number": driver_number,
            "date>": lap_start,
            "date<": end_dt.isoformat(),
        })

        location_data = _openf1("location", {
            "session_key": session_key,
            "driver_number": driver_number,
            "date>": lap_start,
            "date<": end_dt.isoformat(),
        })

        if not car_data:
            alt = fb.telemetry_from_fastf1(session_key, driver_number, lap, _openf1)
            if alt:
                return alt
            return _empty_telemetry()

        # Merge by timestamp for accurate alignment
        merged = _merge_telemetry_by_timestamp(car_data, location_data)
        if not merged:
            alt = fb.telemetry_from_fastf1(session_key, driver_number, lap, _openf1)
            if alt:
                return alt
            return _empty_telemetry()

        # Sample to ~400 points for smoother track (OpenF1 ~3.7 Hz, 90s lap ≈ 333 raw)
        n_target = 400
        n_raw = len(merged)
        step = max(1, n_raw // n_target)
        sampled = merged[::step][:n_target]

        speed = [d["speed"] for d in sampled]
        throttle = [d["throttle"] for d in sampled]
        brake = [d["brake"] for d in sampled]
        gear = [d["n_gear"] for d in sampled]
        drs = [d["drs"] for d in sampled]
        timestamps = [d["date"] for d in sampled]
        x_raw = [d["x"] for d in sampled]
        y_raw = [d["y"] for d in sampled]

        # Normalize X/Y to 0-1 (preserve aspect for track shape)
        x_norm, y_norm = [], []
        if x_raw and any(x != 0 for x in x_raw) and any(y != 0 for y in y_raw):
            x_min, x_max = min(x_raw), max(x_raw)
            y_min, y_max = min(y_raw), max(y_raw)
            x_range = x_max - x_min or 1
            y_range = y_max - y_min or 1
            x_norm = [round((v - x_min) / x_range, 4) for v in x_raw]
            y_norm = [round((v - y_min) / y_range, 4) for v in y_raw]
        else:
            x_norm = x_raw
            y_norm = y_raw

        return {
            "driver_number": driver_number,
            "lap":          lap_number,
            "lap_time":     round(target_lap.get("lap_duration", 0), 3),
            "n_points":     len(sampled),
            "speed":        speed,
            "throttle":     throttle,
            "brake":        brake,
            "gear":         gear,
            "drs":          drs,
            "x":            x_norm,
            "y":            y_norm,
            "x_raw":        x_raw,
            "y_raw":        y_raw,
            "timestamps":   timestamps,
            "sectors": {
                "s1": target_lap.get("duration_sector_1"),
                "s2": target_lap.get("duration_sector_2"),
                "s3": target_lap.get("duration_sector_3"),
            },
        }
    except Exception as e:
        raise HTTPException(502, f"Telemetry fetch failed: {e}")


def _empty_telemetry() -> dict:
    return {
        "driver_number": None, "lap": None, "lap_time": None, "n_points": 0,
        "speed": [], "throttle": [], "brake": [], "gear": [], "drs": [],
        "x": [], "y": [], "x_raw": [], "y_raw": [], "timestamps": [],
        "sectors": {"s1": None, "s2": None, "s3": None},
    }


def _normalize_openf1_driver_stints(stints: list) -> list:
    """
    OpenF1 stint rows are often returned out of lap order; sprint data sometimes omits
    the opening stint (first API row starts at lap > 1). Sort by lap_start, fill
    lap gaps with UNKNOWN, renumber stint_number 1..n. TyreDegModel.fit skips UNKNOWN.
    """
    if not stints:
        return []
    raw: list = []
    for s in stints:
        try:
            ls, le = int(s["lap_start"]), int(s["lap_end"])
        except (KeyError, TypeError, ValueError):
            continue
        if le < ls:
            continue
        comp = s.get("compound") or "UNKNOWN"
        if isinstance(comp, str):
            comp = comp.upper()
        else:
            comp = str(comp).upper()
        try:
            sn = int(s.get("stint_number", 0))
        except (TypeError, ValueError):
            sn = 0
        raw.append({
            "stint_number": sn,
            "compound": comp,
            "lap_start": ls,
            "lap_end": le,
            "tyre_age_at_start": s.get("tyre_age_at_start", 0),
        })
    if not raw:
        return []
    raw.sort(key=lambda x: (x["lap_start"], x["stint_number"]))
    out: list = []
    need_lap = 1
    for r in raw:
        ls, le = r["lap_start"], r["lap_end"]
        if le < need_lap:
            continue
        if ls < need_lap:
            ls = need_lap
            if ls > le:
                continue
        if ls > need_lap:
            out.append({
                "stint_number": len(out) + 1,
                "compound": "UNKNOWN",
                "lap_start": need_lap,
                "lap_end": ls - 1,
                "laps": ls - need_lap,
                "tyre_age_at_start": 0,
                "inferred_opening": True,
            })
        out.append({
            "stint_number": len(out) + 1,
            "compound": r["compound"],
            "lap_start": ls,
            "lap_end": le,
            "laps": le - ls + 1,
            "tyre_age_at_start": r.get("tyre_age_at_start", 0),
            "inferred_opening": False,
        })
        need_lap = le + 1
    for i, row in enumerate(out, 1):
        row["stint_number"] = i
    return out


# ─── LAPS ─────────────────────────────────────────────────────────────────────

def _lap_duration(lap: dict) -> Optional[float]:
    """lap_duration from API, or computed from sectors when null (common for Sprint)."""
    d = lap.get("lap_duration")
    if d is not None and d > 0:
        return float(d)
    s1, s2, s3 = lap.get("duration_sector_1"), lap.get("duration_sector_2"), lap.get("duration_sector_3")
    if s1 is not None and s2 is not None and s3 is not None:
        return float(s1) + float(s2) + float(s3)
    return None


def _finite_or_none(v):
    """Return numeric value if finite, else None (avoids JSON nan/inf errors)."""
    if v is None:
        return None
    try:
        fv = float(v)
        if fv != fv:  # nan
            return None
        if fv == float("inf") or fv == float("-inf"):
            return None
        return fv
    except Exception:
        return None


@app.get("/api/laps/{session_key}/{driver_number}")
def get_laps(session_key: int, driver_number: int):
    """Fetch all laps with sector times for a driver."""
    laps = _openf1("laps", {
        "session_key": session_key,
        "driver_number": driver_number,
    })
    if not laps:
        laps = fb.laps_from_fastf1(session_key, driver_number, _openf1)
        return laps
    return [{
        "lap_number":   l["lap_number"],
        "lap_duration": _finite_or_none(_lap_duration(l)),
        "s1":           _finite_or_none(l.get("duration_sector_1")),
        "s2":           _finite_or_none(l.get("duration_sector_2")),
        "s3":           _finite_or_none(l.get("duration_sector_3")),
        "i1_speed":     _finite_or_none(l.get("i1_speed")),
        "i2_speed":     _finite_or_none(l.get("i2_speed")),
        "st_speed":     _finite_or_none(l.get("st_speed")),
        "is_pit_out":   l.get("is_pit_out_lap", False),
    } for l in laps]


# ─── STINTS ───────────────────────────────────────────────────────────────────

@app.get("/api/stints/{session_key}")
def get_stints(session_key: int, driver_number: Optional[int] = Query(None)):
    """Fetch tyre stint data. Optionally filter by driver."""
    params = {"session_key": session_key}
    if driver_number is not None:
        params["driver_number"] = driver_number
    stints = _openf1("stints", params)
    if not stints:
        stints = fb.stints_from_fastf1(session_key, _openf1, driver_number)

    # Group by driver number
    grouped = {}
    for s in stints:
        dn = s["driver_number"]
        if dn not in grouped:
            grouped[dn] = []
        grouped[dn].append({
            "stint_number": s["stint_number"],
            "compound":     s.get("compound", "UNKNOWN"),
            "lap_start":    s["lap_start"],
            "lap_end":      s["lap_end"],
            "laps":         s["lap_end"] - s["lap_start"] + 1,
            "tyre_age_at_start": s.get("tyre_age_at_start", 0),
        })

    for dn in list(grouped.keys()):
        grouped[dn] = _normalize_openf1_driver_stints(grouped[dn])

    return grouped


# ─── RESULT ───────────────────────────────────────────────────────────────────

@app.get("/api/result/{session_key}")
def get_result(session_key: int):
    """Fetch session finishing order with driver info."""
    try:
        results = _openf1("session_result", {"session_key": session_key})
    except Exception:
        results = []

    if not results:
        results = fb.session_result_from_fastf1(session_key, _openf1)

    if not results:
        return []

    # Enrich with driver info
    try:
        drivers = _openf1("drivers", {"session_key": session_key})
        driver_map = {d["driver_number"]: d for d in drivers}
    except Exception:
        driver_map = {}
    if not driver_map:
        for d in fb.drivers_from_fastf1(session_key, _openf1):
            driver_map[d["driver_number"]] = d

    for r in results:
        d = driver_map.get(r["driver_number"], {})
        r["full_name"] = d.get("full_name", f"Driver {r['driver_number']}")
        r["name_acronym"] = d.get("name_acronym", "")
        r["team_name"] = d.get("team_name", "Unknown")
        r["team_colour"] = d.get("team_colour", "5a5a80")
    return sorted(results, key=lambda x: x.get("position") or 99)


# ─── STARTING GRID ────────────────────────────────────────────────────────────

@app.get("/api/starting_grid/{session_key}")
def get_starting_grid(session_key: int):
    """Fetch the starting grid for a race session."""
    grid = _openf1("starting_grid", {"session_key": session_key})
    return sorted(grid, key=lambda x: x.get("position") or 99)


# ─── WEATHER ──────────────────────────────────────────────────────────────────

@app.get("/api/weather/{session_key}")
def get_weather(session_key: int):
    """Fetch weather data for a session (first + last readings)."""
    weather = _openf1("weather", {"session_key": session_key})
    if not weather:
        return {"air_temperature": None, "track_temperature": None,
                "humidity": None, "wind_speed": None, "rainfall": False}

    # Return summary: averages of first and last reading
    first = weather[0]
    last = weather[-1]
    return {
        "air_temperature":   round((first.get("air_temperature", 0) + last.get("air_temperature", 0)) / 2, 1),
        "track_temperature": round((first.get("track_temperature", 0) + last.get("track_temperature", 0)) / 2, 1),
        "humidity":          round((first.get("humidity", 0) + last.get("humidity", 0)) / 2, 1),
        "wind_speed":        round((first.get("wind_speed", 0) + last.get("wind_speed", 0)) / 2, 1),
        "rainfall":          any(w.get("rainfall", 0) for w in weather),
        "n_readings":        len(weather),
    }


# ─── PREDICT ──────────────────────────────────────────────────────────────────

class PredictRequest(BaseModel):
    session_key: Optional[int] = None   # Qualifying session key (may be None for pre-quali)
    race_session_key: Optional[int] = None
    meeting_key: int
    circuit: str = "Australia"
    n_sims: int = 100000
    force_refresh: bool = False
    # How to choose the data source for building the grid:
    # "auto"          → current behaviour (qualifying if available, else sprint quali / practice / team rankings)
    # "full_quali"    → force main Qualifying session
    # "sprint_quali"  → force Sprint Qualifying / Sprint Shootout
    # "fp_only"       → ignore qualifying and sprint quali, estimate from practice / team rankings
    source_mode: str = "auto"


@app.post("/api/predict")
def predict(req: PredictRequest):
    """
    Run Monte Carlo prediction pipeline.
    Works with or without qualifying data:
    - If qualifying completed → use actual quali results
    - If only practice/sprint quali → estimate grid from best available data
    - If no session data → use driver list with team-based estimates
    """
    # Gather all sessions for this meeting
    try:
        sessions = _openf1("sessions", {"meeting_key": req.meeting_key})
    except Exception:
        sessions = []
    if not sessions:
        sessions = _sessions_from_fastf1_round_key(req.meeting_key)
    if not sessions:
        sessions = fb.sessions_from_fastf1_meeting(req.meeting_key, _openf1)

    def _drivers_for_session(sk: int) -> list:
        rows = _openf1("drivers", {"session_key": sk})
        if not rows:
            rows = fb.drivers_from_fastf1(sk, _openf1)
        return rows if isinstance(rows, list) else []

    def _session_result_for_session(sk: int) -> list:
        rows = _openf1("session_result", {"session_key": sk})
        if not rows:
            rows = fb.session_result_from_fastf1(sk, _openf1)
        return rows if isinstance(rows, list) else []

    request_key = _prediction_request_key(
        req.meeting_key, req.session_key, req.race_session_key, req.n_sims, req.source_mode
    )
    data_version = _build_prediction_data_version(
        req.meeting_key, sessions, req.session_key, req.race_session_key, req.source_mode
    )
    cache_key = _local_cache_key(request_key, data_version)

    # Check cache after computing upstream data fingerprint.
    if not req.force_refresh:
        cached = _load_supabase_cache(request_key, data_version)
        if not cached:
            cached = _load_cache(cache_key)
        if cached:
            cached["cached"] = True
            cached["data_version"] = data_version
            return cached

    # Get driver info from ANY completed session
    driver_map = {}
    for s in sessions:
        if s.get("status") == "completed" or s.get("session_key") == req.session_key:
            try:
                drivers = _drivers_for_session(s["session_key"])
                for d in drivers:
                    driver_map[d["driver_number"]] = d
                if driver_map:
                    break
            except Exception:
                pass

    # If still no drivers, try the race session or any session
    if not driver_map:
        for s in sessions:
            try:
                drivers = _drivers_for_session(s["session_key"])
                for d in drivers:
                    driver_map[d["driver_number"]] = d
                if driver_map:
                    break
            except Exception:
                pass

    # Apply dynamic circuit SC/VSC/rain probabilities from OpenF1 when available
    try:
        circuit_key = None
        for s in sessions:
            if s.get("circuit_key"):
                circuit_key = s["circuit_key"]
                break
        if circuit_key is not None:
            dynamic_stats = _get_circuit_stats_from_openf1(circuit_key)
            if dynamic_stats:
                # Blend historical stats with prior and avoid hard 0%/100% extremes
                base = mc.CIRCUIT_PARAMS.get(req.circuit, mc.CIRCUIT_PARAMS.get("Australia", {})).copy()
                prior_sc = base.get("sc_prob", 0.5)
                prior_vsc = base.get("vsc_prob", 0.25)
                prior_rain = base.get("rain_prob", 0.15)
                emp_sc = float(dynamic_stats.get("sc_prob", prior_sc))
                emp_vsc = float(dynamic_stats.get("vsc_prob", prior_vsc))
                emp_rain = float(dynamic_stats.get("rain_prob", prior_rain))
                blend = 0.5  # 50% prior, 50% empirical

                def _blend(prior: float, empirical: float, floor: float = 0.05, ceil: float = 0.95) -> float:
                    v = prior * (1.0 - blend) + empirical * blend
                    return max(floor, min(ceil, v))

                base.update({
                    "sc_prob": _blend(prior_sc, emp_sc, floor=0.05),
                    "vsc_prob": _blend(prior_vsc, emp_vsc, floor=0.02),
                    "rain_prob": _blend(prior_rain, emp_rain, floor=0.01),
                })
                mc.CIRCUIT_PARAMS[req.circuit] = base
    except Exception:
        pass

    # Strategy: try data sources in order of quality
    qualifying = []
    prediction_basis = "estimated"
    source_mode = getattr(req, "source_mode", "auto") or "auto"

    # 1) Try actual qualifying results, depending on source_mode
    target_session_key: Optional[int] = None
    target_label = None

    if source_mode == "full_quali":
        q_sess = next(
            (s for s in sessions if s["session_name"] == "Qualifying" and s.get("status") == "completed"),
            None,
        )
        if q_sess:
            target_session_key = q_sess["session_key"]
            target_label = "Qualifying"
    elif source_mode == "sprint_quali":
        q_sess = next(
            (
                s for s in sessions
                if s["session_name"] in ("Sprint Qualifying", "Sprint Shootout") and s.get("status") == "completed"
            ),
            None,
        )
        if q_sess:
            target_session_key = q_sess["session_key"]
            target_label = q_sess["session_name"]
    elif source_mode == "auto" and req.session_key:
        target_session_key = req.session_key
        target_label = "Qualifying"

    if target_session_key:
        try:
            quali_results = _session_result_for_session(target_session_key)
            if quali_results:
                prediction_basis = (
                    "qualifying"
                    if source_mode == "auto"
                    else f"qualifying ({target_label or 'manual'})"
                )
                for r in sorted(quali_results, key=lambda x: x.get("position") or 99):
                    dn = r["driver_number"]
                    d = driver_map.get(dn, {})
                    pos = r.get("position", 22)
                    duration = r.get("duration")
                    q_time = None
                    if isinstance(duration, list):
                        for t in reversed(duration):
                            if t and t > 0:
                                q_time = t
                                break
                    elif duration and duration > 0:
                        q_time = duration
                    qualifying.append({
                        "pos":          pos,
                        "driver":       d.get("full_name", f"Driver {dn}"),
                        "team":         d.get("team_name", "Unknown"),
                        "q_time":       q_time,
                        "abbreviation": d.get("name_acronym", ""),
                        "driver_number": dn,
                        "team_colour":  d.get("team_colour", "5a5a80"),
                    })
        except Exception:
            pass

    # 2) If no quali data yet, try sprint qualifying or practice results
    if not qualifying:
        # Choose priority based on requested source_mode
        if source_mode == "fp_only":
            priority = ["Practice 3", "Practice 2", "Practice 1"]
        elif source_mode == "sprint_quali":
            priority = ["Sprint Qualifying", "Sprint Shootout"]
        elif source_mode == "full_quali":
            priority = ["Qualifying"]
        else:
            # auto
            priority = ["Sprint Qualifying", "Sprint Shootout", "Practice 3", "Practice 2", "Practice 1"]
        for pname in priority:
            target = next((s for s in sessions if s["session_name"] == pname and s.get("status") == "completed"), None)
            if not target:
                continue
            try:
                results = _session_result_for_session(target["session_key"])
                if results:
                    prediction_basis = f"estimated ({pname})"
                    for r in sorted(results, key=lambda x: x.get("position") or 99):
                        dn = r["driver_number"]
                        d = driver_map.get(dn, {})
                        pos = r.get("position", 22)
                        duration = r.get("duration")
                        q_time = None
                        if isinstance(duration, (int, float)) and duration > 0:
                            q_time = duration
                        qualifying.append({
                            "pos":          pos,
                            "driver":       d.get("full_name", f"Driver {dn}"),
                            "team":         d.get("team_name", "Unknown"),
                            "q_time":       q_time,
                            "abbreviation": d.get("name_acronym", ""),
                            "driver_number": dn,
                            "team_colour":  d.get("team_colour", "5a5a80"),
                        })
                    break
            except Exception:
                continue

    # 3) Last resort: use driver list with team-based ordering
    if not qualifying and driver_map:
        prediction_basis = "estimated (team rankings)"
        # Rough 2026 team order for grid estimation
        team_rank = {
            "Mercedes": 1, "Ferrari": 2, "McLaren": 3, "Red Bull Racing": 4,
            "Aston Martin": 5, "Alpine": 6, "Williams": 7, "Racing Bulls": 8,
            "Haas F1 Team": 9, "Kick Sauber": 10, "Cadillac": 11, "Audi": 12,
        }
        sorted_drivers = sorted(
            driver_map.values(),
            key=lambda d: (team_rank.get(d.get("team_name", ""), 99), d.get("driver_number", 99))
        )
        for i, d in enumerate(sorted_drivers):
            qualifying.append({
                "pos":          i + 1,
                "driver":       d.get("full_name", f"Driver {d['driver_number']}"),
                "team":         d.get("team_name", "Unknown"),
                "q_time":       None,
                "abbreviation": d.get("name_acronym", ""),
                "driver_number": d["driver_number"],
                "team_colour":  d.get("team_colour", "5a5a80"),
            })

    if not qualifying:
        raise HTTPException(404, "No data available to generate predictions for this meeting.")

    # Fetch practice times (best lap per driver from FP sessions)
    fp_times = {}
    try:
        fp_sessions = [s for s in sessions if s.get("session_type") == "Practice" and s.get("status") == "completed"]
        for fps in fp_sessions:
            fp_key = fps["session_name"].lower().replace("practice ", "fp")
            fp_results = _session_result_for_session(fps["session_key"])
            for fr in fp_results:
                dn = fr["driver_number"]
                d = driver_map.get(dn, {})
                name = d.get("full_name", f"Driver {dn}")
                if name not in fp_times:
                    fp_times[name] = {}
                dur = fr.get("duration")
                if isinstance(dur, (int, float)) and dur > 0:
                    fp_times[name][fp_key] = dur
    except Exception:
        pass

    # Build optional weekend_incidents with sprint performance for race prediction
    weekend_incidents: dict[str, dict] = {}
    try:
        sprint_session = next(
            (s for s in sessions if s.get("session_name") == "Sprint" and s.get("status") == "completed"),
            None,
        )
        if sprint_session:
            sprint_results = _session_result_for_session(sprint_session["session_key"])
            if isinstance(sprint_results, list) and sprint_results:
                sprint_pos = {r["driver_number"]: r.get("position", 22) for r in sprint_results}
                qual_pos = {q["driver_number"]: q["pos"] for q in qualifying if q.get("driver_number") is not None}
                for q in qualifying:
                    dn = q.get("driver_number")
                    if not dn or dn not in sprint_pos or dn not in qual_pos:
                        continue
                    qpos = qual_pos[dn]
                    spos = sprint_pos[dn]
                    # Positive delta means gained positions vs grid in Sprint
                    delta = qpos - spos
                    # Normalise: base 0.5, ±0.05 per position change, clipped to [0,1]
                    sprint_perf = max(0.0, min(1.0, 0.5 + 0.05 * delta))
                    name = q["driver"]
                    weekend_incidents.setdefault(name, {})["sprint_perf"] = sprint_perf
    except Exception:
        weekend_incidents = {}

    # Run model pipeline
    result = mc.run_prediction_pipeline(
        qualifying=qualifying,
        fp_times=fp_times,
        circuit=req.circuit,
        n_sims=req.n_sims,
        weekend_incidents=weekend_incidents,
    )

    output = {
        "session_key":      req.session_key,
        "meeting_key":      req.meeting_key,
        "circuit":          req.circuit,
        "n_sims":           req.n_sims,
        "prediction_basis": prediction_basis,
        "data_version":     data_version,
        **result,
        "cached":           False,
    }

    _save_cache(cache_key, output)
    _save_supabase_cache(request_key, data_version, output)
    return output


# ─── STRATEGY ENGINE ──────────────────────────────────────────────────────────

class StrategySimulateRequest(BaseModel):
    meeting_key: int
    circuit: str = "Australia"
    n_sims: int = 30000
    available_compounds: list[str] = ["SOFT", "MEDIUM", "HARD"]
    custom_pit_loss: Optional[float] = None
    custom_total_laps: Optional[int] = None
    driver_numbers: Optional[list[int]] = None
    session_type: str = "Race"


class StrategyLiveScenarioRequest(BaseModel):
    """Mid-race strategy with fixed SC/VSC/red flag and gap context."""
    meeting_key: int
    circuit: str = "Australia"
    driver_number: int
    current_lap: int = 1
    current_compound: str = "MEDIUM"
    stint_age: int = 5
    gap_ahead: float = 2.0
    gap_behind: float = 2.0
    safety_car_lap: Optional[int] = None
    vsc_lap: Optional[int] = None
    red_flag_lap: Optional[int] = None
    puncture: bool = False
    session_type: str = "Race"
    available_compounds: Optional[list[str]] = None
    custom_pit_loss: Optional[float] = None
    custom_total_laps: Optional[int] = None


# FIA standard tyre allocation per weekend
TYRE_ALLOCATION_NORMAL = {"SOFT": 8, "MEDIUM": 3, "HARD": 2}
TYRE_ALLOCATION_SPRINT = {"SOFT": 6, "MEDIUM": 4, "HARD": 2}


def _select_race_or_sprint_session(sessions: list, for_sprint: bool):
    """Pick main Race or Sprint session (same rules as get_strategy_actual)."""
    if for_sprint:
        return next(
            (s for s in sessions
             if "sprint" in (s.get("session_name") or "").lower()
             and "qualifying" not in (s.get("session_name") or "").lower()),
            None,
        )
    return next(
        (s for s in sessions if (s.get("session_name") or "").strip() == "Race"),
        None,
    )


def _estimate_sprint_race_total_laps(sessions: list) -> Optional[int]:
    """Use max lap number from a completed sprint session, else None."""
    target = _select_race_or_sprint_session(sessions, True)
    if not target or target.get("status") != "completed":
        return None
    sk = target.get("session_key")
    if not sk:
        return None
    try:
        laps = _openf1("laps", {"session_key": sk})
    except Exception:
        laps = []
    if not isinstance(laps, list) or not laps:
        return None
    mx = 0
    for lap in laps:
        ln = lap.get("lap_number")
        if ln is not None and int(ln) > mx:
            mx = int(ln)
    return mx if mx >= 5 else None


def _fetch_previous_year_stop_profile(
    circuit_key: int, current_year: int, for_sprint: bool,
) -> Optional[dict]:
    """
    Aggregate stop patterns from last year's race or sprint at this circuit.
    - Race: 1-stop vs 2-stop vs 3+ (drivers need ≥2 stint rows).
    - Sprint: 0-stop (single stint) vs 1-stop vs 2+ (sprints are usually no-stop or one-stop).
    """
    prev_year = current_year - 1
    if prev_year < 2020:
        return None
    try:
        meetings = _openf1("meetings", {"year": prev_year, "circuit_key": circuit_key})
    except Exception:
        meetings = []
    if not isinstance(meetings, list) or not meetings:
        return None
    mk = meetings[0].get("meeting_key")
    if not mk:
        return None
    try:
        prev_sessions = _openf1("sessions", {"meeting_key": mk})
    except Exception:
        prev_sessions = []
    if not isinstance(prev_sessions, list):
        return None
    target = _select_race_or_sprint_session(prev_sessions, for_sprint)
    if not target:
        return None
    sk = target.get("session_key")
    if not sk:
        return None
    try:
        raw_stints = _openf1("stints", {"session_key": sk})
    except Exception:
        raw_stints = []
    if not isinstance(raw_stints, list) or not raw_stints:
        return None

    by_driver: dict[int, list] = {}
    for st in raw_stints:
        dn = st["driver_number"]
        by_driver.setdefault(dn, []).append(st)

    if for_sprint:
        zero_stop = one_stop = two_plus = 0
        for rows in by_driver.values():
            n_stints = len(rows)
            n_stops = max(0, n_stints - 1)
            if n_stops > 3:
                continue
            if n_stints == 1:
                zero_stop += 1
            elif n_stops == 1:
                one_stop += 1
            else:
                two_plus += 1

        sample = zero_stop + one_stop + two_plus
        if sample < 6:
            return None

        p0 = round(100.0 * zero_stop / sample, 1)
        p1 = round(100.0 * one_stop / sample, 1)
        p2p = round(100.0 * two_plus / sample, 1)

        clamped = False
        if two_plus >= zero_stop and two_plus >= one_stop and two_plus > 0:
            dominant_pits = 1
            clamped = True
            confidence = (two_plus / sample) * 0.52
        elif zero_stop > one_stop:
            dominant_pits = 0
            confidence = zero_stop / sample
        elif one_stop > zero_stop:
            dominant_pits = 1
            confidence = one_stop / sample
        else:
            dominant_pits = 0
            confidence = (zero_stop / sample) * 0.72

        confidence = float(min(0.95, max(0.35, confidence)))
        bonus_seconds = float(min(36.0, 3.5 + 40.0 * confidence))

        return {
            "dominant_pits": dominant_pits,
            "confidence": round(confidence, 3),
            "bonus_seconds": round(bonus_seconds, 2),
            "sample_size": sample,
            "session_kind": "sprint",
            "zero_stop_pct": p0,
            "one_stop_pct": p1,
            "two_plus_pct": p2p,
            "two_stop_pct": 0.0,
            "three_plus_pct": 0.0,
            "source_year": prev_year,
            "clamped_from_three_plus": False,
            "clamped_from_two_plus": clamped,
            "session_name": target.get("session_name", "Sprint"),
        }

    one_stop = two_stop = three_plus = 0
    for rows in by_driver.values():
        n_stints = len(rows)
        n_stops = max(0, n_stints - 1)
        if n_stints < 2:
            continue
        if n_stops > 4:
            continue
        if n_stops == 1:
            one_stop += 1
        elif n_stops == 2:
            two_stop += 1
        else:
            three_plus += 1

    sample = one_stop + two_stop + three_plus
    if sample < 8:
        return None

    p1 = round(100.0 * one_stop / sample, 1)
    p2 = round(100.0 * two_stop / sample, 1)
    p3 = round(100.0 * three_plus / sample, 1)

    clamped = False
    if three_plus >= one_stop and three_plus >= two_stop:
        dominant_pits = 2
        clamped = three_plus > 0
        confidence = (three_plus / sample) * 0.55 if clamped else (two_stop / sample)
    elif one_stop > two_stop:
        dominant_pits = 1
        confidence = one_stop / sample
    elif two_stop > one_stop:
        dominant_pits = 2
        confidence = two_stop / sample
    else:
        dominant_pits = 2
        confidence = (one_stop / sample) * 0.72

    confidence = float(min(0.95, max(0.35, confidence)))
    # Scale so bias can overcome deg-model raw gaps (~10–40s) when the field strongly
    # favored one stop count last year (confidence = dominant share).
    bonus_seconds = float(min(42.0, 4.0 + 48.0 * confidence))

    return {
        "dominant_pits": dominant_pits,
        "confidence": round(confidence, 3),
        "bonus_seconds": round(bonus_seconds, 2),
        "sample_size": sample,
        "session_kind": "race",
        "zero_stop_pct": 0.0,
        "one_stop_pct": p1,
        "two_stop_pct": p2,
        "three_plus_pct": p3,
        "two_plus_pct": 0.0,
        "source_year": prev_year,
        "clamped_from_three_plus": clamped,
        "clamped_from_two_plus": False,
        "session_name": target.get("session_name", "Race"),
    }


def _fetch_grid_positions(sessions: list, session_type: str) -> dict[int, int]:
    """Fetch grid positions from the appropriate qualifying session.
    Returns {driver_number: grid_position}.
    For Race: use full Qualifying (session_name exactly 'Qualifying', or last Qualifying by date).
    For Sprint: use Sprint Qualifying (session_name contains 'Sprint' and 'Qualifying')."""
    all_quali = [s for s in sessions if s.get("session_type") == "Qualifying"]
    if session_type == "Sprint":
        quali_sessions = [s for s in all_quali
                         if "sprint" in (s.get("session_name") or "").lower()]
    else:
        quali_sessions = [s for s in all_quali
                         if (s.get("session_name") or "").strip() == "Qualifying"]
        if not quali_sessions:
            quali_sessions = [s for s in all_quali
                             if "sprint" not in (s.get("session_name") or "").lower()]
        if len(quali_sessions) > 1:
            quali_sessions = sorted(quali_sessions,
                                   key=lambda x: x.get("date_start", ""),
                                   reverse=True)[:1]
    for qs in quali_sessions:
        try:
            results = _openf1("session_result", {"session_key": qs["session_key"]})
            if results:
                return {r["driver_number"]: r.get("position", 22) for r in results}
        except Exception:
            pass
    return {}


def _compute_tyre_allocation(meeting_key: int, sessions: list, is_sprint: bool) -> dict:
    """Compute tyre sets used/remaining per driver from stint data across all sessions."""
    base_alloc = TYRE_ALLOCATION_SPRINT if is_sprint else TYRE_ALLOCATION_NORMAL

    all_stints = []
    for s in sessions:
        sk = s["session_key"]
        stype = s.get("session_type", "")
        if stype == "Race":
            continue
        try:
            raw = _openf1("stints", {"session_key": sk})
            if isinstance(raw, list):
                all_stints.extend(raw)
        except Exception:
            pass

    driver_usage: dict[int, dict[str, int]] = {}
    for st in all_stints:
        dn = st["driver_number"]
        compound = (st.get("compound") or "UNKNOWN").upper()
        if compound not in base_alloc:
            continue
        if st.get("tyre_age_at_start", 0) == 0:
            if dn not in driver_usage:
                driver_usage[dn] = {"SOFT": 0, "MEDIUM": 0, "HARD": 0}
            driver_usage[dn][compound] = driver_usage[dn].get(compound, 0) + 1

    result = {}
    for dn, usage in driver_usage.items():
        result[dn] = {}
        for comp in ["SOFT", "MEDIUM", "HARD"]:
            allocated = base_alloc.get(comp, 0)
            used = usage.get(comp, 0)
            result[dn][comp] = {
                "allocated": allocated,
                "used": used,
                "remaining": max(0, allocated - used),
            }
    return result


def _fetch_session_stints_laps(sessions: list, driver_map: dict,
                               session_type: str,
                               session_name_filter: callable = None) -> list[tuple[dict, dict]]:
    """
    Fetch stints + laps from sessions matching session_type.

    session_name_filter: optional callable(session_name) -> bool to filter
    (e.g. exclude Sprint when we want main Race only).
    Returns list of (stints_dict, laps_dict) - one per session so lap numbers match.
    """
    target_sessions = [s for s in sessions
                      if s.get("session_type") == session_type
                      and s.get("status") == "completed"]
    if session_name_filter is not None:
        target_sessions = [s for s in target_sessions
                          if session_name_filter(s.get("session_name") or "")]

    result: list[tuple[dict, dict]] = []

    for sess in target_sessions:
        sk = sess["session_key"]
        all_stints: dict[str, list] = {}
        all_laps: dict[int, list] = {}

        try:
            raw_stints = _openf1("stints", {"session_key": sk})
        except Exception:
            raw_stints = []
        if isinstance(raw_stints, list):
            for st in raw_stints:
                dn = str(st["driver_number"])
                if dn not in all_stints:
                    all_stints[dn] = []
                all_stints[dn].append({
                    "stint_number": st["stint_number"],
                    "compound": st.get("compound", "UNKNOWN"),
                    "lap_start": st["lap_start"],
                    "lap_end": st["lap_end"],
                    "tyre_age_at_start": st.get("tyre_age_at_start", 0),
                })

        for _dn_key in list(all_stints.keys()):
            all_stints[_dn_key] = _normalize_openf1_driver_stints(all_stints[_dn_key])

        for dn_int in set(int(k) for k in all_stints.keys()):
            try:
                raw_laps = _openf1("laps", {
                    "session_key": sk, "driver_number": dn_int})
            except Exception:
                raw_laps = []
            if isinstance(raw_laps, list) and raw_laps:
                laps_list = []
                for l in raw_laps:
                    dur = l.get("lap_duration")
                    if dur is None or dur <= 0:
                        s1 = l.get("duration_sector_1")
                        s2 = l.get("duration_sector_2")
                        s3 = l.get("duration_sector_3")
                        if s1 and s2 and s3:
                            dur = s1 + s2 + s3
                    laps_list.append({
                        "lap_number": l["lap_number"],
                        "lap_duration": dur,
                        "s1": l.get("duration_sector_1"),
                        "s2": l.get("duration_sector_2"),
                        "s3": l.get("duration_sector_3"),
                        "is_pit_out": l.get("is_pit_out_lap", False),
                    })
                all_laps[dn_int] = laps_list

        if all_stints:
            result.append((all_stints, all_laps))

    return result


def _fetch_degradation_data(sessions: list, driver_map: dict) -> list[tuple[dict, dict]]:
    """
    Fetch stints + laps from Practice, Race, and Sprint for deg model.

    Returns list of (stints_dict, laps_dict) per session.
    Preference order: Practice first, then Race, then Sprint.
    Practice is preferred when both exist; Race/Sprint fill gaps.
    """
    result: list[tuple[dict, dict]] = []

    # 1. Practice (all FP sessions - FP1, FP2, FP3)
    result.extend(_fetch_session_stints_laps(sessions, driver_map, "Practice"))

    # 2. Main Race (exclude Sprint) - session_name exactly "Race"
    result.extend(_fetch_session_stints_laps(
        sessions, driver_map, "Race",
        session_name_filter=lambda n: n.strip() == "Race"))

    # 3. Sprint (if present)
    result.extend(_fetch_session_stints_laps(
        sessions, driver_map, "Race",
        session_name_filter=lambda n: "sprint" in n.lower() and "qualifying" not in n.lower()))

    return result


@app.post("/api/strategy/simulate")
def strategy_simulate(req: StrategySimulateRequest):
    """Run tyre strategy Monte Carlo simulation using practice session data."""
    try:
        sessions = _openf1("sessions", {"meeting_key": req.meeting_key})
    except Exception:
        sessions = []
    if not sessions:
        sessions = _sessions_from_fastf1_round_key(req.meeting_key)
    if not sessions:
        sessions = fb.sessions_from_fastf1_meeting(req.meeting_key, _openf1)

    driver_map = {}
    for s in sessions:
        try:
            drivers = _openf1("drivers", {"session_key": s["session_key"]})
            if not drivers:
                drivers = fb.drivers_from_fastf1(s["session_key"], _openf1)
            for d in drivers:
                driver_map[d["driver_number"]] = d
            if driver_map:
                break
        except Exception:
            pass

    if not driver_map:
        raise HTTPException(404, "No driver data available for this meeting.")

    grid_positions = _fetch_grid_positions(sessions, req.session_type)

    is_sprint = any(s.get("session_type") == "Sprint" for s in sessions)
    tyre_alloc = _compute_tyre_allocation(req.meeting_key, sessions, is_sprint)

    data_sources = _fetch_degradation_data(sessions, driver_map)

    deg_model = se.TyreDegModel()
    drivers_list = [{"driver_number": dn, "full_name": d.get("full_name", ""),
                     "team_name": d.get("team_name", "")}
                    for dn, d in driver_map.items()]
    for stints, laps in data_sources:
        deg_model.fit(stints, laps, drivers_list)

    sprint_race = req.session_type == "Sprint"
    sprint_laps: Optional[int] = None
    if sprint_race:
        sprint_laps = req.custom_total_laps or _estimate_sprint_race_total_laps(sessions)
        sprint_laps = sprint_laps if sprint_laps else 24
    effective_laps = sprint_laps if sprint_race else req.custom_total_laps

    sim = se.StrategySimulator(
        deg_model=deg_model,
        circuit=req.circuit,
        available_compounds=req.available_compounds,
        custom_pit_loss=req.custom_pit_loss,
        custom_total_laps=effective_laps,
        sprint_race=sprint_race,
    )

    sim_drivers = []
    for dn, d in driver_map.items():
        if req.driver_numbers and dn not in req.driver_numbers:
            continue
        gp = grid_positions.get(dn, 22)
        driver_alloc = tyre_alloc.get(dn, {})
        driver_compounds = []
        for c in req.available_compounds:
            info = driver_alloc.get(c)
            if info is None:
                driver_compounds.append(c)
            elif info.get("remaining", 0) > 0:
                driver_compounds.append(c)
        # OpenF1 stint tallies often "use up" 8+ softs in FP; that leaves 0–1 compound
        # with remaining>0. Full races need ≥2 compounds for 1/2-stop; sprints need ≥2 for 1-stop
        # (0-stop only needs one compound but we keep a full set when in doubt).
        if not driver_compounds or len(driver_compounds) < 2:
            driver_compounds = list(req.available_compounds)

        sim_drivers.append({
            "driver": d.get("full_name", f"Driver {dn}"),
            "driver_number": dn,
            "team": d.get("team_name", ""),
            "team_colour": d.get("team_colour", "5a5a80"),
            "grid_pos": gp,
            "available_compounds": driver_compounds,
            "tyre_allocation": driver_alloc,
        })

    if not sim_drivers:
        raise HTTPException(400, "No matching drivers found.")

    circuit_key = None
    current_year = None
    for s in sessions:
        if s.get("circuit_key") is not None:
            circuit_key = s["circuit_key"]
        if s.get("year") is not None:
            current_year = s["year"]
        if circuit_key is not None and current_year is not None:
            break

    historical_stop_bias = None
    historical_stop_profile = None
    if circuit_key is not None and current_year is not None:
        profile = _fetch_previous_year_stop_profile(
            int(circuit_key), int(current_year), req.session_type == "Sprint",
        )
        if profile:
            historical_stop_profile = dict(profile)
            historical_stop_bias = {
                "dominant_pits": profile["dominant_pits"],
                "confidence": profile["confidence"],
                "bonus_seconds": profile["bonus_seconds"],
            }

    result = sim.run_monte_carlo(
        sim_drivers, n_sims=req.n_sims, historical_stop_bias=historical_stop_bias,
    )
    result["meeting_key"] = req.meeting_key
    result["session_type"] = req.session_type
    result["grid_positions"] = grid_positions
    result["tyre_allocation"] = {str(k): v for k, v in tyre_alloc.items()}
    if historical_stop_profile:
        result.setdefault("meta", {})["historical_stop_profile"] = historical_stop_profile
    return result


@app.post("/api/strategy/live-scenario")
def strategy_live_scenario(req: StrategyLiveScenarioRequest):
    """
    Optimal tyre strategy from current lap with user-defined SC/VSC/red flag/puncture
    and gaps to cars ahead/behind (undercut/overcut-style adjustments).
    """
    try:
        sessions = _openf1("sessions", {"meeting_key": req.meeting_key})
    except Exception:
        sessions = []
    if not sessions:
        sessions = _sessions_from_fastf1_round_key(req.meeting_key)
    if not sessions:
        sessions = fb.sessions_from_fastf1_meeting(req.meeting_key, _openf1)

    driver_map = {}
    for s in sessions:
        try:
            drivers = _openf1("drivers", {"session_key": s["session_key"]})
            if not drivers:
                drivers = fb.drivers_from_fastf1(s["session_key"], _openf1)
            for d in drivers:
                driver_map[d["driver_number"]] = d
            if driver_map:
                break
        except Exception:
            pass

    if not driver_map:
        raise HTTPException(404, "No driver data available for this meeting.")

    if req.driver_number not in driver_map:
        raise HTTPException(404, f"Driver #{req.driver_number} not found for this meeting.")

    is_sprint = any(s.get("session_type") == "Sprint" for s in sessions)
    tyre_alloc = _compute_tyre_allocation(req.meeting_key, sessions, is_sprint)

    data_sources = _fetch_degradation_data(sessions, driver_map)
    deg_model = se.TyreDegModel()
    drivers_list = [{"driver_number": dn, "full_name": d.get("full_name", ""),
                     "team_name": d.get("team_name", "")}
                    for dn, d in driver_map.items()]
    for stints, laps in data_sources:
        deg_model.fit(stints, laps, drivers_list)

    comps = list(req.available_compounds or ["SOFT", "MEDIUM", "HARD"])
    alloc = tyre_alloc.get(req.driver_number, {})
    if alloc:
        filtered = [c for c in comps if alloc.get(c, {}).get("remaining", 1) > 0]
        if len(filtered) >= 2:
            comps = filtered
        # else: keep full comps — same ≥2 compounds rule as strategy_simulate

    live_sprint = req.session_type == "Sprint"
    live_laps = req.custom_total_laps
    if live_sprint:
        live_laps = live_laps or _estimate_sprint_race_total_laps(sessions) or 24

    sim = se.StrategySimulator(
        deg_model=deg_model,
        circuit=req.circuit,
        available_compounds=comps,
        custom_pit_loss=req.custom_pit_loss,
        custom_total_laps=live_laps if live_sprint else req.custom_total_laps,
        sprint_race=live_sprint,
    )

    total = sim.total_laps
    if req.current_lap < 1 or req.current_lap > total:
        raise HTTPException(400, f"current_lap must be between 1 and {total}")

    d = driver_map[req.driver_number]
    name = d.get("full_name", f"Driver {req.driver_number}")

    out = sim.run_live_scenario(
        driver=name,
        current_lap=req.current_lap,
        current_compound=req.current_compound,
        stint_age=max(0, req.stint_age),
        gap_ahead=req.gap_ahead,
        gap_behind=req.gap_behind,
        sc_lap=req.safety_car_lap,
        vsc_lap=req.vsc_lap,
        red_flag_lap=req.red_flag_lap,
        puncture=req.puncture,
        available_compounds=comps,
    )
    out["meeting_key"] = req.meeting_key
    out["session_type"] = req.session_type
    out["driver_number"] = req.driver_number
    return out


@app.get("/api/strategy/actual/{meeting_key}")
def get_strategy_actual(meeting_key: int, session_type: str = Query("Race", description="Race or Sprint")):
    """
    Fetch actual race/sprint results and strategies for comparison with predictions.

    Returns actual finish positions and stint data when the session is completed.
    """
    try:
        sessions = _openf1("sessions", {"meeting_key": meeting_key})
    except Exception:
        sessions = []

    target = _select_race_or_sprint_session(sessions, session_type == "Sprint")

    if not target:
        return {"available": False, "session_key": None, "drivers": []}

    sk = target["session_key"]
    try:
        results = _openf1("session_result", {"session_key": sk})
    except Exception:
        results = []

    if not results or not isinstance(results, list):
        return {"available": False, "session_key": sk, "drivers": []}
    try:
        raw_stints = _openf1("stints", {"session_key": sk})
    except Exception:
        raw_stints = []

    driver_map = {}
    try:
        drivers = _openf1("drivers", {"session_key": sk})
        driver_map = {d["driver_number"]: d for d in drivers}
    except Exception:
        pass

    stints_by_driver = {}
    for s in raw_stints:
        dn = s["driver_number"]
        if dn not in stints_by_driver:
            stints_by_driver[dn] = []
        stints_by_driver[dn].append({
            "stint_number": s.get("stint_number", 0),
            "compound": (s.get("compound") or "UNKNOWN").upper(),
            "lap_start": s["lap_start"],
            "lap_end": s["lap_end"],
            "tyre_age_at_start": s.get("tyre_age_at_start", 0),
        })
    for dn in list(stints_by_driver.keys()):
        norm = _normalize_openf1_driver_stints(stints_by_driver[dn])
        stints_by_driver[dn] = [{
            "compound": (x.get("compound") or "UNKNOWN").upper(),
            "laps": x["laps"],
            "lap_start": x["lap_start"],
            "lap_end": x["lap_end"],
        } for x in norm]

    drivers_out = []
    for r in sorted(results, key=lambda x: x.get("position") or 99):
        dn = r["driver_number"]
        d = driver_map.get(dn, {})
        stints = stints_by_driver.get(dn, [])
        drivers_out.append({
            "driver_number": dn,
            "driver": d.get("full_name", f"Driver {dn}"),
            "position": r.get("position", 99),
            "stints": stints,
            "n_stops": max(0, len(stints) - 1),
        })

    return {
        "available": True,
        "session_key": sk,
        "session_name": target.get("session_name", session_type),
        "drivers": drivers_out,
    }


@app.get("/api/strategy/tyre-allocation/{meeting_key}")
def get_tyre_allocation(meeting_key: int):
    """Get tyre sets used/remaining per driver for a meeting."""
    try:
        sessions = _openf1("sessions", {"meeting_key": meeting_key})
    except Exception:
        sessions = []
    is_sprint = any(s.get("session_type") == "Sprint" for s in sessions)
    alloc = _compute_tyre_allocation(meeting_key, sessions, is_sprint)

    driver_map = {}
    for s in sessions:
        try:
            drivers = _openf1("drivers", {"session_key": s["session_key"]})
            for d in drivers:
                driver_map[d["driver_number"]] = d
            if driver_map:
                break
        except Exception:
            pass

    result = {}
    for dn, compounds in alloc.items():
        name = driver_map.get(dn, {}).get("full_name", f"Driver {dn}")
        result[str(dn)] = {
            "driver": name,
            "driver_number": dn,
            "compounds": compounds,
        }
    return {"meeting_key": meeting_key, "is_sprint": is_sprint, "drivers": result}


class UndercutRequest(BaseModel):
    meeting_key: int
    circuit: str = "Australia"
    driver_ahead: str
    driver_behind: str
    current_gap: float
    current_lap: int
    compound_ahead: str = "MEDIUM"
    compound_behind: str = "MEDIUM"
    stint_age_ahead: int = 10
    stint_age_behind: int = 10
    target_compound: str = "HARD"


@app.post("/api/strategy/undercut")
def strategy_undercut(req: UndercutRequest):
    """Analyze undercut/overcut/stay-out scenarios between two drivers."""
    try:
        sessions = _openf1("sessions", {"meeting_key": req.meeting_key})
    except Exception:
        sessions = []

    driver_map = {}
    for s in sessions:
        try:
            drivers = _openf1("drivers", {"session_key": s["session_key"]})
            for d in drivers:
                driver_map[d["driver_number"]] = d
            if driver_map:
                break
        except Exception:
            pass

    data_sources = _fetch_degradation_data(sessions, driver_map)

    deg_model = se.TyreDegModel()
    drivers_list = [{"driver_number": dn, "full_name": d.get("full_name", ""),
                     "team_name": d.get("team_name", "")}
                    for dn, d in driver_map.items()]
    for stints, laps in data_sources:
        deg_model.fit(stints, laps, drivers_list)

    calc = se.UndercutCalculator(deg_model, req.circuit)
    return calc.analyze(
        driver_ahead=req.driver_ahead,
        driver_behind=req.driver_behind,
        current_gap=req.current_gap,
        current_lap=req.current_lap,
        compound_ahead=req.compound_ahead,
        compound_behind=req.compound_behind,
        stint_age_ahead=req.stint_age_ahead,
        stint_age_behind=req.stint_age_behind,
        target_compound=req.target_compound,
    )


@app.get("/api/strategy/deg-model/{meeting_key}")
def strategy_deg_model(meeting_key: int):
    """Return fitted tyre degradation curves from practice data."""
    try:
        sessions = _openf1("sessions", {"meeting_key": meeting_key})
    except Exception:
        sessions = []

    driver_map = {}
    for s in sessions:
        try:
            drivers = _openf1("drivers", {"session_key": s["session_key"]})
            for d in drivers:
                driver_map[d["driver_number"]] = d
            if driver_map:
                break
        except Exception:
            pass

    data_sources = _fetch_degradation_data(sessions, driver_map)

    deg_model = se.TyreDegModel()
    drivers_list = [{"driver_number": dn, "full_name": d.get("full_name", ""),
                     "team_name": d.get("team_name", "")}
                    for dn, d in driver_map.items()]
    for stints, laps in data_sources:
        deg_model.fit(stints, laps, drivers_list)

    return {
        "meeting_key": meeting_key,
        "curves": deg_model.to_dict(),
        "driver_base_pace": {k: round(v, 3) for k, v in deg_model.driver_base_pace.items()},
    }


# ─── STRATEGY CHAT (LLM + RAG) ──────────────────────────────────────────────

class StrategyChatRequest(BaseModel):
    meeting_key: int
    circuit: str = "Australia"
    message: str
    simulation_context: Optional[dict] = None
    conversation_history: Optional[list] = None
    driver_focus: Optional[str] = None


@app.post("/api/strategy/chat")
def strategy_chat(req: StrategyChatRequest):
    """Chat with APEX strategy assistant (Claude + RAG)."""
    rag = get_rag()
    llm = get_llm()

    rag_context = rag.query(
        req.message, n=5, circuit_filter=req.circuit if req.circuit else None)

    response = llm.chat(
        user_message=req.message,
        simulation_context=req.simulation_context,
        rag_context=rag_context,
        conversation_history=req.conversation_history or [],
    )

    return {
        "response": response,
        "rag_context_used": len(rag_context),
        "llm_available": llm.available,
    }


class StrategyNarrateRequest(BaseModel):
    meeting_key: int
    circuit: str = "Australia"
    simulation_result: dict
    driver_focus: Optional[str] = None


@app.post("/api/strategy/narrate")
def strategy_narrate(req: StrategyNarrateRequest):
    """Generate strategy narration from simulation results."""
    rag = get_rag()
    llm = get_llm()

    circuit_query = f"tyre strategy {req.circuit} race"
    rag_context = rag.query(circuit_query, n=5, circuit_filter=req.circuit)

    narration = llm.narrate_strategy(
        simulation_result=req.simulation_result,
        rag_context=rag_context,
        driver_focus=req.driver_focus,
    )

    return {
        "narration": narration,
        "rag_context_used": len(rag_context),
        "llm_available": llm.available,
    }


@app.get("/api/strategy/rag-stats")
def strategy_rag_stats():
    """Get RAG knowledge base statistics."""
    rag = get_rag()
    return rag.get_stats()


# ─── LOCATION (raw track outline) ────────────────────────────────────────────

@app.get("/api/track/{session_key}/{driver_number}")
def get_track_outline(session_key: int, driver_number: int):
    """
    Fetch one lap's worth of location data to build a track outline.
    Uses the first lap's data.
    """
    try:
        laps_data = _openf1("laps", {
            "session_key": session_key,
            "driver_number": driver_number,
        })
        valid_laps = [l for l in laps_data
                      if l.get("lap_duration") and l["lap_duration"] > 0
                      and not l.get("is_pit_out_lap")]
        if not valid_laps:
            return {"x": [], "y": [], "n_points": 0}

        target = valid_laps[0]
        lap_start = target.get("date_start")
        if not lap_start:
            return {"x": [], "y": [], "n_points": 0}

        from datetime import timedelta
        start_dt = datetime.fromisoformat(lap_start)
        end_dt = start_dt + timedelta(seconds=target.get("lap_duration", 90) + 1)

        location = _openf1("location", {
            "session_key": session_key,
            "driver_number": driver_number,
            "date>": lap_start,
            "date<": end_dt.isoformat(),
        })

        if not location:
            return {"x": [], "y": [], "n_points": 0}

        x_raw = [d["x"] for d in location]
        y_raw = [d["y"] for d in location]

        # Normalize
        x_min, x_max = min(x_raw), max(x_raw)
        y_min, y_max = min(y_raw), max(y_raw)
        x_range = x_max - x_min or 1
        y_range = y_max - y_min or 1

        return {
            "x": [round((v - x_min) / x_range, 4) for v in x_raw],
            "y": [round((v - y_min) / y_range, 4) for v in y_raw],
            "n_points": len(x_raw),
        }
    except Exception as e:
        raise HTTPException(502, f"Track outline fetch failed: {e}")
