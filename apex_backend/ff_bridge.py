"""
FastF1 fallback when OpenF1 returns no usable data.
Resolves session_key via OpenF1 `sessions?session_key=` (metadata only), then loads
the same weekend/session from FastF1 and returns shapes compatible with APEX endpoints.
"""

from __future__ import annotations

import os
import re
import warnings
from typing import Any, Optional

# Re-use cache dir from f1_loader
CACHE_DIR = os.path.join(os.path.dirname(__file__), "f1_cache")

try:
    import fastf1
    import numpy as np

    FASTF1_AVAILABLE = True
except ImportError:
    FASTF1_AVAILABLE = False
    fastf1 = None  # type: ignore
    np = None  # type: ignore


def _is_nan_val(val) -> bool:
    if val is None:
        return True
    if np is not None:
        try:
            return bool(np.isnan(val))
        except Exception:
            pass
    return False


def _setup_cache():
    if not FASTF1_AVAILABLE:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    fastf1.Cache.enable_cache(CACHE_DIR)


# session_key -> FastF1 context when OpenF1 has no session list (synthetic keys from schedule)
_SYNTHETIC_SESSION_CTX: dict[int, dict] = {}


def register_synthetic_session(session_key: int, ctx: dict) -> None:
    _SYNTHETIC_SESSION_CTX[int(session_key)] = dict(ctx)


def clear_synthetic_sessions() -> None:
    _SYNTHETIC_SESSION_CTX.clear()


def _openf1_sessions_meta(session_key: int, fetcher) -> Optional[dict]:
    """fetcher: callable(endpoint, params) -> list"""
    try:
        rows = fetcher("sessions", {"session_key": session_key})
    except Exception:
        rows = []
    if not rows or not isinstance(rows, list):
        return None
    s = rows[0]
    if not isinstance(s, dict):
        return None
    return s


def _meeting_year(meeting_key: int, year_hint: Optional[int], fetcher) -> Optional[int]:
    if year_hint:
        return int(year_hint)
    for yr in (2026, 2025, 2024, 2023):
        try:
            meetings = fetcher("meetings", {"year": yr})
        except Exception:
            meetings = []
        if not isinstance(meetings, list):
            continue
        for m in meetings:
            if m.get("meeting_key") == meeting_key:
                return yr
    return None


def meeting_key_to_gp(year: int, meeting_key: int, fetcher) -> Optional[Any]:
    """
    Map OpenF1 meeting_key to a FastF1 `gp` argument (round int or event name string).
    """
    if not FASTF1_AVAILABLE:
        return None
    try:
        meetings = fetcher("meetings", {"year": year})
    except Exception:
        meetings = []
    if not isinstance(meetings, list):
        return None
    target = next((m for m in meetings if m.get("meeting_key") == meeting_key), None)
    if not target:
        return None
    tname = (target.get("meeting_name") or "").lower()
    tcirc = (target.get("circuit_short_name") or "").lower()
    _setup_cache()
    try:
        schedule = fastf1.get_event_schedule(year)
    except Exception:
        return None
    if schedule is None or schedule.empty:
        return None

    best_rn = None
    for _, row in schedule.iterrows():
        try:
            rn = int(row["RoundNumber"])
        except (TypeError, ValueError, KeyError):
            continue
        en = str(row.get("EventName", "")).lower()
        loc = str(row.get("Location", "")).lower()
        country = str(row.get("Country", "")).lower()
        if tcirc and (tcirc in loc or tcirc in country or tcirc in en):
            return rn
        # Loose name match: significant tokens from meeting name
        tokens = [t for t in re.split(r"[^a-z0-9]+", tname) if len(t) > 4]
        if tokens and any(t in en for t in tokens[:4]):
            best_rn = rn
    if best_rn is not None:
        return best_rn
    # Last resort: official meeting name (FastF1 accepts some full names)
    return target.get("meeting_name") or target.get("circuit_short_name")


def openf1_session_to_ff_identifier(session_name: str, session_type: str) -> Optional[str]:
    """Map OpenF1 session_name / session_type to FastF1 session identifier."""
    n = (session_name or "").strip().lower()
    st = (session_type or "").strip()

    if "shootout" in n:
        return "SQ"
    if "sprint qualifying" in n or n == "sprint shootout":
        return "SQ"
    if n == "sprint" or (st == "Race" and "sprint" in n and "qualifying" not in n):
        return "S"
    if "practice 1" in n or n in ("fp1", "first practice"):
        return "FP1"
    if "practice 2" in n or n == "fp2":
        return "FP2"
    if "practice 3" in n or n == "fp3":
        return "FP3"
    if "qualifying" in n and "sprint" not in n:
        return "Q"
    if n == "race" or (st == "Race" and "sprint" not in n):
        return "R"
    if st == "Practice":
        if "2" in n:
            return "FP2"
        if "3" in n:
            return "FP3"
        return "FP1"
    if st == "Qualifying":
        return "SQ" if "sprint" in n else "Q"
    return None


def resolve_fastf1_context(session_key: int, fetcher) -> Optional[dict]:
    """
    Returns dict: year, gp, ff_session, meeting_key, session_name, session_type
    or None if FastF1 cannot be targeted.
    """
    if not FASTF1_AVAILABLE:
        return None
    # Synthetic session keys created from FastF1 schedule should resolve directly.
    synthetic = _SYNTHETIC_SESSION_CTX.get(int(session_key))
    if synthetic:
        return dict(synthetic)

    meta = _openf1_sessions_meta(session_key, fetcher)
    if not meta:
        return None
    meeting_key = meta.get("meeting_key")
    year = meta.get("year")
    if meeting_key is None:
        return None
    year = _meeting_year(int(meeting_key), int(year) if year is not None else None, fetcher)
    if not year:
        return None
    gp = meeting_key_to_gp(year, int(meeting_key), fetcher)
    if gp is None:
        return None
    ff_id = openf1_session_to_ff_identifier(
        str(meta.get("session_name", "")),
        str(meta.get("session_type", "")),
    )
    if not ff_id:
        return None
    return {
        "year": year,
        "gp": gp,
        "ff_session": ff_id,
        "meeting_key": int(meeting_key),
        "session_name": meta.get("session_name", ""),
        "session_type": meta.get("session_type", ""),
    }


def _load_ff_session(ctx: dict):
    _setup_cache()
    return fastf1.get_session(ctx["year"], ctx["gp"], ctx["ff_session"])


def drivers_from_fastf1(session_key: int, fetcher) -> list[dict]:
    ctx = resolve_fastf1_context(session_key, fetcher)
    if not ctx:
        return []
    try:
        sess = _load_ff_session(ctx)
        sess.load(telemetry=False, weather=False, messages=False)
        res = sess.results
        if res is None or res.empty:
            return []
        out = []
        for _, row in res.iterrows():
            try:
                dn = int(row["DriverNumber"])
            except (TypeError, ValueError, KeyError):
                continue
            abb = str(row.get("Abbreviation", "") or "")
            full = str(row.get("FullName", "") or "")
            team = str(row.get("TeamName", "") or "")
            tc = str(row.get("TeamColor", "") or "").lstrip("#")
            parts = full.split(None, 1)
            fn = parts[0] if parts else ""
            ln = parts[1] if len(parts) > 1 else ""
            out.append({
                "driver_number": dn,
                "full_name": full,
                "name_acronym": abb,
                "first_name": fn,
                "last_name": ln,
                "team_name": team,
                "team_colour": tc or "5a5a80",
                "headshot_url": "",
                "broadcast_name": full,
            })
        return out
    except Exception as e:
        warnings.warn(f"FastF1 drivers fallback failed: {e}")
        return []


def _lap_time_seconds(val) -> Optional[float]:
    if val is None:
        return None
    try:
        if hasattr(val, "total_seconds"):
            return float(val.total_seconds())
    except Exception:
        pass
    try:
        if val is not None and not (isinstance(val, float) and np is not None and np.isnan(val)):
            return float(val)
    except Exception:
        pass
    return None


def laps_from_fastf1(session_key: int, driver_number: int, fetcher) -> list[dict]:
    ctx = resolve_fastf1_context(session_key, fetcher)
    if not ctx:
        return []
    try:
        sess = _load_ff_session(ctx)
        sess.load(telemetry=False, weather=False, messages=False)
        laps = sess.laps
        if laps is None or laps.empty:
            return []
        # Resolve driver abbreviation from number
        abbr = None
        res = sess.results
        if res is not None and not res.empty:
            for _, row in res.iterrows():
                try:
                    if int(row["DriverNumber"]) == int(driver_number):
                        abbr = row.get("Abbreviation")
                        break
                except Exception:
                    continue
        if not abbr:
            return []
        dl = laps[laps["Driver"] == abbr]
        if dl.empty:
            return []
        out = []
        for _, lap in dl.iterrows():
            lap_num = int(lap["LapNumber"])
            dur = _lap_time_seconds(lap.get("LapTime"))
            s1 = _lap_time_seconds(lap.get("Sector1Time"))
            s2 = _lap_time_seconds(lap.get("Sector2Time"))
            s3 = _lap_time_seconds(lap.get("Sector3Time"))
            pit_out = bool(lap.get("PitOutTime") is not None and lap.get("PitInTime") is None)
            out.append({
                "lap_number": lap_num,
                "lap_duration": dur,
                "s1": s1,
                "s2": s2,
                "s3": s3,
                "i1_speed": None,
                "i2_speed": None,
                "st_speed": float(lap["SpeedST"]) if lap.get("SpeedST") is not None else None,
                "is_pit_out": pit_out,
            })
        return out
    except Exception as e:
        warnings.warn(f"FastF1 laps fallback failed: {e}")
        return []


def stints_from_fastf1(session_key: int, fetcher, driver_number: Optional[int] = None) -> list[dict]:
    """
    Raw stint rows (OpenF1-shaped) for all drivers or one driver.
    """
    ctx = resolve_fastf1_context(session_key, fetcher)
    if not ctx:
        return []
    try:
        import f1_loader as fl

        if not getattr(fl, "FASTF1_AVAILABLE", False):
            return []
        by_name = fl.fetch_stints(ctx["year"], ctx["gp"], ctx["ff_session"])
        if not by_name:
            return []

        sess = _load_ff_session(ctx)
        sess.load(telemetry=False, weather=False, messages=False)
        res = sess.results
        name_to_num: dict[str, int] = {}
        if res is not None and not res.empty:
            for _, row in res.iterrows():
                try:
                    name_to_num[str(row.get("FullName", ""))] = int(row["DriverNumber"])
                except Exception:
                    continue

        raw_stints: list[dict] = []
        for full_name, stint_list in by_name.items():
            dn = name_to_num.get(full_name)
            if dn is None:
                continue
            if driver_number is not None and int(dn) != int(driver_number):
                continue
            for i, st in enumerate(stint_list, 1):
                raw_stints.append({
                    "driver_number": dn,
                    "stint_number": i,
                    "compound": (st.get("compound") or "UNKNOWN").upper(),
                    "lap_start": int(st["start_lap"]),
                    "lap_end": int(st["end_lap"]),
                    "tyre_age_at_start": 0,
                })
        return raw_stints
    except Exception as e:
        warnings.warn(f"FastF1 stints fallback failed: {e}")
        return []


def session_result_from_fastf1(session_key: int, fetcher) -> list[dict]:
    ctx = resolve_fastf1_context(session_key, fetcher)
    if not ctx:
        return []
    try:
        sess = _load_ff_session(ctx)
        sess.load(telemetry=False, weather=False, messages=False)
        res = sess.results
        if res is None or res.empty:
            return []
        out = []
        for _, row in res.iterrows():
            try:
                pos = int(row["Position"]) if row.get("Position") == row.get("Position") else None
            except Exception:
                pos = None
            try:
                dn = int(row["DriverNumber"])
            except Exception:
                continue
            out.append({
                "position": pos if pos is not None else 99,
                "driver_number": dn,
                "points": float(row.get("Points", 0) or 0),
                "status": str(row.get("Status", "")),
            })
        out.sort(key=lambda x: (x.get("position") or 99))
        return out
    except Exception as e:
        warnings.warn(f"FastF1 session_result fallback failed: {e}")
        return []


def telemetry_from_fastf1(session_key: int, driver_number: int, lap: Optional[int], fetcher) -> Optional[dict]:
    """Returns APEX /api/telemetry-shaped dict or None."""
    if not FASTF1_AVAILABLE:
        return None
    ctx = resolve_fastf1_context(session_key, fetcher)
    if not ctx:
        return None
    try:
        import f1_loader as fl

        if not getattr(fl, "FASTF1_AVAILABLE", False):
            return None
        sess = _load_ff_session(ctx)
        sess.load(telemetry=False, weather=False, messages=False)
        res = sess.results
        abbr = None
        if res is not None and not res.empty:
            for _, row in res.iterrows():
                try:
                    if int(row["DriverNumber"]) == int(driver_number):
                        abbr = str(row.get("Abbreviation", ""))
                        break
                except Exception:
                    continue
        if not abbr:
            return None
        ft = fl.fetch_telemetry(ctx["year"], ctx["gp"], abbr, ctx["ff_session"], lap_number=lap)
        if not ft or not ft.get("n_points"):
            return None
        xs = ft.get("x") or []
        ys = ft.get("y") or []
        return {
            "driver_number": driver_number,
            "lap": ft.get("lap"),
            "lap_time": ft.get("lap_time"),
            "n_points": ft.get("n_points", 0),
            "speed": ft.get("speed", []),
            "throttle": ft.get("throttle", []),
            "brake": ft.get("brake", []),
            "gear": ft.get("gear", []),
            "drs": ft.get("drs", []),
            "x": xs,
            "y": ys,
            "x_raw": xs,
            "y_raw": ys,
            "timestamps": [""] * len(xs),
            "sectors": {"s1": None, "s2": None, "s3": None},
        }
    except Exception as e:
        warnings.warn(f"FastF1 telemetry fallback failed: {e}")
        return None


def sessions_from_fastf1_meeting(meeting_key: int, fetcher) -> list[dict]:
    """
    Build pseudo session list from FastF1 schedule when OpenF1 returns no sessions.
    Uses synthetic positive session_keys in a reserved range to avoid OpenF1 collisions.
    """
    if not FASTF1_AVAILABLE:
        return []
    year = _meeting_year(meeting_key, None, fetcher)
    if not year:
        return []
    gp = meeting_key_to_gp(year, meeting_key, fetcher)
    if gp is None:
        return []
    _setup_cache()
    try:
        schedule = fastf1.get_event_schedule(year)
    except Exception:
        return []
    row = None
    for _, r in schedule.iterrows():
        try:
            if int(r["RoundNumber"]) == int(gp):
                row = r
                break
        except Exception:
            continue
    if row is None and isinstance(gp, str):
        for _, r in schedule.iterrows():
            if gp.lower() in str(r.get("EventName", "")).lower():
                row = r
                break
    if row is None:
        return []

    # Session columns Session1..Session5 with parallel Date columns
    base = 8_000_000_000 + int(meeting_key) * 100
    sessions_out = []
    slot = 0
    for i in range(1, 6):
        sname = row.get(f"Session{i}")
        sdate = row.get(f"Session{i}Date")
        if sname is None or (isinstance(sname, float) and _is_nan_val(sname)):
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
        elif nl == "sprint" or (nl == "race" and "sprint" in str(row.get("EventFormat", "")).lower()):
            stype = "Race"
        elif nl == "race":
            stype = "Race"
        ff_id = openf1_session_to_ff_identifier(name, stype)
        if not ff_id:
            continue
        try:
            rn = int(row["RoundNumber"])
        except Exception:
            rn = gp
        register_synthetic_session(sk, {
            "year": year,
            "gp": rn,
            "ff_session": ff_id,
            "meeting_key": meeting_key,
            "session_name": name,
            "session_type": stype,
        })
        ds = ""
        if sdate is not None and not (isinstance(sdate, float) and _is_nan_val(sdate)):
            try:
                ds = sdate.isoformat() if hasattr(sdate, "isoformat") else str(sdate)
            except Exception:
                ds = str(sdate)
        if not ds:
            ds = f"{year}-01-01T00:00:00+00:00"
        sessions_out.append({
            "session_key": sk,
            "session_name": name,
            "session_type": stype,
            "date_start": ds,
            "date_end": ds,
            "status": "upcoming",
            "data_source": "fastf1",
        })
    return sessions_out
