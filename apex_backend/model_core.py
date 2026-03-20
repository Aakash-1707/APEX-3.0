"""
APEX Model Core — v4 (2026 Regulation-Aware)
=============================================
Fully decoupled from hardcoded data.
Accepts FastF1-loaded data as input, runs the same logic as predictv3.py.

Pipeline:
  raw FastF1 data
    → build_grid_input()       normalise FastF1 → model-ready dicts
    → compute_features_v4()    10 features per driver
    → compute_raw_score()      weighted sum (with team priors + season adjustments)
    → softmax_scores()         probability distribution
    → run_monte_carlo_v4()     100k race simulations
    → predictions JSON         returned to API / frontend
"""

import json
import os
import numpy as np
from collections import defaultdict
from typing import Optional


# ─── 2026 REGULATION CONSTANTS ────────────────────────────────────────────────
# These are model parameters, not data — they belong here permanently.

POLE_WIN_RATE_2026  = 0.45   # down from 0.60 — active aero makes overtaking easier
OVERTAKE_FACTOR     = 1.4    # 40% more position changes than old regs
ENERGY_UNCERTAINTY  = 0.04   # first race with new PUs
SOFTMAX_TEMP        = 0.10   # slightly cooler than v3 → fewer extreme long-shots
LAP1_INCIDENT_PROB  = 0.35   # 22-car grid + new start procedure
SC_PROB             = 0.55   # Albert Park historical (~circuit-specific, overridable)
VSC_PROB            = 0.25
RAIN_PROB           = 0.15

NEW_TEAM_UNCERTAINTY = {"Cadillac": 0.06, "Audi": 0.04}

DNF_RATES = {
    "default":     0.08,
    "Cadillac":    0.12,
    "Audi":        0.12,
    "Aston Martin":0.10,
    "Red Bull":    0.09,
}

START_PROCEDURE_ADVANTAGE = {
    "Ferrari":     0.3,
    "Mercedes":    0.0,
    "McLaren":     0.0,
    "Red Bull":   -0.1,
    "Racing Bulls":0.0,
    "Audi":       -0.1,
    "Haas":        0.0,
    "Alpine":      0.0,
    "Williams":   -0.1,
    "Aston Martin":-0.2,
    "Cadillac":   -0.2,
}

# Energy management readiness — updated each race as reliability data accrues
ENERGY_READINESS = {
    "Mercedes":    0.90,
    "Ferrari":     0.85,
    "McLaren":     0.80,
    "Red Bull":    0.75,
    "Racing Bulls":0.65,
    "Haas":        0.60,
    "Alpine":      0.55,
    "Audi":        0.50,
    "Williams":    0.50,
    "Aston Martin":0.40,
    "Cadillac":    0.35,
}

WEIGHTS_V4 = {
    "quali_pace":       0.25,
    "race_pace":        0.15,
    "grid_win_rate":    0.08,
    "practice_trend":   0.06,
    "teammate_gap":     0.08,
    "quali_extraction": 0.07,
    "adaptability":     0.06,
    "start_score":      0.05,
    "reliability":      0.07,
    "energy_score":     0.08,
}
# Normalise to exactly 1.0
_total = sum(WEIGHTS_V4.values())
WEIGHTS_V4 = {k: round(v / _total, 6) for k, v in WEIGHTS_V4.items()}


# ─── TEAM TIER PRIORS + SEASON ADJUSTMENTS ───────────────────────────────────

TEAM_TIER_PRIOR = {
    "Mercedes": 0.20,
    "Ferrari": 0.16,
    "McLaren": 0.14,
    "Red Bull Racing": 0.10,
    "Aston Martin": 0.00,
    "Alpine": -0.05,
    "Williams": -0.08,
    "Racing Bulls": -0.10,
    "Haas F1 Team": -0.12,
    "Kick Sauber": -0.20,
    "Audi": -0.26,
    "Cadillac": -0.30,
}

TEAM_TIER_ADJUST: dict[str, float] = {}
_adjust_path = os.path.join(os.path.dirname(__file__), "team_adjustments_2026.json")
try:
    if os.path.exists(_adjust_path):
        with open(_adjust_path) as f:
            data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    try:
                        TEAM_TIER_ADJUST[k] = float(v)
                    except (TypeError, ValueError):
                        continue
except Exception:
    TEAM_TIER_ADJUST = {}


def get_team_tier_boost(team: str) -> float:
    """
    Base team tier prior + optional 2026 season adjustment.

    TEAM_TIER_PRIOR encodes pre-season expectations.
    TEAM_TIER_ADJUST (from team_adjustments_2026.json) lets you nudge teams up/down
    as the season unfolds based on real results.
    """
    base = TEAM_TIER_PRIOR.get(team, -0.10)
    return base + TEAM_TIER_ADJUST.get(team, 0.0)


# ─── DRIVER EXPERIENCE TABLE ──────────────────────────────────────────────────
# This is static biographical data (seasons, poles) — it doesn't come from
# FastF1 per-weekend, so it lives here. Updated manually each season.

DRIVER_EXPERIENCE = {
    "George Russell":    {"f1_seasons": 7,  "career_poles": 5},
    "Kimi Antonelli":    {"f1_seasons": 1,  "career_poles": 0},
    "Isack Hadjar":      {"f1_seasons": 0,  "career_poles": 0},
    "Charles Leclerc":   {"f1_seasons": 7,  "career_poles": 26},
    "Oscar Piastri":     {"f1_seasons": 3,  "career_poles": 2},
    "Lando Norris":      {"f1_seasons": 6,  "career_poles": 8},
    "Lewis Hamilton":    {"f1_seasons": 18, "career_poles": 104},
    "Liam Lawson":       {"f1_seasons": 1,  "career_poles": 0},
    "Arvid Lindblad":    {"f1_seasons": 0,  "career_poles": 0},
    "Gabriel Bortoleto": {"f1_seasons": 0,  "career_poles": 0},
    "Nico Hulkenberg":   {"f1_seasons": 14, "career_poles": 1},
    "Oliver Bearman":    {"f1_seasons": 1,  "career_poles": 0},
    "Esteban Ocon":      {"f1_seasons": 8,  "career_poles": 0},
    "Pierre Gasly":      {"f1_seasons": 8,  "career_poles": 0},
    "Alex Albon":        {"f1_seasons": 5,  "career_poles": 0},
    "Franco Colapinto":  {"f1_seasons": 1,  "career_poles": 0},
    "Fernando Alonso":   {"f1_seasons": 22, "career_poles": 22},
    "Sergio Perez":      {"f1_seasons": 14, "career_poles": 3},
    "Valtteri Bottas":   {"f1_seasons": 13, "career_poles": 20},
    "Max Verstappen":    {"f1_seasons": 10, "career_poles": 40},
    "Carlos Sainz":      {"f1_seasons": 10, "career_poles": 6},
    "Lance Stroll":      {"f1_seasons": 8,  "career_poles": 1},
}

# ─── TYRE MODEL ───────────────────────────────────────────────────────────────
# 2026 regulations: wider tyres, different compounds, estimated deg rates
# base_lap = seconds added to a driver's raw pace; deg = extra seconds per lap on used tyres

TYRE_COMPOUNDS = {
    "SOFT":   {"base_delta": 0.0,  "deg_per_lap": 0.065, "cliff_lap": 20},
    "MEDIUM": {"base_delta": 0.55, "deg_per_lap": 0.038, "cliff_lap": 30},
    "HARD":   {"base_delta": 1.10, "deg_per_lap": 0.022, "cliff_lap": 42},
}

# Overtaking difficulty: 0 = easy (Monza), 1 = impossible (Monaco)
# Affects how much tyre delta is needed to pass

# Circuit-specific overrides
CIRCUIT_PARAMS = {
    "Australia":     {"sc_prob": 0.55, "vsc_prob": 0.25, "rain_prob": 0.15, "pole_win_rate": 0.45, "race_laps": 58, "pit_loss": 22.0, "overtake_difficulty": 0.55},
    "China":         {"sc_prob": 0.50, "vsc_prob": 0.22, "rain_prob": 0.10, "pole_win_rate": 0.48, "race_laps": 56, "pit_loss": 22.0, "overtake_difficulty": 0.40},
    "Japan":         {"sc_prob": 0.40, "vsc_prob": 0.20, "rain_prob": 0.20, "pole_win_rate": 0.52, "race_laps": 53, "pit_loss": 20.0, "overtake_difficulty": 0.60},
    "Bahrain":       {"sc_prob": 0.30, "vsc_prob": 0.18, "rain_prob": 0.02, "pole_win_rate": 0.50, "race_laps": 57, "pit_loss": 21.0, "overtake_difficulty": 0.35},
    "Saudi Arabia":  {"sc_prob": 0.65, "vsc_prob": 0.30, "rain_prob": 0.01, "pole_win_rate": 0.42, "race_laps": 50, "pit_loss": 21.0, "overtake_difficulty": 0.50},
    "Miami":         {"sc_prob": 0.60, "vsc_prob": 0.28, "rain_prob": 0.25, "pole_win_rate": 0.43, "race_laps": 57, "pit_loss": 23.0, "overtake_difficulty": 0.45},
    "Emilia Romagna":{"sc_prob": 0.45, "vsc_prob": 0.22, "rain_prob": 0.25, "pole_win_rate": 0.55, "race_laps": 63, "pit_loss": 22.0, "overtake_difficulty": 0.55},
    "Monaco":        {"sc_prob": 0.70, "vsc_prob": 0.35, "rain_prob": 0.18, "pole_win_rate": 0.75, "race_laps": 78, "pit_loss": 20.0, "overtake_difficulty": 0.95},
    "Spain":         {"sc_prob": 0.35, "vsc_prob": 0.20, "rain_prob": 0.08, "pole_win_rate": 0.52, "race_laps": 66, "pit_loss": 21.0, "overtake_difficulty": 0.50},
    "Canada":        {"sc_prob": 0.60, "vsc_prob": 0.28, "rain_prob": 0.30, "pole_win_rate": 0.44, "race_laps": 70, "pit_loss": 20.0, "overtake_difficulty": 0.40},
    "Austria":       {"sc_prob": 0.45, "vsc_prob": 0.22, "rain_prob": 0.30, "pole_win_rate": 0.50, "race_laps": 71, "pit_loss": 19.0, "overtake_difficulty": 0.35},
    "Britain":       {"sc_prob": 0.50, "vsc_prob": 0.25, "rain_prob": 0.35, "pole_win_rate": 0.48, "race_laps": 52, "pit_loss": 21.0, "overtake_difficulty": 0.45},
    "Belgium":       {"sc_prob": 0.55, "vsc_prob": 0.28, "rain_prob": 0.40, "pole_win_rate": 0.40, "race_laps": 44, "pit_loss": 22.0, "overtake_difficulty": 0.30},
    "Hungary":       {"sc_prob": 0.35, "vsc_prob": 0.20, "rain_prob": 0.15, "pole_win_rate": 0.65, "race_laps": 70, "pit_loss": 20.0, "overtake_difficulty": 0.75},
    "Netherlands":   {"sc_prob": 0.40, "vsc_prob": 0.22, "rain_prob": 0.25, "pole_win_rate": 0.60, "race_laps": 72, "pit_loss": 19.0, "overtake_difficulty": 0.70},
    "Italy":         {"sc_prob": 0.35, "vsc_prob": 0.18, "rain_prob": 0.12, "pole_win_rate": 0.38, "race_laps": 53, "pit_loss": 23.0, "overtake_difficulty": 0.25},
    "Azerbaijan":    {"sc_prob": 0.72, "vsc_prob": 0.35, "rain_prob": 0.05, "pole_win_rate": 0.38, "race_laps": 51, "pit_loss": 22.0, "overtake_difficulty": 0.35},
    "Singapore":     {"sc_prob": 0.68, "vsc_prob": 0.32, "rain_prob": 0.40, "pole_win_rate": 0.42, "race_laps": 62, "pit_loss": 22.0, "overtake_difficulty": 0.70},
    "United States": {"sc_prob": 0.55, "vsc_prob": 0.25, "rain_prob": 0.20, "pole_win_rate": 0.45, "race_laps": 56, "pit_loss": 21.0, "overtake_difficulty": 0.40},
    "Mexico":        {"sc_prob": 0.40, "vsc_prob": 0.20, "rain_prob": 0.10, "pole_win_rate": 0.52, "race_laps": 71, "pit_loss": 20.0, "overtake_difficulty": 0.45},
    "Brazil":        {"sc_prob": 0.55, "vsc_prob": 0.28, "rain_prob": 0.45, "pole_win_rate": 0.40, "race_laps": 71, "pit_loss": 21.0, "overtake_difficulty": 0.35},
    "Las Vegas":     {"sc_prob": 0.50, "vsc_prob": 0.25, "rain_prob": 0.05, "pole_win_rate": 0.42, "race_laps": 50, "pit_loss": 22.0, "overtake_difficulty": 0.30},
    "Qatar":         {"sc_prob": 0.35, "vsc_prob": 0.18, "rain_prob": 0.02, "pole_win_rate": 0.55, "race_laps": 57, "pit_loss": 21.0, "overtake_difficulty": 0.40},
    "Abu Dhabi":     {"sc_prob": 0.30, "vsc_prob": 0.15, "rain_prob": 0.01, "pole_win_rate": 0.58, "race_laps": 58, "pit_loss": 22.0, "overtake_difficulty": 0.45},
}

# ─── STRATEGY POOL (pre-computed per race distance) ──────────────────────────
_STRATEGY_CACHE: dict[int, list[tuple[float, list[tuple[str, int]]]]] = {}

def _build_strategy_pool(race_laps: int) -> list[tuple[float, list[tuple[str, int]]]]:
    """Build and score all viable 1-stop and 2-stop strategies for a given race length.
    Returns sorted list of (time_cost, strategy). Cached globally."""
    if race_laps in _STRATEGY_CACHE:
        return _STRATEGY_CACHE[race_laps]

    compounds = list(TYRE_COMPOUNDS.keys())
    min_stint = 8
    strategies = []

    for c1 in compounds:
        for c2 in compounds:
            if c1 == c2:
                continue
            for split_pct in range(20, 81, 5):
                s1 = max(min_stint, int(race_laps * split_pct / 100))
                s2 = race_laps - s1
                if s2 < min_stint:
                    continue
                strategies.append([(c1, s1), (c2, s2)])

    for c1 in compounds:
        for c2 in compounds:
            for c3 in compounds:
                if len({c1, c2, c3}) < 2:
                    continue
                for p1 in range(20, 50, 10):
                    for p2 in range(20, 50, 10):
                        s1 = max(min_stint, int(race_laps * p1 / 100))
                        s2 = max(min_stint, int(race_laps * p2 / 100))
                        s3 = race_laps - s1 - s2
                        if s3 < min_stint:
                            continue
                        strategies.append([(c1, s1), (c2, s2), (c3, s3)])

    scored = []
    for strat in strategies:
        total_time = 0.0
        n_stops = len(strat) - 1
        for compound, laps in strat:
            tc = TYRE_COMPOUNDS[compound]
            for lap_in_stint in range(laps):
                deg = tc["deg_per_lap"] * lap_in_stint
                if lap_in_stint > tc["cliff_lap"]:
                    deg += (lap_in_stint - tc["cliff_lap"]) * tc["deg_per_lap"] * 2.0
                total_time += tc["base_delta"] + deg
        total_time += n_stops * 22.0
        scored.append((total_time, strat))

    scored.sort(key=lambda x: x[0])
    top = scored[:20]
    _STRATEGY_CACHE[race_laps] = top
    return top


def _pick_strategy(race_laps: int, grid_pos: int, base_pace: float) -> list[tuple[str, int]]:
    """Pick a plausible strategy from the pre-computed pool."""
    pool = _build_strategy_pool(race_laps)
    if not pool:
        half = race_laps // 2
        return [("MEDIUM", half), ("HARD", race_laps - half)]

    if grid_pos <= 5:
        for _, s in pool[:8]:
            if len(s) <= 2:
                return s
    elif grid_pos >= 15:
        for _, s in pool[:12]:
            if len(s) >= 3:
                return s

    idx = np.random.randint(0, min(8, len(pool)))
    return pool[idx][1]


# ─── DATA NORMALISATION ───────────────────────────────────────────────────────

def build_grid_input(
    qualifying: list[dict],
    fp_times: dict,
    weekend_incidents: Optional[dict] = None,
) -> list[dict]:
    """
    Normalise FastF1-loaded data into the format expected by compute_features_v4.

    Args:
        qualifying: list of dicts from fastf1_loader.extract_qualifying_data()
                    keys: pos, driver, team, q_time (seconds or None)
        fp_times:   dict from fastf1_loader.extract_fp_actual_times()
                    keys: driver_name → {fp1: float, fp2: float, fp3: float}
        weekend_incidents: optional dict of driver_name → {"dnf_in_practice": bool,
                           "crash_in_quali": bool, "reliability_flag": bool}

    Returns:
        list of dicts ready for compute_features_v4()
    """
    incidents = weekend_incidents or {}

    # Fill any missing FP times with grid-position-based estimate
    fp3_best = min((v.get("fp3", 99) for v in fp_times.values()), default=80.0)
    fp_fallback_base = fp3_best + 3.0  # ~3s off pace = tail of grid

    enriched = []
    for entry in qualifying:
        name = entry["driver"]
        fp = fp_times.get(name, {
            "fp1": fp_fallback_base + 0.5,
            "fp2": fp_fallback_base + 0.3,
            "fp3": fp_fallback_base,
        })

        # Override reliability / extra context if weekend incidents reported
        inc = incidents.get(name, {})
        reliability_override = None
        if inc.get("crash_in_quali") or inc.get("dnf_in_practice"):
            reliability_override = 0.20
        elif inc.get("reliability_flag"):
            reliability_override = 0.60

        sprint_perf = inc.get("sprint_perf")

        enriched.append({
            "driver": name,
            "team":   entry["team"],
            "pos":    entry["pos"],
            "q_time": entry.get("q_time"),
            "fp":     fp,
            "reliability_override": reliability_override,
            "sprint_perf": sprint_perf,
            "driver_number": entry.get("driver_number"),
            "team_colour":   entry.get("team_colour"),
        })

    return enriched


# ─── FEATURE ENGINEERING ──────────────────────────────────────────────────────

def compute_features_v4(driver_entry: dict, all_entries: list[dict], circuit: str = "Australia") -> dict:
    """
    Compute 10 features for a single driver.
    Uses only 2026-weekend data except where physics transfers (experience, adaptability).

    Args:
        driver_entry: single driver dict from build_grid_input()
        all_entries:  full grid list (needed for teammate comparison, normalization)
        circuit:      circuit name for CIRCUIT_PARAMS lookup
    """
    name      = driver_entry["driver"]
    team      = driver_entry["team"]
    grid_pos  = driver_entry["pos"]
    q_time    = driver_entry.get("q_time")
    fp        = driver_entry["fp"]
    rel_override = driver_entry.get("reliability_override")
    sprint_perf = driver_entry.get("sprint_perf")

    exp = DRIVER_EXPERIENCE.get(name, {"f1_seasons": 0, "career_poles": 0})

    circuit_p = CIRCUIT_PARAMS.get(circuit, CIRCUIT_PARAMS["Australia"])
    pole_win_rate = circuit_p["pole_win_rate"]

    # Reference values from this grid
    pole_time = next((e["q_time"] for e in all_entries if e["pos"] == 1 and e.get("q_time")), None)
    fp3_times = [e["fp"].get("fp3", 99) for e in all_entries]
    fp2_times = [e["fp"].get("fp2", 99) for e in all_entries]
    fp3_best  = min(fp3_times) if fp3_times else 80.0
    fp2_best  = min(fp2_times) if fp2_times else 80.0

    # ── F1: Qualifying gap to pole ────────────────────────────────────────────
    if q_time is not None and pole_time is not None:
        q_gap = q_time - pole_time
        quali_pace = max(0.0, 1.0 - (q_gap / 3.5))
    else:
        best_fp = min(fp.get("fp1", 99), fp.get("fp2", 99), fp.get("fp3", 99))
        estimated_gap = best_fp - fp3_best
        quali_pace = max(0.0, 1.0 - (estimated_gap / 3.5)) * 0.4  # penalise no Q time

    # ── F2: Grid position win rate (2026-adjusted) ────────────────────────────
    if grid_pos == 1:
        grid_win_rate = pole_win_rate
    elif grid_pos <= 3:
        grid_win_rate = pole_win_rate * (0.35 / grid_pos)
    elif grid_pos <= 6:
        grid_win_rate = pole_win_rate * (0.12 / (grid_pos - 1))
    elif grid_pos <= 10:
        grid_win_rate = pole_win_rate * (0.03 / (grid_pos - 3))
    else:
        grid_win_rate = max(0.001, 0.01 * (1 - (grid_pos - 10) / 12))

    # ── F3: FP2 race pace ─────────────────────────────────────────────────────
    fp2_gap  = fp.get("fp2", fp2_best + 2) - fp2_best
    race_pace = max(0.0, 1.0 - (fp2_gap / 3.0))

    # Optional sprint race adjustment: if a completed Sprint exists, we pass in
    # a normalised sprint_perf ∈ [0,1] where >0.5 means the driver outperformed
    # their grid position in the Sprint. Blend this into race_pace so that
    # race prediction uses FP + sprint evidence, without overriding the grid.
    if sprint_perf is not None:
        try:
            sprint_val = float(sprint_perf)
            race_pace = float(np.clip(0.7 * race_pace + 0.3 * sprint_val, 0.0, 1.0))
        except (TypeError, ValueError):
            pass

    # ── F4: Practice improvement trend (FP1 → FP3) ───────────────────────────
    fp1_gap = fp.get("fp1", fp3_best + 3) - fp3_best
    fp3_gap = fp.get("fp3", fp3_best + 1) - fp3_best
    if fp1_gap > 0.1:
        improvement = 1.0 - (fp3_gap / fp1_gap)
        practice_trend = float(np.clip(improvement, 0, 1))
    else:
        practice_trend = 0.85

    # ── F5: Teammate qualifying delta ─────────────────────────────────────────
    teammate_times = [
        e["q_time"] for e in all_entries
        if e["team"] == team and e["driver"] != name and e.get("q_time") is not None
    ]
    if q_time is not None and teammate_times:
        delta = min(teammate_times) - q_time
        teammate_gap = float(np.clip((delta + 1.0) / 2.0, 0, 1))
    elif q_time is not None:
        teammate_gap = 0.75
    else:
        teammate_gap = 0.15

    # ── F6: Qualifying extraction (quali vs best practice) ────────────────────
    if q_time is not None:
        best_practice = min(fp.get("fp1", 99), fp.get("fp2", 99), fp.get("fp3", 99))
        extraction = best_practice - q_time
        quali_extraction = float(np.clip((extraction + 1.5) / 3.0, 0, 1))
    else:
        quali_extraction = 0.05

    # ── F7: Adaptability (reg-change survival history) ────────────────────────
    seasons = exp["f1_seasons"]
    reg_changes = 0
    if seasons >= 2:  reg_changes += 1
    if seasons >= 5:  reg_changes += 1
    if seasons >= 9:  reg_changes += 1
    if seasons >= 13: reg_changes += 1
    adaptability = min(1.0, reg_changes * 0.25)

    # ── F8: Start procedure advantage (2026) ──────────────────────────────────
    start_advantage = START_PROCEDURE_ADVANTAGE.get(team, 0.0)
    start_score = float(np.clip(0.5 + start_advantage, 0, 1))

    # ── F9: Reliability ───────────────────────────────────────────────────────
    if rel_override is not None:
        reliability = rel_override
    elif q_time is None:
        reliability = 0.20
    else:
        reliability = 1.0

    # ── F10: Energy management readiness ─────────────────────────────────────
    energy_score = ENERGY_READINESS.get(team, 0.40)

    return {
        "quali_pace":       round(float(quali_pace), 4),
        "grid_win_rate":    round(float(grid_win_rate), 4),
        "race_pace":        round(float(race_pace), 4),
        "practice_trend":   round(float(practice_trend), 4),
        "teammate_gap":     round(float(teammate_gap), 4),
        "quali_extraction": round(float(quali_extraction), 4),
        "adaptability":     round(float(adaptability), 4),
        "start_score":      round(float(start_score), 4),
        "reliability":      round(float(reliability), 4),
        "energy_score":     round(float(energy_score), 4),
    }


# ─── SCORING ──────────────────────────────────────────────────────────────────

def compute_raw_score(features: dict, team: str) -> float:
    base_score = sum(features.get(k, 0) * w for k, w in WEIGHTS_V4.items())
    # Apply innate team tier prior + optional 2026 season adjustment.
    # This ensures realistic separation when practice/quali data is sparse,
    # but still allows teams to improve as TEAM_TIER_ADJUST is updated.
    return base_score + get_team_tier_boost(team)


def softmax_scores(scores: list, temperature: float = SOFTMAX_TEMP) -> np.ndarray:
    s = np.array(scores, dtype=float)
    if s.size == 0:
        return s
    exp_s = np.exp((s - s.max()) / temperature)
    return exp_s / exp_s.sum()


# ─── MONTE CARLO (STINT-BASED STRATEGY SIMULATION) ───────────────────────────

def _stint_time(compound: str, n_laps: int) -> float:
    """Analytical total tyre-time for a stint (sum of base_delta + degradation)."""
    tc = TYRE_COMPOUNDS[compound]
    cliff = tc["cliff_lap"]
    base = tc["base_delta"] * n_laps
    normal_laps = min(n_laps, cliff)
    deg = tc["deg_per_lap"] * normal_laps * (normal_laps - 1) / 2.0
    if n_laps > cliff:
        extra = n_laps - cliff
        cliff_rate = tc["deg_per_lap"] * 3.5
        deg += cliff_rate * extra * (extra - 1) / 2.0 + tc["deg_per_lap"] * cliff * extra
    return base + deg


def simulate_race_v4(predictions: list, circuit: str = "Australia") -> list:
    """
    Strategy-aware race simulation with tyre stints, pit stops, SC/VSC timing,
    rain, DRS overtaking, mechanical DNFs, and lap-1 incidents.
    Uses analytical stint-time computation for performance.
    """
    n = len(predictions)
    if n == 0:
        return []

    cp = CIRCUIT_PARAMS.get(circuit, CIRCUIT_PARAMS["Australia"])
    race_laps = cp.get("race_laps", 56)
    pit_loss  = cp.get("pit_loss", 22.0)
    ov_diff   = cp.get("overtake_difficulty", 0.45)

    drivers = [p["driver"] for p in predictions]
    teams   = [p["team"]   for p in predictions]
    base_p  = np.array([p["win_prob"] for p in predictions], dtype=float)

    pmax = base_p.max() if base_p.max() > 0 else 1.0
    pace = (1.0 - base_p / pmax) * 3.2
    pace += np.random.normal(0, 0.15, n)

    for i, tm in enumerate(teams):
        pace[i] += np.random.normal(0, ENERGY_UNCERTAINTY)
        extra = NEW_TEAM_UNCERTAINTY.get(tm, 0.0)
        if extra > 0:
            pace[i] += np.random.normal(0, extra)

    is_rain = np.random.random() < cp["rain_prob"]
    if is_rain:
        for i, d in enumerate(drivers):
            seasons = DRIVER_EXPERIENCE.get(d, {}).get("f1_seasons", 0)
            pace[i] -= seasons * 0.02
        pace += np.random.normal(0, 0.25, n)

    strats = [_pick_strategy(race_laps, p["grid_pos"], base_p[i]) for i, p in enumerate(predictions)]

    race_time = np.zeros(n)
    dnf = np.zeros(n, dtype=bool)

    for i in range(n):
        n_stops = len(strats[i]) - 1
        for compound, laps in strats[i]:
            race_time[i] += _stint_time(compound, laps)
        race_time[i] += n_stops * (pit_loss + np.random.normal(0, 0.5))

    race_time += pace * race_laps

    fuel_variation = np.random.normal(0, 0.5, n)
    race_time += fuel_variation

    # Lap 1 incidents
    sc_laps_used = 0
    if np.random.random() < LAP1_INCIDENT_PROB:
        n_victims = np.random.choice([1, 2, 3], p=[0.5, 0.35, 0.15])
        for _ in range(n_victims):
            victim = np.random.randint(2, min(14, n))
            if np.random.random() < 0.40:
                dnf[victim] = True
            else:
                race_time[victim] += np.random.uniform(8.0, 25.0)
        if n_victims >= 2 and np.random.random() < 0.70:
            sc_laps = np.random.randint(3, 6)
            sc_laps_used += sc_laps

    # Safety car events (compress gaps)
    n_sc_events = 0
    if np.random.random() < cp["sc_prob"]:
        n_sc_events += 1
    if np.random.random() < cp["sc_prob"] * 0.3:
        n_sc_events += 1

    for _ in range(n_sc_events):
        sc_lap = np.random.randint(5, race_laps - 5)
        sc_duration = np.random.randint(3, 7)
        sc_laps_used += sc_duration

        alive = np.where(~dnf)[0]
        if len(alive) < 2:
            continue
        alive_sorted = alive[np.argsort(race_time[alive])]
        leader_time = race_time[alive_sorted[0]]
        for rank, idx in enumerate(alive_sorted):
            if rank > 0:
                gap = race_time[idx] - leader_time
                race_time[idx] -= gap * 0.65
                race_time[idx] += np.random.normal(0, 0.3)

        for idx in alive:
            si = strats[idx]
            n_stints = len(si)
            cum = 0
            for stint_idx, (comp, laps) in enumerate(si):
                cum += laps
                if cum > sc_lap and stint_idx < n_stints - 1:
                    early_pit_savings = pit_loss * 0.45
                    race_time[idx] -= early_pit_savings * np.random.uniform(0.3, 0.8)
                    break

    # Virtual safety car
    if np.random.random() < cp["vsc_prob"]:
        alive = np.where(~dnf)[0]
        if len(alive) > 1:
            alive_sorted = alive[np.argsort(race_time[alive])]
            leader_time = race_time[alive_sorted[0]]
            for idx in alive_sorted[1:]:
                gap = race_time[idx] - leader_time
                race_time[idx] -= gap * 0.3

    # Mechanical DNF
    for i, tm in enumerate(teams):
        if dnf[i]:
            continue
        base_dnf = DNF_RATES.get(tm, DNF_RATES["default"])
        if np.random.random() < base_dnf:
            dnf[i] = True

    # Driver error (off-track, spin)
    for i in range(n):
        if dnf[i]:
            continue
        if np.random.random() < 0.04:
            race_time[i] += np.random.uniform(3.0, 18.0)

    # Overtaking dynamics (undercut/overcut + DRS)
    alive = np.where(~dnf)[0]
    alive_sorted = alive[np.argsort(race_time[alive])]

    for rank in range(1, len(alive_sorted)):
        i = alive_sorted[rank]
        ahead = alive_sorted[rank - 1]
        gap = race_time[i] - race_time[ahead]

        if gap < 5.0 and gap > 0:
            pace_adv = pace[ahead] - pace[i]
            strat_diff = len(strats[i]) - len(strats[ahead])

            overtake_chance = 0.0
            if pace_adv > 0:
                overtake_chance += min(0.30, pace_adv * 0.12)
            if strat_diff > 0:
                overtake_chance += 0.08
            if gap < 1.0:
                overtake_chance += 0.05

            overtake_chance *= (1.0 - ov_diff * 0.7)
            overtake_chance *= OVERTAKE_FACTOR / 1.4

            if np.random.random() < overtake_chance:
                old_ahead = race_time[ahead]
                race_time[ahead] = race_time[i] + 0.4
                race_time[i] = old_ahead

    # Start procedure advantage (small boost for top finishers)
    alive = np.where(~dnf)[0]
    alive_sorted = alive[np.argsort(race_time[alive])]
    for rank, i in enumerate(alive_sorted[:5]):
        bonus = START_PROCEDURE_ADVANTAGE.get(teams[i], 0.0) * 0.3
        race_time[i] -= bonus

    # Noise for variance
    race_time += np.random.normal(0, 0.8, n)

    alive = np.where(~dnf)[0]
    alive_sorted = alive[np.argsort(race_time[alive])]
    return [drivers[i] for i in alive_sorted]


def run_monte_carlo_v4(predictions: list, n_sims: int = 100000, circuit: str = "Australia") -> list:
    win_counts    = defaultdict(int)
    podium_counts = defaultdict(int)
    points_counts = defaultdict(int)
    dnf_counts    = defaultdict(int)
    position_sums = defaultdict(int)
    all_drivers   = [p["driver"] for p in predictions]

    for _ in range(n_sims):
        result = simulate_race_v4(predictions, circuit)
        if result:
            win_counts[result[0]] += 1
        for d in result[:3]:
            podium_counts[d] += 1
        for d in result[:10]:
            points_counts[d] += 1
        for pos, d in enumerate(result):
            position_sums[d] += (pos + 1)
        for d in all_drivers:
            if d not in result:
                dnf_counts[d] += 1
                position_sums[d] += len(all_drivers)

    output = []
    for p in predictions:
        d = p["driver"]
        output.append({
            "driver":    d,
            "team":      p["team"],
            "grid_pos":  p["grid_pos"],
            "win_pct":   round(win_counts[d]    / n_sims * 100, 2),
            "podium_pct":round(podium_counts[d] / n_sims * 100, 2),
            "points_pct":round(points_counts[d] / n_sims * 100, 2),
            "dnf_pct":   round(dnf_counts[d]    / n_sims * 100, 2),
            "avg_finish": round(position_sums[d] / n_sims, 1),
            "model_score":round(p["raw_score"], 4),
            "features":  p["features"],
            "driver_number": p.get("driver_number"),
            "team_colour":   p.get("team_colour"),
        })

    output.sort(key=lambda x: x["win_pct"], reverse=True)
    return output


# ─── MAIN PIPELINE ────────────────────────────────────────────────────────────

def run_prediction_pipeline(
    qualifying:         list[dict],
    fp_times:           dict,
    circuit:            str  = "Australia",
    n_sims:             int  = 100000,
    weekend_incidents:  Optional[dict] = None,
) -> dict:
    """
    Full pipeline: raw FastF1 data → prediction JSON.

    Args:
        qualifying:  list[{pos, driver, team, q_time}]  ← from FastF1 or manual input
        fp_times:    {driver_name: {fp1, fp2, fp3}}     ← actual lap times in seconds
        circuit:     GP name for circuit-specific params
        n_sims:      Monte Carlo iterations
        weekend_incidents: {driver_name: {crash_in_quali, dnf_in_practice, reliability_flag}}

    Returns:
        dict with keys: predictions, feature_weights, model_meta
    """
    # Step 1: Normalise into model-ready format
    grid_input = build_grid_input(qualifying, fp_times, weekend_incidents)

    # Step 2: Feature engineering
    predictions = []
    for entry in grid_input:
        features  = compute_features_v4(entry, grid_input, circuit)
        raw_score = compute_raw_score(features, entry["team"])
        predictions.append({
            "driver":        entry["driver"],
            "team":          entry["team"],
            "grid_pos":      entry["pos"],
            "features":      features,
            "raw_score":     raw_score,
            "driver_number": entry.get("driver_number"),
            "team_colour":   entry.get("team_colour"),
        })

    # Step 3: Softmax probabilities
    scores = [p["raw_score"] for p in predictions]
    probs  = softmax_scores(scores)
    for i, p in enumerate(predictions):
        p["win_prob"] = float(probs[i])

    # Step 4: Monte Carlo
    results = run_monte_carlo_v4(predictions, n_sims=n_sims, circuit=circuit)

    circuit_p = CIRCUIT_PARAMS.get(circuit, CIRCUIT_PARAMS["Australia"])

    return {
        "predictions":     results,
        "feature_weights": WEIGHTS_V4,
        "model_meta": {
            "n_sims":              n_sims,
            "circuit":             circuit,
            "race_laps":           circuit_p.get("race_laps", 56),
            "pit_loss_seconds":    circuit_p.get("pit_loss", 22.0),
            "overtake_difficulty": circuit_p.get("overtake_difficulty", 0.45),
            "pole_win_rate":       circuit_p["pole_win_rate"],
            "overtake_factor":     OVERTAKE_FACTOR,
            "energy_uncertainty":  ENERGY_UNCERTAINTY,
            "softmax_temperature": SOFTMAX_TEMP,
            "sc_probability":      circuit_p["sc_prob"],
            "vsc_probability":     circuit_p["vsc_prob"],
            "rain_probability":    circuit_p["rain_prob"],
            "simulation_type":     "lap_by_lap_strategy",
        },
    }
