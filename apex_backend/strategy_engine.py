"""
APEX Strategy Engine — Tyre Strategy Intelligence
===================================================
Tyre degradation modelling, Monte Carlo strategy simulation,
and undercut/overcut analysis for F1 race strategy.

Pipeline:
  FP stint + lap data
    → TyreDegModel.fit()           fit degradation curves per driver/compound
    → StrategySimulator.run()      Monte Carlo strategy simulation with events
    → UndercutCalculator.analyze() gap evolution for undercut/overcut scenarios
"""

import hashlib
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict


# ─── CIRCUIT STRATEGY PARAMETERS ─────────────────────────────────────────────

STRATEGY_CIRCUIT_PARAMS = {
    "Australia":      {"pit_loss": 21.5, "total_laps": 58, "fuel_effect": 0.055},
    "China":          {"pit_loss": 22.0, "total_laps": 56, "fuel_effect": 0.055},
    "Shanghai":       {"pit_loss": 22.0, "total_laps": 56, "fuel_effect": 0.055},
    "Japan":          {"pit_loss": 21.0, "total_laps": 53, "fuel_effect": 0.055},
    "Suzuka":         {"pit_loss": 21.0, "total_laps": 53, "fuel_effect": 0.055},
    "Bahrain":        {"pit_loss": 22.5, "total_laps": 57, "fuel_effect": 0.055},
    "Saudi Arabia":   {"pit_loss": 23.0, "total_laps": 50, "fuel_effect": 0.055},
    "Jeddah":         {"pit_loss": 23.0, "total_laps": 50, "fuel_effect": 0.055},
    "Miami":          {"pit_loss": 23.5, "total_laps": 57, "fuel_effect": 0.055},
    "Emilia Romagna": {"pit_loss": 22.0, "total_laps": 63, "fuel_effect": 0.050},
    "Imola":          {"pit_loss": 22.0, "total_laps": 63, "fuel_effect": 0.050},
    "Monaco":         {"pit_loss": 24.0, "total_laps": 78, "fuel_effect": 0.045},
    "Spain":          {"pit_loss": 22.5, "total_laps": 66, "fuel_effect": 0.055},
    "Barcelona":      {"pit_loss": 22.5, "total_laps": 66, "fuel_effect": 0.055},
    "Canada":         {"pit_loss": 22.0, "total_laps": 70, "fuel_effect": 0.050},
    "Montreal":       {"pit_loss": 22.0, "total_laps": 70, "fuel_effect": 0.050},
    "Austria":        {"pit_loss": 20.5, "total_laps": 71, "fuel_effect": 0.055},
    "Spielberg":      {"pit_loss": 20.5, "total_laps": 71, "fuel_effect": 0.055},
    "Britain":        {"pit_loss": 21.5, "total_laps": 52, "fuel_effect": 0.055},
    "Silverstone":    {"pit_loss": 21.5, "total_laps": 52, "fuel_effect": 0.055},
    "Belgium":        {"pit_loss": 21.0, "total_laps": 44, "fuel_effect": 0.060},
    "Spa-Francorchamps": {"pit_loss": 21.0, "total_laps": 44, "fuel_effect": 0.060},
    "Hungary":        {"pit_loss": 22.0, "total_laps": 70, "fuel_effect": 0.050},
    "Budapest":       {"pit_loss": 22.0, "total_laps": 70, "fuel_effect": 0.050},
    "Netherlands":    {"pit_loss": 22.5, "total_laps": 72, "fuel_effect": 0.050},
    "Zandvoort":      {"pit_loss": 22.5, "total_laps": 72, "fuel_effect": 0.050},
    "Italy":          {"pit_loss": 25.0, "total_laps": 53, "fuel_effect": 0.060},
    "Monza":          {"pit_loss": 25.0, "total_laps": 53, "fuel_effect": 0.060},
    "Azerbaijan":     {"pit_loss": 23.0, "total_laps": 51, "fuel_effect": 0.055},
    "Baku":           {"pit_loss": 23.0, "total_laps": 51, "fuel_effect": 0.055},
    "Singapore":      {"pit_loss": 23.5, "total_laps": 62, "fuel_effect": 0.050},
    "Marina Bay":     {"pit_loss": 23.5, "total_laps": 62, "fuel_effect": 0.050},
    "United States":  {"pit_loss": 22.0, "total_laps": 56, "fuel_effect": 0.055},
    "Austin":         {"pit_loss": 22.0, "total_laps": 56, "fuel_effect": 0.055},
    "Mexico":         {"pit_loss": 22.5, "total_laps": 71, "fuel_effect": 0.050},
    "Mexico City":    {"pit_loss": 22.5, "total_laps": 71, "fuel_effect": 0.050},
    "Brazil":         {"pit_loss": 21.5, "total_laps": 71, "fuel_effect": 0.055},
    "Interlagos":     {"pit_loss": 21.5, "total_laps": 71, "fuel_effect": 0.055},
    "Las Vegas":      {"pit_loss": 24.0, "total_laps": 50, "fuel_effect": 0.055},
    "Qatar":          {"pit_loss": 22.0, "total_laps": 57, "fuel_effect": 0.055},
    "Lusail":         {"pit_loss": 22.0, "total_laps": 57, "fuel_effect": 0.055},
    "Abu Dhabi":      {"pit_loss": 22.5, "total_laps": 58, "fuel_effect": 0.055},
    "Yas Marina":     {"pit_loss": 22.5, "total_laps": 58, "fuel_effect": 0.055},
    "Melbourne":      {"pit_loss": 21.5, "total_laps": 58, "fuel_effect": 0.055},
}

_DEFAULT_CIRCUIT = {"pit_loss": 22.0, "total_laps": 57, "fuel_effect": 0.055}

COMPOUND_DEFAULTS = {
    "SOFT":   {"delta": 0.0,  "base_deg": 0.080, "cliff_deg": 0.0030, "max_stint": 22},
    "MEDIUM": {"delta": 0.55, "base_deg": 0.040, "cliff_deg": 0.0010, "max_stint": 32},
    "HARD":   {"delta": 1.10, "base_deg": 0.025, "cliff_deg": 0.0005, "max_stint": 42},
    "INTER":  {"delta": 0.30, "base_deg": 0.050, "cliff_deg": 0.0020, "max_stint": 28},
    "WET":    {"delta": 3.00, "base_deg": 0.030, "cliff_deg": 0.0010, "max_stint": 35},
}

MIN_STINT_LAPS = 5
SC_PIT_SAVING = 16.0
VSC_PIT_SAVING = 10.0
PUNCTURE_PENALTY = 28.0


# ─── DEGRADATION MODEL ───────────────────────────────────────────────────────

@dataclass
class DegCurve:
    """Tyre degradation curve for a driver + compound combination."""
    driver: str
    compound: str
    base_time: float
    linear_deg: float
    quadratic_deg: float
    r_squared: float = 0.0
    n_laps_fitted: int = 0

    def lap_time(self, stint_lap: int) -> float:
        return self.base_time + self.linear_deg * stint_lap + self.quadratic_deg * stint_lap ** 2

    def competitive_laps(self, threshold: float = 2.0) -> int:
        for lap in range(1, 80):
            if self.lap_time(lap) - self.base_time > threshold:
                return lap
        return 80

    def stint_time_vec(self, n_laps: int, race_lap_start: int,
                       fuel_effect: float, deg_noise: float = 1.0) -> float:
        """Vectorized total stint time with fuel correction and deg noise."""
        sl = np.arange(n_laps, dtype=np.float64)
        rl = race_lap_start + sl
        times = (self.base_time
                 + self.linear_deg * deg_noise * sl
                 + self.quadratic_deg * deg_noise * sl ** 2
                 - fuel_effect * rl)
        return float(np.sum(times))

    def stint_time_continued(
        self, n_laps: int, stint_lap_start: int, race_lap_start: int,
        fuel_effect: float, deg_noise: float = 1.0,
    ) -> float:
        """Total time for n_laps continuing a stint (stint_lap_start = next lap index on tyre)."""
        if n_laps <= 0:
            return 0.0
        total = 0.0
        for i in range(n_laps):
            sl = stint_lap_start + i
            rl = race_lap_start + i
            total += (
                self.base_time
                + self.linear_deg * deg_noise * sl
                + self.quadratic_deg * deg_noise * sl * sl
                - fuel_effect * rl
            )
        return float(total)


class TyreDegModel:
    """Fits tyre degradation curves from practice session data."""

    def __init__(self):
        self.curves: dict[tuple[str, str], DegCurve] = {}
        self.driver_base_pace: dict[str, float] = {}

    def fit(self, stints: dict, laps: dict, drivers: list[dict]):
        """
        Fit deg curves from OpenF1 stint + lap data.

        stints: {driver_number_str: [{stint_number, compound, lap_start, lap_end, ...}]}
        laps:   {driver_number_int: [{lap_number, lap_duration, s1, s2, s3, is_pit_out}]}
        drivers: [{driver_number, full_name, team_name, ...}]
        """
        driver_map = {d["driver_number"]: d.get("full_name", f"Driver {d['driver_number']}")
                      for d in drivers}

        for dn_str, driver_stints in stints.items():
            dn = int(dn_str)
            name = driver_map.get(dn, f"Driver {dn}")
            driver_laps = laps.get(dn, [])
            if not driver_laps:
                continue

            lap_map = {}
            for l in driver_laps:
                dur = l.get("lap_duration")
                if dur is None or dur <= 0:
                    s1, s2, s3 = l.get("s1"), l.get("s2"), l.get("s3")
                    if s1 and s2 and s3:
                        dur = s1 + s2 + s3
                if dur and dur > 0:
                    lap_map[l["lap_number"]] = dur

            for stint in driver_stints:
                compound = (stint.get("compound") or "UNKNOWN").upper()
                if compound == "UNKNOWN":
                    continue

                lap_start = stint["lap_start"]
                lap_end = stint["lap_end"]
                if lap_end - lap_start + 1 < 3:
                    continue

                stint_laps_x = []
                stint_times_y = []
                for i, lap_num in enumerate(range(lap_start, lap_end + 1)):
                    if i == 0:
                        continue
                    if lap_num in lap_map:
                        t = lap_map[lap_num]
                        if t is not None and t > 60:
                            stint_laps_x.append(i)
                            stint_times_y.append(t)

                if len(stint_laps_x) < 3:
                    continue

                times_arr = np.array(stint_times_y)
                q1, q3 = np.percentile(times_arr, [25, 75])
                iqr = max(q3 - q1, 0.01)
                upper = q3 + 2.5 * iqr
                mask = times_arr <= upper
                stint_laps_x = [stint_laps_x[j] for j in range(len(mask)) if mask[j]]
                stint_times_y = [stint_times_y[j] for j in range(len(mask)) if mask[j]]

                if len(stint_laps_x) < 3:
                    continue

                x = np.array(stint_laps_x, dtype=float)
                y = np.array(stint_times_y, dtype=float)

                use_linear = len(stint_laps_x) <= 5
                try:
                    if use_linear:
                        coeffs = np.polyfit(x, y, deg=1)
                        a_coeff, b_coeff = coeffs[0], coeffs[1]
                        c_coeff = 0.0
                    else:
                        coeffs = np.polyfit(x, y, deg=2)
                        c_coeff, b_coeff, a_coeff = coeffs
                    if use_linear:
                        y_pred = a_coeff + b_coeff * x
                    else:
                        y_pred = np.polyval([c_coeff, b_coeff, a_coeff], x)
                    ss_res = np.sum((y - y_pred) ** 2)
                    ss_tot = np.sum((y - np.mean(y)) ** 2)
                    r_sq = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

                    b_coeff = max(0.0, b_coeff)
                    c_coeff = max(0.0, c_coeff) if not use_linear else 0.0

                    key = (name, compound)
                    existing = self.curves.get(key)
                    if existing is None or len(stint_laps_x) > existing.n_laps_fitted:
                        self.curves[key] = DegCurve(
                            driver=name, compound=compound,
                            base_time=a_coeff, linear_deg=b_coeff,
                            quadratic_deg=c_coeff,
                            r_squared=max(0.0, r_sq),
                            n_laps_fitted=len(stint_laps_x),
                        )
                except (np.linalg.LinAlgError, ValueError):
                    continue

            best = min(lap_map.values()) if lap_map else None
            if best:
                self.driver_base_pace[name] = best

    @staticmethod
    def _synthetic_deg_scale(driver: str, grid_pos: Optional[int]) -> float:
        """
        When tyre curves are not fitted for this driver, stint optimisation is identical
        for everyone (same linear/quadratic per compound). Apply a stable per-driver
        factor plus a small grid effect so strategies diverge realistically.
        """
        h = hashlib.sha256(driver.encode("utf-8")).digest()
        u = int.from_bytes(h[:4], "big") / (2**32 - 1)
        noise = 0.86 + 0.28 * u
        gp = float(grid_pos if grid_pos is not None else 11)
        g_scale = 1.0 + (gp - 11.0) * 0.004
        return float(np.clip(noise * g_scale, 0.82, 1.22))

    def get_curve(
        self, driver: str, compound: str, grid_pos: Optional[int] = None,
    ) -> DegCurve:
        key = (driver, compound.upper())
        if key in self.curves:
            return self.curves[key]

        base_pace = self.driver_base_pace.get(driver)
        if base_pace is None:
            driver_curves = [c.base_time for c in self.curves.values() if c.driver == driver]
            base_pace = min(driver_curves) if driver_curves else 92.0

        scale = self._synthetic_deg_scale(driver, grid_pos)
        compound_upper = compound.upper()
        compound_curves = [
            curve for (_, c), curve in self.curves.items()
            if c == compound_upper
        ]
        if compound_curves:
            avg_linear = float(np.mean([c.linear_deg for c in compound_curves]))
            avg_quad = float(np.mean([c.quadratic_deg for c in compound_curves]))
            defaults = COMPOUND_DEFAULTS.get(compound_upper, COMPOUND_DEFAULTS["MEDIUM"])
            return DegCurve(
                driver=driver, compound=compound_upper,
                base_time=base_pace + defaults["delta"],
                linear_deg=avg_linear * scale,
                quadratic_deg=avg_quad * scale,
            )

        defaults = COMPOUND_DEFAULTS.get(compound_upper, COMPOUND_DEFAULTS["MEDIUM"])
        return DegCurve(
            driver=driver, compound=compound_upper,
            base_time=base_pace + defaults["delta"],
            linear_deg=defaults["base_deg"] * scale,
            quadratic_deg=defaults["cliff_deg"] * scale,
        )

    def _curve_payload(self, curve: DegCurve) -> dict:
        return {
            "base_time": round(curve.base_time, 3),
            "linear_deg": round(curve.linear_deg, 4),
            "quadratic_deg": round(curve.quadratic_deg, 6),
            "r_squared": round(curve.r_squared, 3),
            "n_laps_fitted": curve.n_laps_fitted,
            "competitive_laps": curve.competitive_laps(),
        }

    def to_dict(
        self,
        fill_for_drivers: Optional[list[dict]] = None,
        fill_compounds: Optional[list[str]] = None,
    ) -> dict:
        """
        Serialize fitted curves. If fill_for_drivers + fill_compounds are set, also
        add any missing (driver, compound) rows via get_curve() so UIs show synthetic
        curves used when practice data did not produce a fit.
        """
        result: dict[str, dict] = {}
        for (driver, compound), curve in self.curves.items():
            if driver not in result:
                result[driver] = {}
            result[driver][compound] = self._curve_payload(curve)

        if fill_for_drivers and fill_compounds:
            comps = [c.upper() for c in fill_compounds]
            for d in fill_for_drivers:
                name = d.get("driver")
                if not name:
                    continue
                gp = d.get("grid_pos", 22)
                if name not in result:
                    result[name] = {}
                for c in comps:
                    if c in result[name]:
                        continue
                    curve = self.get_curve(name, c, gp)
                    payload = self._curve_payload(curve)
                    payload["synthetic"] = (name, c) not in self.curves
                    result[name][c] = payload

        return result


# ─── STRATEGY SIMULATOR ──────────────────────────────────────────────────────

@dataclass
class _StintPlan:
    compound: str
    laps: int


def _get_circuit(circuit: str) -> dict:
    return STRATEGY_CIRCUIT_PARAMS.get(circuit, _DEFAULT_CIRCUIT)


class StrategySimulator:
    """Monte Carlo tyre strategy simulation with event injection."""

    def __init__(
        self,
        deg_model: TyreDegModel,
        circuit: str = "Australia",
        available_compounds: Optional[list[str]] = None,
        custom_pit_loss: Optional[float] = None,
        custom_total_laps: Optional[int] = None,
        sprint_race: bool = False,
    ):
        self.deg_model = deg_model
        self.circuit = circuit
        self.sprint_race = sprint_race
        params = _get_circuit(circuit)
        self.pit_loss = custom_pit_loss if custom_pit_loss is not None else params["pit_loss"]
        self.total_laps = custom_total_laps if custom_total_laps is not None else params["total_laps"]
        self.fuel_effect = params["fuel_effect"]
        self.compounds = [c.upper() for c in (available_compounds or ["SOFT", "MEDIUM", "HARD"])]

        try:
            from model_core import CIRCUIT_PARAMS
            cp = CIRCUIT_PARAMS.get(circuit, {})
        except ImportError:
            cp = {}
        self.sc_prob = cp.get("sc_prob", 0.45)
        self.vsc_prob = cp.get("vsc_prob", 0.22)
        self.rain_prob = cp.get("rain_prob", 0.10)

    # ── Strategy generation ──────────────────────────────────────────────────

    def generate_strategies(
        self, driver: str, driver_compounds: Optional[list[str]] = None,
        grid_pos: Optional[int] = None,
    ) -> list[dict]:
        """Generate optimized candidate strategies for a driver."""
        strategies = []
        total = self.total_laps
        comps = [c.upper() for c in (driver_compounds or self.compounds)]

        if self.sprint_race:
            # Sprint: 0-stop (single stint) and 1-stop only — matches real sprint behaviour.
            for c in comps:
                mx = COMPOUND_DEFAULTS.get(c, {}).get("max_stint", 40)
                if total >= MIN_STINT_LAPS and total <= mx:
                    strategies.append({
                        "stints": [{"compound": c, "laps": total}],
                        "n_stops": 0,
                        "label": f"{c[0]}{total}",
                    })
            for c1 in comps:
                for c2 in comps:
                    if c1 == c2:
                        continue
                    split = self._optimize_1stop(driver, c1, c2, total, grid_pos)
                    if split:
                        s1, s2 = split
                        strategies.append({
                            "stints": [{"compound": c1, "laps": s1},
                                       {"compound": c2, "laps": s2}],
                            "n_stops": 1,
                            "label": f"{c1[0]}{s1}-{c2[0]}{s2}",
                        })
            return self._deduplicate(strategies)

        for c1 in comps:
            for c2 in comps:
                if c1 == c2:
                    continue
                split = self._optimize_1stop(driver, c1, c2, total, grid_pos)
                if split:
                    s1, s2 = split
                    strategies.append({
                        "stints": [{"compound": c1, "laps": s1},
                                   {"compound": c2, "laps": s2}],
                        "n_stops": 1,
                        "label": f"{c1[0]}{s1}-{c2[0]}{s2}",
                    })

        for c1 in comps:
            for c2 in comps:
                for c3 in comps:
                    if len({c1, c2, c3}) < 2:
                        continue
                    split = self._optimize_2stop(driver, c1, c2, c3, total, grid_pos)
                    if split:
                        s1, s2, s3 = split
                        strategies.append({
                            "stints": [{"compound": c1, "laps": s1},
                                       {"compound": c2, "laps": s2},
                                       {"compound": c3, "laps": s3}],
                            "n_stops": 2,
                            "label": f"{c1[0]}{s1}-{c2[0]}{s2}-{c3[0]}{s3}",
                        })

        return self._deduplicate(strategies)

    def _optimize_1stop(self, driver, c1, c2, total, grid_pos: Optional[int] = None):
        best_t, best = float("inf"), None
        curve1 = self.deg_model.get_curve(driver, c1, grid_pos)
        curve2 = self.deg_model.get_curve(driver, c2, grid_pos)
        max1 = min(COMPOUND_DEFAULTS.get(c1, {}).get("max_stint", 35), total - MIN_STINT_LAPS)
        max2 = COMPOUND_DEFAULTS.get(c2, {}).get("max_stint", 40)
        for s1 in range(MIN_STINT_LAPS, max1 + 1):
            s2 = total - s1
            if s2 < MIN_STINT_LAPS or s2 > max2:
                continue
            t = (curve1.stint_time_vec(s1, 0, self.fuel_effect)
                 + self.pit_loss
                 + curve2.stint_time_vec(s2, s1, self.fuel_effect))
            if t < best_t:
                best_t, best = t, (s1, s2)
        return best

    def _optimize_2stop(self, driver, c1, c2, c3, total, grid_pos: Optional[int] = None):
        best_t, best = float("inf"), None
        curve1 = self.deg_model.get_curve(driver, c1, grid_pos)
        curve2 = self.deg_model.get_curve(driver, c2, grid_pos)
        curve3 = self.deg_model.get_curve(driver, c3, grid_pos)
        m1 = COMPOUND_DEFAULTS.get(c1, {}).get("max_stint", 25)
        m2 = COMPOUND_DEFAULTS.get(c2, {}).get("max_stint", 25)
        m3 = COMPOUND_DEFAULTS.get(c3, {}).get("max_stint", 25)

        for s1 in range(MIN_STINT_LAPS, min(m1, total - 2 * MIN_STINT_LAPS) + 1, 5):
            for s2 in range(MIN_STINT_LAPS, min(m2, total - s1 - MIN_STINT_LAPS) + 1, 5):
                s3 = total - s1 - s2
                if s3 < MIN_STINT_LAPS or s3 > m3:
                    continue
                t = (curve1.stint_time_vec(s1, 0, self.fuel_effect)
                     + self.pit_loss
                     + curve2.stint_time_vec(s2, s1, self.fuel_effect)
                     + self.pit_loss
                     + curve3.stint_time_vec(s3, s1 + s2, self.fuel_effect))
                if t < best_t:
                    best_t, best = t, (s1, s2, s3)

        if best:
            s1c, s2c, _ = best
            for s1 in range(max(MIN_STINT_LAPS, s1c - 2), min(m1, s1c + 3) + 1):
                for s2 in range(max(MIN_STINT_LAPS, s2c - 2), min(m2, s2c + 3) + 1):
                    s3 = total - s1 - s2
                    if s3 < MIN_STINT_LAPS or s3 > m3:
                        continue
                    t = (curve1.stint_time_vec(s1, 0, self.fuel_effect)
                         + self.pit_loss
                         + curve2.stint_time_vec(s2, s1, self.fuel_effect)
                         + self.pit_loss
                         + curve3.stint_time_vec(s3, s1 + s2, self.fuel_effect))
                    if t < best_t:
                        best_t, best = t, (s1, s2, s3)
        return best

    def _deduplicate(self, strategies):
        seen, unique = set(), []
        for s in strategies:
            comps = tuple(st["compound"] for st in s["stints"])
            laps = tuple(round(st["laps"] / 3) * 3 for st in s["stints"])
            sig = (comps, laps)
            if sig not in seen:
                seen.add(sig)
                unique.append(s)
        return unique

    # ── Monte Carlo ──────────────────────────────────────────────────────────

    def _evaluate_strategy(
        self, driver: str, stints: list[dict],
        sc_lap, sc_dur, vsc_lap, vsc_dur,
        red_flag_lap, has_puncture: bool,
        grid_pos: Optional[int] = None,
    ) -> float:
        total_time = 0.0
        race_lap = 0
        for i, stint in enumerate(stints):
            curve = self.deg_model.get_curve(driver, stint["compound"], grid_pos)
            noise = max(0.5, np.random.normal(1.0, 0.12))
            total_time += curve.stint_time_vec(
                stint["laps"], race_lap, self.fuel_effect, noise)
            race_lap += stint["laps"]

            if i < len(stints) - 1:
                pit = self.pit_loss + np.random.normal(0, 0.3)
                pit_lap = race_lap
                if sc_lap is not None and abs(pit_lap - sc_lap) <= 2:
                    pit = max(4.0, pit - SC_PIT_SAVING)
                elif vsc_lap is not None and abs(pit_lap - vsc_lap) <= 1:
                    pit = max(6.0, pit - VSC_PIT_SAVING)
                elif red_flag_lap is not None and abs(pit_lap - red_flag_lap) <= 3:
                    pit = 0.0
                total_time += pit

        if has_puncture:
            total_time += PUNCTURE_PENALTY + np.random.normal(0, 4)
        total_time += np.random.normal(0, 2.5)
        return total_time

    @staticmethod
    def _historical_stop_bias_delta(n_stops: int, bias: Optional[dict]) -> float:
        """
        Negative = strategy matches last year's dominant stop count (lower time = better).
        dominant_pits 0 = no-stop sprint (historical field stayed on one set).
        """
        if not bias:
            return 0.0
        dom = bias.get("dominant_pits")
        if dom not in (0, 1, 2):
            return 0.0
        conf = float(bias.get("confidence", 0.6))
        bonus = float(bias.get("bonus_seconds", 3.5))
        if n_stops == dom:
            return -bonus * conf
        # Penalize non-dominant stop count (must be material when bonus is large)
        return bonus * conf * 0.5

    def run_monte_carlo(
        self,
        drivers: list[dict],
        n_sims: int = 10000,
        historical_stop_bias: Optional[dict] = None,
    ) -> dict:
        strats = {}
        grid_map = {}
        for d in drivers:
            name = d["driver"]
            gp = d.get("grid_pos", 22)
            grid_map[name] = gp
            driver_comps = d.get("available_compounds")
            s = self.generate_strategies(name, driver_comps, gp)
            if s:
                base_times = []
                for st in s:
                    t = 0.0
                    rl = 0
                    for stint in st["stints"]:
                        curve = self.deg_model.get_curve(name, stint["compound"], gp)
                        t += curve.stint_time_vec(stint["laps"], rl, self.fuel_effect, 1.0)
                        rl += stint["laps"]
                    t += st["n_stops"] * self.pit_loss
                    base_times.append(t)

                scored = []
                hist_dom = (
                    historical_stop_bias.get("dominant_pits")
                    if historical_stop_bias
                    else None
                )
                for i, st in enumerate(s):
                    adj = base_times[i]
                    n_stops = st["n_stops"]
                    if not self.sprint_race:
                        if gp <= 5:
                            adj -= 2.0 if n_stops == 1 else 0.0
                        elif gp >= 16:
                            # Back-of-grid 2-stop heuristic conflicts with historical 1-stop tracks
                            if hist_dom != 1:
                                adj -= 2.5 if n_stops >= 2 else 0.0
                    adj += self._historical_stop_bias_delta(n_stops, historical_stop_bias)
                    scored.append((adj, i))
                scored.sort(key=lambda x: x[0])
                adj_by_idx = {i: adj for adj, i in scored}
                top5 = [s[i] for _, i in scored[:5]]
                if not self.sprint_race and gp <= 5:
                    one_stops = [st for st in top5 if st["n_stops"] == 1]
                    if not one_stops and any(st["n_stops"] == 1 for st in s):
                        best_1s_idx = min((i for i, st in enumerate(s) if st["n_stops"] == 1),
                                          key=lambda i: base_times[i])
                        best_1s = s[best_1s_idx]
                        top5 = [best_1s] + [st for st in top5 if st != best_1s][:4]
                # Last year's dominant stop count must appear in MC candidate set
                if hist_dom == 0 and not any(st["n_stops"] == 0 for st in top5):
                    zidx = [i for i, st in enumerate(s) if st["n_stops"] == 0]
                    if zidx:
                        bi = min(zidx, key=lambda i: adj_by_idx[i])
                        best0 = s[bi]
                        top5 = [best0] + [st for st in top5 if st != best0][:4]
                if hist_dom == 1 and not any(st["n_stops"] == 1 for st in top5):
                    ones = [i for i, st in enumerate(s) if st["n_stops"] == 1]
                    if ones:
                        bi = min(ones, key=lambda i: adj_by_idx[i])
                        best_1s = s[bi]
                        top5 = [best_1s] + [st for st in top5 if st != best_1s][:4]
                if hist_dom == 2 and not any(st["n_stops"] == 2 for st in top5):
                    twos = [i for i, st in enumerate(s) if st["n_stops"] == 2]
                    if twos:
                        bi = min(twos, key=lambda i: adj_by_idx[i])
                        best_2s = s[bi]
                        top5 = [best_2s] + [st for st in top5 if st != best_2s][:4]
                strats[name] = top5
        if not strats:
            return {"drivers": [], "meta": {}}

        wins = defaultdict(lambda: defaultdict(int))
        times = defaultdict(lambda: defaultdict(list))
        positions = defaultdict(lambda: defaultdict(list))

        total = self.total_laps
        driver_names = [d["driver"] for d in drivers]

        for _ in range(n_sims):
            sc_lap = np.random.randint(1, total) if np.random.random() < self.sc_prob else None
            sc_dur = np.random.randint(3, 7) if sc_lap else 0
            vsc_lap = np.random.randint(1, total) if np.random.random() < self.vsc_prob else None
            vsc_dur = np.random.randint(2, 4) if vsc_lap else 0
            red_flag_lap = np.random.randint(1, total) if np.random.random() < 0.04 else None
            puncture_driver = np.random.choice(driver_names) if np.random.random() < 0.06 else None

            sim_best_times = {}
            for name in driver_names:
                driver_strats = strats.get(name, [])
                if not driver_strats:
                    continue
                best_t, best_idx = float("inf"), 0
                hist_d = (
                    historical_stop_bias.get("dominant_pits")
                    if historical_stop_bias
                    else None
                )
                for idx, s in enumerate(driver_strats):
                    t = self._evaluate_strategy(
                        name, s["stints"],
                        sc_lap, sc_dur, vsc_lap, vsc_dur,
                        red_flag_lap, name == puncture_driver,
                        grid_map.get(name),
                    )

                    gp = grid_map.get(name, 22)
                    first_stint_laps = s["stints"][0]["laps"] if s["stints"] else 10
                    if gp > 5:
                        dirty_air_per_lap = 0.25 * min(1.0, (gp - 5) / 12.0)
                        dirty_air_laps = min(first_stint_laps, int(first_stint_laps * 0.7))
                        t += dirty_air_per_lap * dirty_air_laps
                    if (
                        not self.sprint_race
                        and gp >= 16
                        and s["n_stops"] >= 2
                        and hist_d != 1
                    ):
                        t -= 0.5
                    t += self._historical_stop_bias_delta(s["n_stops"], historical_stop_bias)

                    if t < best_t:
                        best_t, best_idx = t, idx
                sim_best_times[name] = (best_idx, best_t)
                wins[name][best_idx] += 1
                times[name][best_idx].append(best_t)

            ranked = sorted(sim_best_times.items(), key=lambda x: x[1][1])
            for pos, (name, (idx, _)) in enumerate(ranked, 1):
                positions[name][idx].append(pos)

        output_drivers = []
        for d in drivers:
            name = d["driver"]
            gp = d.get("grid_pos", 22)
            driver_strats = strats.get(name, [])
            if not driver_strats:
                continue
            strat_out = []
            for idx, s in enumerate(driver_strats):
                w = wins[name][idx]
                t_list = times[name][idx]
                p_list = positions[name][idx]
                strat_out.append({
                    "stints": s["stints"],
                    "n_stops": s["n_stops"],
                    "label": s["label"],
                    "probability": round(w / n_sims * 100, 1),
                    "avg_race_time": round(float(np.mean(t_list)), 1) if t_list else 0,
                    "time_std": round(float(np.std(t_list)), 1) if t_list else 0,
                    "avg_position": round(float(np.mean(p_list)), 1) if p_list else 0,
                })
            strat_out.sort(key=lambda x: x["probability"], reverse=True)
            output_drivers.append({
                "driver": name,
                "driver_number": d.get("driver_number"),
                "team": d.get("team", ""),
                "team_colour": d.get("team_colour", ""),
                "grid_pos": gp,
                "tyre_allocation": d.get("tyre_allocation", {}),
                "strategies": strat_out[:8],
                "optimal_index": 0,
            })

        output_drivers.sort(
            key=lambda x: x["strategies"][0]["avg_position"] if x["strategies"] else 99)

        return {
            "drivers": output_drivers,
            "meta": {
                "n_sims": n_sims,
                "total_laps": self.total_laps,
                "circuit": self.circuit,
                "pit_loss_time": self.pit_loss,
                "sc_probability": round(self.sc_prob, 2),
                "vsc_probability": round(self.vsc_prob, 2),
                "available_compounds": self.compounds,
                "fuel_effect": self.fuel_effect,
                "sprint_race": self.sprint_race,
            },
            "deg_model": self.deg_model.to_dict(
                fill_for_drivers=drivers,
                fill_compounds=self.compounds,
            ),
        }

    def _pit_cost_at_lap(
        self, abs_lap: int,
        sc_lap: Optional[int], vsc_lap: Optional[int], red_flag_lap: Optional[int],
    ) -> float:
        pit = self.pit_loss
        if sc_lap is not None and abs(abs_lap - sc_lap) <= 2:
            pit = max(4.0, pit - SC_PIT_SAVING)
        elif vsc_lap is not None and abs(abs_lap - vsc_lap) <= 1:
            pit = max(6.0, pit - VSC_PIT_SAVING)
        elif red_flag_lap is not None and abs(abs_lap - red_flag_lap) <= 3:
            pit = 0.0
        return pit

    def _evaluate_live_segments(
        self, driver: str, segments: list[dict], race_lap_start: int,
        sc_lap: Optional[int], vsc_lap: Optional[int], red_flag_lap: Optional[int],
        puncture: bool,
    ) -> float:
        """segments: {compound, laps, continued_from_age?: int}."""
        total = 0.0
        rl = race_lap_start
        for idx, seg in enumerate(segments):
            curve = self.deg_model.get_curve(driver, seg["compound"])
            nl = seg["laps"]
            if nl <= 0:
                continue
            cont = seg.get("continued_from_age")
            if cont is not None:
                total += curve.stint_time_continued(nl, cont, rl, self.fuel_effect, 1.0)
            else:
                total += curve.stint_time_vec(nl, rl, self.fuel_effect, 1.0)
            rl += nl
            if idx < len(segments) - 1:
                total += self._pit_cost_at_lap(rl, sc_lap, vsc_lap, red_flag_lap)
        if puncture:
            total += PUNCTURE_PENALTY
        return total

    def run_live_scenario(
        self,
        driver: str,
        current_lap: int,
        current_compound: str,
        stint_age: int,
        gap_ahead: float,
        gap_behind: float,
        sc_lap: Optional[int] = None,
        vsc_lap: Optional[int] = None,
        red_flag_lap: Optional[int] = None,
        puncture: bool = False,
        available_compounds: Optional[list[str]] = None,
    ) -> dict:
        """
        Optimal strategy from current race state with user-defined SC/VSC/RF/puncture.

        current_lap: 1-based F1 lap number. stint_age: laps already completed on current tyres.
        """
        c0 = current_compound.upper()
        comps = [x.upper() for x in (available_compounds or self.compounds)]
        if c0 not in comps:
            comps = [c0] + [c for c in comps if c != c0]

        R = max(1, self.total_laps - current_lap + 1)
        rl0 = max(0, current_lap - 1)

        max0 = COMPOUND_DEFAULTS.get(c0, COMPOUND_DEFAULTS["MEDIUM"]).get("max_stint", 35)
        max_first = min(R, max(0, max0 - stint_age))

        candidates: list[tuple[float, list[dict], str, int]] = []

        def gap_adjust(total_t: float, first_seg_laps: int, pit_lap_offset: int) -> float:
            """Undercut/overcut-style nudges from gaps to cars ahead/behind."""
            t = total_t
            if gap_behind < 1.2 and first_seg_laps > 3:
                t += 1.8
            if gap_behind < 0.8 and first_seg_laps > 5:
                t += 1.2
            if gap_ahead < 1.5 and first_seg_laps <= 2 and pit_lap_offset <= 2:
                t -= 1.0
            if gap_ahead < 1.0 and first_seg_laps == 0:
                t -= 0.8
            return t

        # 0-stop: finish on current tyres
        if R <= max_first and R > 0:
            segs = [{"compound": c0, "laps": R, "continued_from_age": stint_age}]
            raw = self._evaluate_live_segments(
                driver, segs, rl0, sc_lap, vsc_lap, red_flag_lap, puncture)
            adj = gap_adjust(raw, R, 0)
            candidates.append((adj, segs, f"{c0[0]}{R} (stay out)", max(0, len(segs) - 1)))

        # 1-stop from now
        for s0 in range(0, min(R, max_first) + 1):
            rem = R - s0
            if rem <= 0:
                continue
            if s0 > 0 and s0 < MIN_STINT_LAPS and rem < R:
                continue
            first_seg = {"compound": c0, "laps": s0, "continued_from_age": stint_age} if s0 > 0 else None
            pit_lap = rl0 + s0
            for c2 in comps:
                if c2 == c0 and s0 == 0:
                    continue
                m2 = COMPOUND_DEFAULTS.get(c2, COMPOUND_DEFAULTS["MEDIUM"]).get("max_stint", 40)
                if rem < MIN_STINT_LAPS or rem > m2:
                    continue
                segs = []
                if first_seg:
                    segs.append(first_seg)
                segs.append({"compound": c2, "laps": rem})
                raw = self._evaluate_live_segments(
                    driver, segs, rl0, sc_lap, vsc_lap, red_flag_lap, puncture)
                adj = gap_adjust(raw, s0, 0 if s0 == 0 else 1)
                label = (
                    f"Pit now · {c2[0]}{rem}" if s0 == 0
                    else f"{c0[0]}{s0}-{c2[0]}{rem}"
                )
                n_stops = max(0, len(segs) - 1)
                candidates.append((adj, segs, label, n_stops))

        # 2-stop from now (coarse grid) — not used for sprint distance
        if not self.sprint_race:
            for s0 in range(0, min(R, max_first) + 1, max(1, max_first // 4 or 1)):
                rem12 = R - s0
                if rem12 < 2 * MIN_STINT_LAPS:
                    continue
                first_seg = {"compound": c0, "laps": s0, "continued_from_age": stint_age} if s0 > 0 else None
                for c2 in comps:
                    for c3 in comps:
                        if len({c0, c2, c3}) < 2:
                            continue
                        for s1 in range(MIN_STINT_LAPS, min(rem12 - MIN_STINT_LAPS, 40) + 1, 4):
                            s2 = rem12 - s1
                            if s2 < MIN_STINT_LAPS:
                                continue
                            m2 = COMPOUND_DEFAULTS.get(c2, {}).get("max_stint", 30)
                            m3 = COMPOUND_DEFAULTS.get(c3, {}).get("max_stint", 30)
                            if s1 > m2 or s2 > m3:
                                continue
                            segs = []
                            if first_seg:
                                segs.append(first_seg)
                            segs.append({"compound": c2, "laps": s1})
                            segs.append({"compound": c3, "laps": s2})
                            raw = self._evaluate_live_segments(
                                driver, segs, rl0, sc_lap, vsc_lap, red_flag_lap, puncture)
                            adj = gap_adjust(raw, s0, 2)
                            label = f"{c0[0]}{s0}-{c2[0]}{s1}-{c3[0]}{s2}" if s0 else f"Pit·{c2[0]}{s1}-{c3[0]}{s2}"
                            candidates.append((adj, segs, label, max(0, len(segs) - 1)))

        if not candidates:
            segs = [{"compound": c0, "laps": min(R, max(MIN_STINT_LAPS, max_first)), "continued_from_age": stint_age}]
            raw = self._evaluate_live_segments(driver, segs, rl0, sc_lap, vsc_lap, red_flag_lap, puncture)
            candidates.append((raw, segs, "Fallback", max(0, len(segs) - 1)))

        candidates.sort(key=lambda x: x[0])
        seen_sig: set = set()
        top = []
        for c in candidates:
            segs = c[1]
            sig = tuple(
                (s["compound"], s["laps"], s.get("continued_from_age")) for s in segs)
            if sig in seen_sig:
                continue
            seen_sig.add(sig)
            top.append(c)
            if len(top) >= 12:
                break

        out = []
        for rank, (adj_t, segs, label, n_stops) in enumerate(top):
            stints_out = []
            for s in segs:
                stints_out.append({
                    "compound": s["compound"],
                    "laps": s["laps"],
                    "continued": s.get("continued_from_age") is not None,
                })
            raw_t = self._evaluate_live_segments(
                driver, segs, rl0, sc_lap, vsc_lap, red_flag_lap, puncture)
            out.append({
                "rank": rank + 1,
                "label": label,
                "n_stops": n_stops,
                "adjusted_score": round(adj_t, 2),
                "raw_race_time": round(raw_t, 2),
                "stints": stints_out,
            })

        return {
            "driver": driver,
            "current_lap": current_lap,
            "laps_remaining": R,
            "scenario": {
                "safety_car_lap": sc_lap,
                "vsc_lap": vsc_lap,
                "red_flag_lap": red_flag_lap,
                "puncture": puncture,
                "gap_ahead_s": gap_ahead,
                "gap_behind_s": gap_behind,
            },
            "recommendations": out,
            "meta": {
                "total_laps": self.total_laps,
                "circuit": self.circuit,
                "pit_loss_time": self.pit_loss,
                "sprint_race": self.sprint_race,
            },
        }


# ─── UNDERCUT / OVERCUT CALCULATOR ───────────────────────────────────────────

class UndercutCalculator:
    """Analyse gap evolution for undercut/overcut/stay-out scenarios."""

    def __init__(self, deg_model: TyreDegModel, circuit: str = "Australia"):
        params = _get_circuit(circuit)
        self.deg_model = deg_model
        self.pit_loss = params["pit_loss"]
        self.fuel_effect = params["fuel_effect"]
        self.total_laps = params["total_laps"]

    def analyze(
        self,
        driver_ahead: str,
        driver_behind: str,
        current_gap: float,
        current_lap: int,
        compound_ahead: str,
        compound_behind: str,
        stint_age_ahead: int,
        stint_age_behind: int,
        target_compound: str = "HARD",
    ) -> dict:
        remaining = self.total_laps - current_lap
        projection_len = min(remaining, 35)
        c_ahead = self.deg_model.get_curve(driver_ahead, compound_ahead)
        c_behind = self.deg_model.get_curve(driver_behind, compound_behind)
        c_ahead_new = self.deg_model.get_curve(driver_ahead, target_compound)
        c_behind_new = self.deg_model.get_curve(driver_behind, target_compound)

        stay = self._project_stay_out(
            c_ahead, c_behind,
            stint_age_ahead, stint_age_behind,
            current_gap, current_lap, projection_len)

        undercut = self._project_undercut(
            c_ahead, c_behind_new,
            stint_age_ahead,
            current_gap, current_lap, projection_len)

        overcut = self._project_overcut(
            c_ahead_new, c_behind,
            stint_age_behind,
            current_gap, current_lap, projection_len)

        finals = {k: v["final_gap"] for k, v in
                  {"stay_out": stay, "undercut": undercut, "overcut": overcut}.items()}
        rec = min(finals, key=lambda k: finals[k])

        return {
            "driver_ahead": driver_ahead,
            "driver_behind": driver_behind,
            "current_gap": current_gap,
            "current_lap": current_lap,
            "total_laps": self.total_laps,
            "scenarios": {
                "stay_out": stay,
                "undercut": undercut,
                "overcut": overcut,
            },
            "recommendation": rec,
            "tyre_info": {
                "ahead": {
                    "compound": compound_ahead,
                    "stint_age": stint_age_ahead,
                    "competitive_remaining": max(0, c_ahead.competitive_laps() - stint_age_ahead),
                },
                "behind": {
                    "compound": compound_behind,
                    "stint_age": stint_age_behind,
                    "competitive_remaining": max(0, c_behind.competitive_laps() - stint_age_behind),
                },
            },
        }

    def _lap_delta(self, curve_a: DegCurve, sa: int, curve_b: DegCurve, sb: int,
                   race_lap: int) -> float:
        """Time delta: positive means A is slower than B this lap → gap closes."""
        ta = curve_a.lap_time(sa) - self.fuel_effect * race_lap
        tb = curve_b.lap_time(sb) - self.fuel_effect * race_lap
        return ta - tb

    def _project_stay_out(self, c_a, c_b, sa, sb, gap, clap, n):
        gaps = [round(gap, 3)]
        g = gap
        for i in range(1, n + 1):
            delta = self._lap_delta(c_a, sa + i, c_b, sb + i, clap + i)
            g -= delta
            gaps.append(round(g, 3))
        ot = next((clap + i for i, v in enumerate(gaps) if v <= 0), None)
        return {"gaps": gaps, "overtake_lap": ot, "final_gap": gaps[-1],
                "description": "Both continue on current tyres"}

    def _project_undercut(self, c_a_old, c_b_new, sa, gap, clap, n):
        gaps = [round(gap, 3)]
        g = gap + self.pit_loss
        gaps.append(round(g, 3))
        for i in range(2, n + 1):
            ta = c_a_old.lap_time(sa + i) - self.fuel_effect * (clap + i)
            tb = c_b_new.lap_time(i - 1) - self.fuel_effect * (clap + i)
            g -= (ta - tb)
            gaps.append(round(g, 3))
        ot = next((clap + i for i, v in enumerate(gaps) if i > 0 and v <= 0), None)
        return {"gaps": gaps, "overtake_lap": ot, "final_gap": gaps[-1],
                "description": "Behind pits now, ahead stays out"}

    def _project_overcut(self, c_a_new, c_b_old, sb, gap, clap, n):
        delay = 3
        gaps = [round(gap, 3)]
        g = gap - self.pit_loss
        gaps.append(round(g, 3))
        for i in range(2, n + 1):
            if i <= delay + 1:
                ta = c_a_new.lap_time(i - 1) - self.fuel_effect * (clap + i)
                tb = c_b_old.lap_time(sb + i) - self.fuel_effect * (clap + i)
            elif i == delay + 2:
                g += self.pit_loss
                ta = c_a_new.lap_time(i - 1) - self.fuel_effect * (clap + i)
                tb = c_a_new.lap_time(0) - self.fuel_effect * (clap + i)
            else:
                b_stint = i - delay - 2
                ta = c_a_new.lap_time(i - 1) - self.fuel_effect * (clap + i)
                tb = c_a_new.lap_time(b_stint) - self.fuel_effect * (clap + i)
            g -= (ta - tb)
            gaps.append(round(g, 3))
        ot = next((clap + i for i, v in enumerate(gaps) if v <= 0), None)
        return {"gaps": gaps, "overtake_lap": ot, "final_gap": gaps[-1],
                "description": f"Ahead pits now, behind overcuts by {delay} laps"}
