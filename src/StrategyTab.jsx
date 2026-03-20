// APEX Strategy Tab — Tyre Strategy Intelligence
import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { T, apiFetch, Card, SectionHeader, Tag, Spinner, ErrorBanner, useIsMobile } from "./theme";

// ─── STRATEGY COMPARISON PANEL ───────────────────────────────────────────────

function StrategyBars({ strategies, teamColor }) {
  if (!strategies?.length) return null;
  const maxProb = Math.max(...strategies.map(s => s.probability), 1);
  return (
    <div style={{display:"flex",flexDirection:"column",gap:"6px"}}>
      {strategies.slice(0, 5).map((s, i) => (
        <div key={i} style={{display:"flex",alignItems:"center",gap:"8px"}}>
          <div style={{flex:1}}>
            <div style={{display:"flex",alignItems:"center",gap:"6px",marginBottom:"3px"}}>
              <span style={{fontFamily:T.fontMono,fontSize:"10px",fontWeight:700,
                color:i===0?T.yellow:T.text,minWidth:"42px"}}>
                {s.probability}%
              </span>
              <div style={{display:"flex",gap:"2px"}}>
                {s.stints.map((st, j) => {
                  const color = T.tyres[st.compound] || T.dim;
                  return (
                    <span key={j} style={{
                      fontSize:"9px",fontFamily:T.fontMono,fontWeight:700,
                      padding:"1px 5px",borderRadius:"3px",
                      background:`${color}22`,border:`1px solid ${color}55`,
                      color:color,letterSpacing:"0.5px"}}>
                      {st.compound[0]}{st.laps}
                    </span>
                  );
                })}
              </div>
              <span style={{fontFamily:T.fontMono,fontSize:"8px",color:T.dim2,marginLeft:"auto"}}>
                {s.n_stops}S · P{s.avg_position}
              </span>
            </div>
            <div style={{height:"4px",background:T.bg3,borderRadius:"2px",overflow:"hidden"}}>
              <div style={{
                width:`${(s.probability / maxProb) * 100}%`,
                height:"100%",
                background:i===0
                  ? `linear-gradient(90deg, ${teamColor}, ${teamColor}88)`
                  : `${teamColor}55`,
                borderRadius:"2px",
                transition:"width .3s ease"}}/>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function DriverStrategyCard({ data, mobile }) {
  const teamColor = data.team_colour ? `#${data.team_colour}` : T.dim;
  const best = data.strategies?.[0];
  const gp = data.grid_pos;
  const alloc = data.tyre_allocation || {};
  return (
    <Card style={{padding:mobile?"10px":"14px"}}>
      <div style={{display:"flex",alignItems:"center",gap:"10px",marginBottom:"10px"}}>
        {gp && (
          <span style={{fontFamily:T.fontDisplay,fontSize:"18px",fontWeight:700,
            color:gp<=3?T.yellow:gp<=10?T.accent:T.dim2,minWidth:"32px",textAlign:"center"}}>
            P{gp}
          </span>
        )}
        <div style={{width:"3px",height:"28px",background:teamColor,borderRadius:"2px"}}/>
        <div>
          <div style={{fontFamily:T.fontBody,fontSize:"13px",fontWeight:600,color:T.text}}>
            {data.driver}
          </div>
          <div style={{fontFamily:T.fontMono,fontSize:"9px",color:T.dim2}}>
            {data.team}
          </div>
        </div>
        {best && (
          <div style={{marginLeft:"auto",textAlign:"right"}}>
            <div style={{fontFamily:T.fontMono,fontSize:"8px",color:T.dim2,letterSpacing:"2px"}}>OPTIMAL</div>
            <div style={{fontFamily:T.fontDisplay,fontSize:"13px",fontWeight:700,color:T.yellow}}>
              {best.label}
            </div>
          </div>
        )}
      </div>
      {Object.keys(alloc).length > 0 && (
        <div style={{display:"flex",gap:"6px",marginBottom:"8px"}}>
          {["SOFT","MEDIUM","HARD"].map(c => {
            const a = alloc[c];
            if (!a) return null;
            const color = T.tyres[c] || T.dim;
            return (
              <span key={c} style={{fontFamily:T.fontMono,fontSize:"8px",
                padding:"2px 5px",borderRadius:"3px",
                background:`${color}15`,border:`1px solid ${color}44`,color,
                opacity:a.remaining>0?1:0.35}}>
                {c[0]}: {a.remaining}/{a.allocated}
              </span>
            );
          })}
        </div>
      )}
      <StrategyBars strategies={data.strategies} teamColor={teamColor}/>
    </Card>
  );
}

// ─── GAP EVOLUTION CHART ─────────────────────────────────────────────────────

function GapChart({ undercutData, mobile }) {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!undercutData?.scenarios || !canvasRef.current) return;
    const script = document.createElement("script");
    script.src = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js";
    script.onload = () => {
      if (!window.Chart) return;
      chartRef.current?.destroy?.();

      const scenarios = undercutData.scenarios;
      const maxLen = Math.max(
        scenarios.stay_out?.gaps?.length || 0,
        scenarios.undercut?.gaps?.length || 0,
        scenarios.overcut?.gaps?.length || 0,
      );
      const labels = Array.from({length: maxLen}, (_, i) => undercutData.current_lap + i);

      const datasets = [
        {
          label: "Stay Out",
          data: scenarios.stay_out?.gaps || [],
          borderColor: T.dim2,
          borderWidth: 1.5,
          borderDash: [4, 2],
          pointRadius: 0,
          tension: 0.3,
          fill: false,
        },
        {
          label: "Undercut",
          data: scenarios.undercut?.gaps || [],
          borderColor: T.green,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
          fill: false,
        },
        {
          label: "Overcut",
          data: scenarios.overcut?.gaps || [],
          borderColor: T.orange,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
          fill: false,
        },
      ];

      chartRef.current = new window.Chart(canvasRef.current.getContext("2d"), {
        type: "line",
        data: { labels, datasets },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          plugins: {
            legend: {
              display: true,
              labels: {color: T.dim2, font: {family: "'DM Mono'", size: 9}},
            },
            tooltip: {
              bodyFont: {family: "'DM Mono'"}, backgroundColor: T.bg2,
              borderColor: T.border2, borderWidth: 1,
              callbacks: {label: c => `${c.dataset.label}: ${c.parsed.y?.toFixed(2)}s`},
            },
          },
          scales: {
            x: {
              grid: {color: "rgba(255,255,255,0.04)"},
              ticks: {color: T.dim2, font: {family: "'DM Mono'", size: 9}},
              title: {display: true, text: "LAP", color: T.dim2, font: {family: "'DM Mono'", size: 9}},
            },
            y: {
              grid: {color: "rgba(255,255,255,0.06)"},
              ticks: {color: T.dim2, font: {family: "'DM Mono'", size: 9},
                callback: v => `${v.toFixed(1)}s`},
              title: {display: true, text: "GAP (s)", color: T.dim2,
                font: {family: "'DM Mono'", size: 9}},
            },
          },
        },
      });
    };
    document.head.appendChild(script);
    return () => { chartRef.current?.destroy?.(); try { document.head.removeChild(script); } catch(e) {} };
  }, [undercutData]);

  return <canvas ref={canvasRef}/>;
}

// ─── TYRE LIFE PANEL ─────────────────────────────────────────────────────────

function TyreLifePanel({ degModel, mobile }) {
  if (!degModel || !Object.keys(degModel).length) {
    return (
      <div style={{
        padding: "12px 14px",
        textAlign: "left",
        fontFamily: T.fontMono,
        fontSize: "9px",
        color: T.dim2,
        lineHeight: 1.65,
        letterSpacing: "0.3px",
      }}>
        <div style={{ marginBottom: "10px", color: T.text, fontWeight: 600, letterSpacing: "1px" }}>
          NO TYRE CURVES YET
        </div>
        <div style={{ marginBottom: "8px" }}>
          Run <strong style={{ color: T.red }}>RUN STRATEGY SIM</strong> above first.
        </div>
        <div>
          Competitive laps = how many laps the model keeps you within ~2s/lap of fresh-tyre pace (per driver, S / M / H).
        </div>
      </div>
    );
  }
  const drivers = Object.entries(degModel).slice(0, 10);
  return (
    <div style={{display:"flex",flexDirection:"column",gap:"6px"}}>
      {drivers.map(([driver, compounds]) => (
        <div key={driver} style={{display:"flex",alignItems:"center",gap:"8px"}}>
          <span style={{fontFamily:T.fontMono,fontSize:"10px",color:T.dim2,
            width:mobile?"80px":"120px",overflow:"hidden",textOverflow:"ellipsis",
            whiteSpace:"nowrap"}}>{driver.split(" ").pop()}</span>
          <div style={{flex:1,display:"flex",gap:"4px"}}>
            {Object.entries(compounds).map(([comp, data]) => {
              const color = T.tyres[comp] || T.dim;
              const pct = Math.min(100, (data.competitive_laps / 40) * 100);
              return (
                <div key={comp} style={{flex:1}}>
                  <div style={{display:"flex",justifyContent:"space-between",marginBottom:"2px"}}>
                    <span style={{fontFamily:T.fontMono,fontSize:"8px",color:color}}>{comp[0]}</span>
                    <span style={{fontFamily:T.fontMono,fontSize:"8px",color:T.dim2}}>{data.competitive_laps}L</span>
                  </div>
                  <div style={{height:"6px",background:T.bg3,borderRadius:"3px",overflow:"hidden"}}>
                    <div style={{width:`${pct}%`,height:"100%",background:color,borderRadius:"3px",opacity:0.7}}/>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── ACTUAL VS PREDICTED COMPARISON ───────────────────────────────────────────

function ActualVsPredicted({ predicted, actual, mobile }) {
  if (!actual?.available || !actual?.drivers?.length) return null;
  const predByDriver = Object.fromEntries((predicted?.drivers || []).map(d => [d.driver, d]));
  const actualByDriver = Object.fromEntries(actual.drivers.map(d => [d.driver, d]));

  const drivers = actual.drivers.filter(a => predByDriver[a.driver]).slice(0, 8);
  if (!drivers.length) return null;

  return (
    <div style={{display:"flex",flexDirection:"column",gap:"8px"}}>
      {drivers.map((act, i) => {
        const pred = predByDriver[act.driver];
        const best = pred?.strategies?.[0];
        const predStints = best?.stints || [];
        const actStints = act.stints || [];
        const posMatch = pred && best?.avg_position && Math.round(best.avg_position) === act.position;
        const stratMatch = predStints.length === actStints.length &&
          predStints.every((p, j) => actStints[j] && p.compound === actStints[j].compound);
        return (
          <div key={act.driver} style={{
            display:"flex",alignItems:"center",gap:mobile?"8px":"12px",
            padding:"8px 10px",background:T.bg3,borderRadius:T.radiusSm,
            border:`1px solid ${T.border}`}}>
            <span style={{fontFamily:T.fontMono,fontSize:mobile?"9px":"10px",
              color:T.text,width:mobile?"70px":"100px",overflow:"hidden",
              textOverflow:"ellipsis",whiteSpace:"nowrap"}}>
              {act.driver.split(" ").pop()}
            </span>
            <div style={{flex:1,display:"flex",flexDirection:"column",gap:"4px"}}>
              <div style={{display:"flex",alignItems:"center",gap:"6px"}}>
                <span style={{fontFamily:T.fontMono,fontSize:"8px",color:T.dim2,letterSpacing:"1px"}}>PRED</span>
                {predStints.map((s,j) => (
                  <span key={j} style={{
                    fontSize:"8px",fontFamily:T.fontMono,fontWeight:700,
                    padding:"1px 4px",borderRadius:"2px",
                    background:`${(T.tyres[s.compound]||T.dim)}22`,
                    border:`1px solid ${(T.tyres[s.compound]||T.dim)}55`,
                    color:T.tyres[s.compound]||T.dim}}>
                    {s.compound[0]}{s.laps}
                  </span>
                ))}
                {best && (
                  <span style={{fontFamily:T.fontMono,fontSize:"8px",color:T.dim2}}>
                    P{Math.round(best.avg_position)}
                  </span>
                )}
              </div>
              <div style={{display:"flex",alignItems:"center",gap:"6px"}}>
                <span style={{fontFamily:T.fontMono,fontSize:"8px",color:T.dim2,letterSpacing:"1px"}}>ACT</span>
                {actStints.map((s,j) => (
                  <span key={j} style={{
                    fontSize:"8px",fontFamily:T.fontMono,fontWeight:700,
                    padding:"1px 4px",borderRadius:"2px",
                    background:`${(T.tyres[s.compound]||T.dim)}22`,
                    border:`1px solid ${(T.tyres[s.compound]||T.dim)}55`,
                    color:T.tyres[s.compound]||T.dim}}>
                    {s.compound[0]}{s.laps}
                  </span>
                ))}
                <span style={{fontFamily:T.fontMono,fontSize:"8px",
                  color:posMatch?T.green:T.text,fontWeight:posMatch?700:400}}>
                  P{act.position}
                </span>
              </div>
            </div>
            <div style={{display:"flex",gap:"4px"}}>
              {stratMatch && <span style={{fontSize:"10px",color:T.green}} title="Strategy match">✓</span>}
              {posMatch && <span style={{fontSize:"10px",color:T.green}} title="Position match">P</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── EVENT IMPACT PANEL ──────────────────────────────────────────────────────

function EventImpactPanel({ meta }) {
  if (!meta) return null;
  const items = [
    {label: "SAFETY CAR", value: `${(meta.sc_probability * 100).toFixed(0)}%`, color: T.yellow,
     desc: "Bunches the field — free pit stop window"},
    {label: "VIRTUAL SC", value: `${(meta.vsc_probability * 100).toFixed(0)}%`, color: T.orange,
     desc: "Reduced pit loss during VSC period"},
    {label: "RED FLAG", value: "~4%", color: T.red,
     desc: "Free tyre change for all drivers"},
    {label: "PUNCTURE", value: "~6%", color: T.purple,
     desc: "Forces unplanned pit stop"},
  ];
  return (
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"8px"}}>
      {items.map(item => (
        <div key={item.label} style={{padding:"10px",background:T.bg3,borderRadius:T.radiusSm,
          border:`1px solid ${T.border}`}}>
          <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:"4px"}}>
            <span style={{fontFamily:T.fontMono,fontSize:"8px",letterSpacing:"2px",color:item.color}}>
              {item.label}
            </span>
            <span style={{fontFamily:T.fontDisplay,fontSize:"14px",fontWeight:700,color:item.color}}>
              {item.value}
            </span>
          </div>
          <div style={{fontFamily:T.fontMono,fontSize:"8px",color:T.dim2}}>{item.desc}</div>
        </div>
      ))}
    </div>
  );
}

// ─── MAIN STRATEGY TAB ──────────────────────────────────────────────────────

export default function StrategyTab({ meetingKey, sessions, drivers, circuit, mode, onSimResult, sessionType, strategyResult }) {
  const mobile = useIsMobile();
  const [simResult, setSimResult] = useState(null);
  const [simLoading, setSimLoading] = useState(false);
  const [simError, setSimError] = useState(null);

  const displayResult = simResult || (strategyResult?.meeting_key === meetingKey ? strategyResult : null);

  const [undercutResult, setUndercutResult] = useState(null);
  const [ucLoading, setUcLoading] = useState(false);

  const [actualData, setActualData] = useState(null);
  const [actualLoading, setActualLoading] = useState(false);

  const [strategyFor, setStrategyFor] = useState("Race");
  const [selectedDrivers, setSelectedDrivers] = useState([]);
  const [driverA, setDriverA] = useState("");
  const [driverB, setDriverB] = useState("");
  const [gap, setGap] = useState(1.5);
  const [currentLap, setCurrentLap] = useState(15);
  const [compoundA, setCompoundA] = useState("MEDIUM");
  const [compoundB, setCompoundB] = useState("MEDIUM");
  const [stintAgeA, setStintAgeA] = useState(10);
  const [stintAgeB, setStintAgeB] = useState(10);
  const [targetCompound, setTargetCompound] = useState("HARD");

  const [liveDriverDn, setLiveDriverDn] = useState(null);
  const [liveLap, setLiveLap] = useState(20);
  const [liveCompound, setLiveCompound] = useState("MEDIUM");
  const [liveStintAge, setLiveStintAge] = useState(8);
  const [liveGapAhead, setLiveGapAhead] = useState(1.5);
  const [liveGapBehind, setLiveGapBehind] = useState(2.0);
  const [liveScLap, setLiveScLap] = useState("");
  const [liveVscLap, setLiveVscLap] = useState("");
  const [liveRfLap, setLiveRfLap] = useState("");
  const [livePuncture, setLivePuncture] = useState(false);
  const [liveResult, setLiveResult] = useState(null);
  const [liveLoading, setLiveLoading] = useState(false);
  const [liveError, setLiveError] = useState(null);

  const allDrivers = drivers || [];

  const meetingHasSprintRace = useMemo(() => {
    if (!sessions?.length) return false;
    return sessions.some((s) => {
      const n = (s.session_name || "").toLowerCase();
      if (n.includes("qualifying") || n.includes("shootout")) return false;
      if (s.session_type === "Sprint") return true;
      return n.includes("sprint");
    });
  }, [sessions]);

  useEffect(() => {
    if (!meetingHasSprintRace && strategyFor === "Sprint") {
      setStrategyFor("Race");
    }
  }, [meetingHasSprintRace, strategyFor]);

  const toggleDriver = useCallback((dn) => {
    setSelectedDrivers(prev => {
      if (prev.includes(dn)) return prev.filter(d => d !== dn);
      if (prev.length >= 4) return prev;
      return [...prev, dn];
    });
  }, []);

  useEffect(() => {
    if (allDrivers.length > 0 && selectedDrivers.length === 0) {
      const sorted = [...allDrivers].sort((a,b) => (a.driver_number || 99) - (b.driver_number || 99));
      setSelectedDrivers(sorted.slice(0, 4).map(d => d.driver_number));
    }
  }, [allDrivers]);

  useEffect(() => {
    if (liveDriverDn == null && selectedDrivers.length > 0) {
      setLiveDriverDn(selectedDrivers[0]);
    }
  }, [selectedDrivers, liveDriverDn]);

  const driverNames = (displayResult?.drivers || []).map(d => d.driver);

  useEffect(() => {
    if (driverNames.length >= 2 && !driverA && !driverB) {
      setDriverA(driverNames[0]);
      setDriverB(driverNames[1]);
    }
  }, [driverNames, driverA, driverB]);

  useEffect(() => {
    if (!meetingKey || !displayResult) return;
    setActualLoading(true);
    setActualData(null);
    apiFetch(`/strategy/actual/${meetingKey}?session_type=${strategyFor}`)
      .then(data => setActualData(data.available ? data : null))
      .catch(() => setActualData(null))
      .finally(() => setActualLoading(false));
  }, [meetingKey, strategyFor, displayResult?.meeting_key]);

  const sType = strategyFor;

  const runSimulation = useCallback(async () => {
    if (!meetingKey) return;
    setSimLoading(true); setSimError(null);
    try {
      const body = {
        meeting_key: meetingKey,
        circuit: circuit || "Australia",
        n_sims: 30000,
        available_compounds: ["SOFT", "MEDIUM", "HARD"],
        session_type: sType,
      };
      if (selectedDrivers.length > 0) {
        body.driver_numbers = selectedDrivers;
      }
      const data = await apiFetch("/strategy/simulate", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body),
      });
      setSimResult(data);
      if (onSimResult) onSimResult(data);
    } catch(e) {
      setSimError(e.message);
    } finally {
      setSimLoading(false);
    }
  }, [meetingKey, circuit, selectedDrivers, sType]);

  const runUndercut = useCallback(async () => {
    if (!meetingKey || !driverA || !driverB) return;
    setUcLoading(true);
    try {
      const data = await apiFetch("/strategy/undercut", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          meeting_key: meetingKey,
          circuit: circuit || "Australia",
          driver_ahead: driverA,
          driver_behind: driverB,
          current_gap: gap,
          current_lap: currentLap,
          compound_ahead: compoundA,
          compound_behind: compoundB,
          stint_age_ahead: stintAgeA,
          stint_age_behind: stintAgeB,
          target_compound: targetCompound,
        }),
      });
      setUndercutResult(data);
    } catch(e) {
      console.error("Undercut error:", e);
    } finally {
      setUcLoading(false);
    }
  }, [meetingKey, circuit, driverA, driverB, gap, currentLap,
      compoundA, compoundB, stintAgeA, stintAgeB, targetCompound]);

  const runLiveScenario = useCallback(async () => {
    if (!meetingKey || liveDriverDn == null) return;
    setLiveLoading(true); setLiveError(null);
    const optInt = (s) => {
      const n = parseInt(String(s).trim(), 10);
      return Number.isFinite(n) ? n : null;
    };
    try {
      const body = {
        meeting_key: meetingKey,
        circuit: circuit || "Australia",
        driver_number: liveDriverDn,
        current_lap: Math.max(1, parseInt(liveLap, 10) || 1),
        current_compound: liveCompound,
        stint_age: Math.max(0, parseInt(liveStintAge, 10) || 0),
        gap_ahead: parseFloat(liveGapAhead) || 0,
        gap_behind: parseFloat(liveGapBehind) || 0,
        puncture: livePuncture,
        session_type: sType,
        available_compounds: ["SOFT", "MEDIUM", "HARD"],
      };
      const sc = optInt(liveScLap);
      const vsc = optInt(liveVscLap);
      const rf = optInt(liveRfLap);
      if (sc != null) body.safety_car_lap = sc;
      if (vsc != null) body.vsc_lap = vsc;
      if (rf != null) body.red_flag_lap = rf;
      const data = await apiFetch("/strategy/live-scenario", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body),
      });
      setLiveResult(data);
    } catch (e) {
      setLiveError(e.message);
      setLiveResult(null);
    } finally {
      setLiveLoading(false);
    }
  }, [meetingKey, circuit, liveDriverDn, liveLap, liveCompound, liveStintAge,
      liveGapAhead, liveGapBehind, liveScLap, liveVscLap, liveRfLap, livePuncture, sType]);

  return (
    <div>
      {mode === "upcoming" && !displayResult && (
        <Card style={{marginBottom:"16px",padding:"16px",textAlign:"center"}}>
          <div style={{fontFamily:T.fontMono,fontSize:"10px",color:T.dim2,letterSpacing:"2px",marginBottom:"12px"}}>
            PRE-RACE MONTE CARLO NEEDS PRACTICE DATA · TRY ANYWAY OR USE LIVE SCENARIO BELOW
          </div>
          <button onClick={runSimulation} disabled={simLoading || !meetingKey}
            style={{padding:"8px 20px",fontFamily:T.fontMono,fontSize:"10px",letterSpacing:"2px",
              border:`1px solid ${T.red}`,borderRadius:T.radiusSm,
              background:"rgba(232,0,45,0.12)",color:T.red,cursor:"pointer",textTransform:"uppercase"}}>
            {simLoading ? "RUNNING..." : "RUN STRATEGY SIM"}
          </button>
        </Card>
      )}
      {/* Driver Selection */}
      <Card style={{padding:mobile?"10px":"14px",marginBottom:"16px"}}>
        <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:"10px",flexWrap:"wrap",gap:"8px"}}>
          <div style={{display:"flex",alignItems:"center",gap:"10px",flexWrap:"wrap"}}>
            <span style={{fontFamily:T.fontMono,fontSize:"9px",letterSpacing:"2px",color:T.dim2}}>
              SIMULATE FOR
            </span>
            <div style={{display:"flex",gap:"4px"}}>
              <button type="button" onClick={()=>setStrategyFor("Race")}
                style={{
                  padding:"4px 10px",fontFamily:T.fontMono,fontSize:"9px",letterSpacing:"1px",
                  border:`1px solid ${strategyFor==="Race"?T.red:T.border}`,
                  borderRadius:T.radiusSm,
                  background:strategyFor==="Race"?"rgba(232,0,45,0.15)":"transparent",
                  color:strategyFor==="Race"?T.text:T.dim2,
                  cursor:"pointer",textTransform:"uppercase",
                }}>
                Race
              </button>
              {meetingHasSprintRace && (
                <button type="button" onClick={()=>setStrategyFor("Sprint")}
                  style={{
                    padding:"4px 10px",fontFamily:T.fontMono,fontSize:"9px",letterSpacing:"1px",
                    border:`1px solid ${strategyFor==="Sprint"?T.orange:T.border}`,
                    borderRadius:T.radiusSm,
                    background:strategyFor==="Sprint"?"rgba(255,145,0,0.15)":"transparent",
                    color:strategyFor==="Sprint"?T.text:T.dim2,
                    cursor:"pointer",textTransform:"uppercase",
                  }}>
                  Sprint
                </button>
              )}
            </div>
            <span style={{fontFamily:T.fontMono,fontSize:"9px",color:T.dim2}}>
              · Grid from {strategyFor==="Race" || !meetingHasSprintRace ? "Qualifying" : "Sprint Qualifying"}
            </span>
          </div>
          <span style={{fontFamily:T.fontMono,fontSize:"9px",color:selectedDrivers.length>=4?T.yellow:T.dim2}}>
            {selectedDrivers.length}/4 SELECTED
          </span>
        </div>
        {allDrivers.length === 0 && (
          <div style={{fontFamily:T.fontMono,fontSize:"9px",color:T.yellow,letterSpacing:"1px",marginBottom:"10px",padding:"8px 10px",background:"rgba(255,215,0,0.06)",border:`1px solid rgba(255,215,0,0.2)`,borderRadius:T.radiusSm}}>
            No driver entry list from OpenF1 or FastF1 for the selected session. Pick another session or check that FastF1 is installed on the backend (<code style={{color:T.text}}>pip install fastf1</code>).
          </div>
        )}
        <div style={{display:"flex",flexWrap:"wrap",gap:"6px"}}>
          {allDrivers.map(d => {
            const dn = d.driver_number;
            const isSelected = selectedDrivers.includes(dn);
            const teamColor = d.team_colour ? `#${d.team_colour}` : T.dim;
            const disabled = !isSelected && selectedDrivers.length >= 4;
            return (
              <button key={dn} onClick={() => toggleDriver(dn)}
                disabled={disabled}
                style={{
                  display:"flex",alignItems:"center",gap:"5px",
                  padding:mobile?"6px 10px":"4px 10px",
                  fontFamily:T.fontMono,fontSize:mobile?"10px":"9px",
                  border:`1px solid ${isSelected?teamColor:T.border}`,
                  borderRadius:T.radiusSm,
                  background:isSelected?`${teamColor}18`:"transparent",
                  color:isSelected?T.text:disabled?T.dim2+"60":T.dim2,
                  cursor:disabled?"default":"pointer",
                  opacity:disabled?0.4:1,
                  transition:"all .15s",
                }}>
                <span style={{width:"8px",height:"8px",borderRadius:"2px",
                  background:isSelected?teamColor:T.border,flexShrink:0}}/>
                {(d.full_name||d.name_acronym||`#${dn}`).split(" ").pop()}
              </button>
            );
          })}
        </div>
      </Card>

      {/* Controls */}
      <div style={{display:"flex",alignItems:"center",gap:"10px",marginBottom:"16px",flexWrap:"wrap"}}>
        <button onClick={runSimulation} disabled={simLoading || !meetingKey || selectedDrivers.length===0}
          style={{padding:mobile?"10px 20px":"6px 16px",fontFamily:T.fontMono,
            fontSize:mobile?"11px":"9px",letterSpacing:"2px",
            border:`1px solid ${simLoading?T.border2:T.red}`,borderRadius:T.radiusSm,
            background:simLoading?"transparent":"rgba(232,0,45,0.12)",
            color:simLoading?T.dim2:T.red,cursor:simLoading?"default":"pointer",
            textTransform:"uppercase"}}>
          {simLoading ? "SIMULATING..." : `RUN STRATEGY SIM · ${selectedDrivers.length} DRIVER${selectedDrivers.length!==1?"S":""}`}
        </button>
        {displayResult?.meta && (
          <div style={{display:"flex",gap:"6px",flexWrap:"wrap",alignItems:"center"}}>
            <Tag label={(displayResult.session_type||sType)==="Sprint"?"SPRINT STRATEGY":"RACE STRATEGY"} color={(displayResult.session_type||sType)==="Sprint"?T.orange:T.red}/>
            <Tag label={`${(displayResult.meta.n_sims||30000).toLocaleString()} SIMS`} color={T.red}/>
            <Tag label={`${displayResult.meta.total_laps} LAPS`} color={T.blue}/>
            <Tag label={`PIT LOSS ${displayResult.meta.pit_loss_time}s`} color={T.yellow}/>
          </div>
        )}
      </div>

      {simLoading && <Spinner label={`Running 30,000 strategy sims for ${selectedDrivers.length} driver${selectedDrivers.length!==1?"s":""}...`}/>}
      {simError && <ErrorBanner message={simError} onRetry={runSimulation}/>}

      {displayResult?.meta?.historical_stop_profile && (
        <Card style={{
          marginBottom: "16px",
          padding: mobile ? "10px" : "12px",
          border: `1px solid ${T.blue}44`,
          background: `${T.blue}0c`,
        }}>
          <div style={{ fontFamily: T.fontMono, fontSize: "9px", letterSpacing: "1px", color: T.dim2, marginBottom: "6px" }}>
            LAST YEAR AT THIS TRACK · STOP PATTERN BIAS APPLIED
          </div>
          <div style={{ fontFamily: T.fontMono, fontSize: mobile ? "10px" : "11px", color: T.text, lineHeight: 1.5 }}>
            {(() => {
              const h = displayResult.meta.historical_stop_profile;
              if (h.session_kind === "sprint") {
                const dom = h.dominant_pits === 0 ? "no-stop" : "1-stop";
                const extra = h.clamped_from_two_plus ? " (2+ stops mapped to 1-stop bias)" : "";
                return `${h.source_year} sprint: ${h.zero_stop_pct}% no-stop · ${h.one_stop_pct}% 1-stop · ${h.two_plus_pct}% 2+ · dominant ${dom}${extra} · n=${h.sample_size}`;
              }
              const dom = h.dominant_pits === 1 ? "1-stop" : "2-stop";
              const extra = h.clamped_from_three_plus ? " (3+ stops mapped to 2-stop bias)" : "";
              return `${h.source_year}: ${h.one_stop_pct}% 1-stop · ${h.two_stop_pct}% 2-stop · ${h.three_plus_pct}% 3+ · dominant ${dom}${extra} · n=${h.sample_size}`;
            })()}
          </div>
        </Card>
      )}

      <SectionHeader title="Live race scenario · dynamic strategy"/>
      <Card style={{marginBottom:"16px",padding:mobile?"10px":"14px"}}>
        <div style={{fontFamily:T.fontMono,fontSize:"9px",color:T.dim2,marginBottom:"12px",lineHeight:1.5}}>
          Set race state and optional SC / VSC / red flag laps. Gaps to cars ahead and behind adjust ranking
          (undercut / overcut pressure). Leave event laps blank if not active. Works without running the pre-race sim.
        </div>
        <div style={{display:"grid",gridTemplateColumns:mobile?"1fr":"repeat(auto-fill,minmax(140px,1fr))",
          gap:"10px",marginBottom:"12px"}}>
          <div>
            <label style={labelStyle}>DRIVER</label>
            <select value={liveDriverDn ?? ""} onChange={e=>setLiveDriverDn(parseInt(e.target.value,10))}
              style={{...selectStyle,width:"100%"}}>
              {(selectedDrivers.length?allDrivers.filter(d=>selectedDrivers.includes(d.driver_number)):allDrivers)
                .map(d=><option key={d.driver_number} value={d.driver_number}>
                  {d.name_acronym||d.driver_number}
                </option>)}
            </select>
          </div>
          <div>
            <label style={labelStyle}>CURRENT LAP</label>
            <input type="number" min={1} value={liveLap} onChange={e=>setLiveLap(parseInt(e.target.value,10)||1)}
              style={{...inputStyle,width:"100%"}}/>
          </div>
          <div>
            <label style={labelStyle}>TYRE</label>
            <select value={liveCompound} onChange={e=>setLiveCompound(e.target.value)} style={{...selectStyle,width:"100%"}}>
              {["SOFT","MEDIUM","HARD"].map(c=><option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label style={labelStyle}>STINT AGE (LAPS)</label>
            <input type="number" min={0} value={liveStintAge} onChange={e=>setLiveStintAge(parseInt(e.target.value,10)||0)}
              style={{...inputStyle,width:"100%"}}/>
          </div>
          <div>
            <label style={labelStyle}>GAP AHEAD (s)</label>
            <input type="number" step="0.1" value={liveGapAhead} onChange={e=>setLiveGapAhead(parseFloat(e.target.value)||0)}
              style={{...inputStyle,width:"100%"}}/>
          </div>
          <div>
            <label style={labelStyle}>GAP BEHIND (s)</label>
            <input type="number" step="0.1" value={liveGapBehind} onChange={e=>setLiveGapBehind(parseFloat(e.target.value)||0)}
              style={{...inputStyle,width:"100%"}}/>
          </div>
          <div>
            <label style={labelStyle}>SC LAP (opt)</label>
            <input type="number" placeholder="—" value={liveScLap} onChange={e=>setLiveScLap(e.target.value)}
              style={{...inputStyle,width:"100%"}}/>
          </div>
          <div>
            <label style={labelStyle}>VSC LAP (opt)</label>
            <input type="number" placeholder="—" value={liveVscLap} onChange={e=>setLiveVscLap(e.target.value)}
              style={{...inputStyle,width:"100%"}}/>
          </div>
          <div>
            <label style={labelStyle}>RED FLAG LAP (opt)</label>
            <input type="number" placeholder="—" value={liveRfLap} onChange={e=>setLiveRfLap(e.target.value)}
              style={{...inputStyle,width:"100%"}}/>
          </div>
          <div style={{display:"flex",alignItems:"flex-end",gap:"8px"}}>
            <label style={{...labelStyle,display:"flex",alignItems:"center",gap:"6px",cursor:"pointer"}}>
              <input type="checkbox" checked={livePuncture} onChange={e=>setLivePuncture(e.target.checked)}/>
              PUNCTURE PENALTY
            </label>
          </div>
        </div>
        <button onClick={runLiveScenario} disabled={liveLoading || !meetingKey || liveDriverDn==null || allDrivers.length===0}
          style={{padding:mobile?"10px 18px":"6px 16px",fontFamily:T.fontMono,fontSize:mobile?"11px":"9px",
            letterSpacing:"2px",border:`1px solid ${T.blue}`,borderRadius:T.radiusSm,
            background:"rgba(68,138,255,0.1)",color:T.blue,cursor:liveLoading?"default":"pointer",
            textTransform:"uppercase"}}>
          {liveLoading ? "COMPUTING..." : "RUN LIVE SCENARIO"}
        </button>
        {liveError && <div style={{marginTop:"10px",color:T.red,fontFamily:T.fontMono,fontSize:"10px"}}>{liveError}</div>}
        {liveResult?.recommendations?.length > 0 && (
          <div style={{marginTop:"14px"}}>
            <div style={{fontFamily:T.fontMono,fontSize:"8px",color:T.dim2,marginBottom:"8px"}}>
              {liveResult.laps_remaining} LAPS REMAINING · RANKED BY ADJUSTED SCORE (LOWER = BETTER)
            </div>
            {liveResult.recommendations.map((r) => (
              <div key={r.rank} style={{
                display:"flex",alignItems:"center",gap:"8px",flexWrap:"wrap",
                padding:"8px",marginBottom:"6px",background:r.rank===1?`${T.blue}12`:T.bg3,
                border:`1px solid ${r.rank===1?T.blue:T.border}`,borderRadius:T.radiusSm}}>
                <span style={{fontFamily:T.fontDisplay,fontSize:"14px",fontWeight:700,color:r.rank===1?T.blue:T.dim2}}>
                  #{r.rank}
                </span>
                <span style={{fontFamily:T.fontMono,fontSize:"10px",fontWeight:700,color:T.text}}>{r.label}</span>
                <div style={{display:"flex",gap:"3px"}}>
                  {r.stints.map((st,j) => (
                    <span key={j} style={{
                      fontSize:"8px",fontFamily:T.fontMono,fontWeight:700,
                      padding:"1px 4px",borderRadius:"2px",
                      background:`${(T.tyres[st.compound]||T.dim)}22`,
                      border:`1px solid ${(T.tyres[st.compound]||T.dim)}55`,
                      color:T.tyres[st.compound]||T.dim}}>
                      {st.compound[0]}{st.laps}{st.continued?"*":""}
                    </span>
                  ))}
                </div>
                <span style={{fontFamily:T.fontMono,fontSize:"8px",color:T.dim2,marginLeft:"auto"}}>
                  {r.n_stops}S · raw {r.raw_race_time}s · adj {r.adjusted_score}
                </span>
              </div>
            ))}
            <div style={{fontFamily:T.fontMono,fontSize:"7px",color:T.dim2,marginTop:"6px"}}>
              *continued stint on current tyres
            </div>
          </div>
        )}
      </Card>

      {displayResult && (
        <>
          {/* Strategy comparison + event impact */}
          {/* flex-start avoids grid stretch: right column was matching left column height → huge blank gap */}
          <div style={{
            display: "flex",
            flexDirection: mobile ? "column" : "row",
            flexWrap: "wrap",
            gap: "16px",
            marginBottom: "12px",
            alignItems: "flex-start",
            alignContent: "flex-start",
          }}>
            <div style={{
              flex: mobile ? "none" : "2 1 0",
              minWidth: mobile ? "100%" : 0,
              width: mobile ? "100%" : undefined,
            }}>
              <SectionHeader title={`Optimal strategies · ${(displayResult.session_type||sType)==="Sprint"?"Sprint":"Race"}`}/>
              <div style={{display:"grid",gridTemplateColumns:mobile?"1fr":"1fr 1fr",gap:"10px"}}>
                {(displayResult.drivers || []).map(d => (
                  <DriverStrategyCard key={d.driver} data={d} mobile={mobile}/>
                ))}
              </div>
            </div>
            <div style={{
              flex: mobile ? "none" : "0 1 320px",
              maxWidth: mobile ? "100%" : "400px",
              minWidth: mobile ? "100%" : "260px",
              width: mobile ? "100%" : undefined,
              alignSelf: "flex-start",
            }}>
              <SectionHeader title="Event probabilities"/>
              <Card style={{marginBottom:"12px"}}>
                <EventImpactPanel meta={displayResult.meta}/>
              </Card>
              <SectionHeader title="Actual vs predicted"/>
              <Card style={{ marginBottom: 0 }}>
                {actualLoading ? (
                  <div style={{padding:"14px 16px",textAlign:"center",fontFamily:T.fontMono,fontSize:"9px",color:T.dim2}}>
                    Loading actual results...
                  </div>
                ) : actualData?.available ? (
                  <ActualVsPredicted predicted={displayResult} actual={actualData} mobile={mobile}/>
                ) : (
                  <div style={{padding:"14px 16px",textAlign:"center",fontFamily:T.fontMono,fontSize:"9px",color:T.dim2}}>
                    {(displayResult.session_type||sType)==="Sprint" ? "Sprint" : "Race"} not yet completed
                  </div>
                )}
              </Card>
            </div>
          </div>

          {/* Full-width tyre panel: avoids huge dead space beside a short sidebar in the row above */}
          <div style={{ marginBottom: "16px" }}>
            <SectionHeader title="Tyre life · competitive laps"/>
            <Card style={{ padding: mobile ? "10px 12px" : "12px 16px" }}>
              <TyreLifePanel degModel={displayResult.deg_model} mobile={mobile}/>
            </Card>
          </div>

          {/* Undercut/Overcut analysis */}
          <SectionHeader title="Undercut / overcut analysis"/>
          <Card style={{marginBottom:"16px",padding:mobile?"10px":"16px"}}>
            <div style={{display:"flex",gap:mobile?"8px":"16px",marginBottom:"16px",
              flexWrap:"wrap",alignItems:"flex-end"}}>
              <div>
                <label style={labelStyle}>DRIVER AHEAD</label>
                <select value={driverA} onChange={e=>setDriverA(e.target.value)} style={selectStyle}>
                  {driverNames.map(n=><option key={n} value={n}>{n}</option>)}
                </select>
              </div>
              <div>
                <label style={labelStyle}>DRIVER BEHIND</label>
                <select value={driverB} onChange={e=>setDriverB(e.target.value)} style={selectStyle}>
                  {driverNames.map(n=><option key={n} value={n}>{n}</option>)}
                </select>
              </div>
              <div>
                <label style={labelStyle}>GAP (s)</label>
                <input type="number" value={gap} onChange={e=>setGap(parseFloat(e.target.value)||0)}
                  step="0.1" style={inputStyle}/>
              </div>
              <div>
                <label style={labelStyle}>CURRENT LAP</label>
                <input type="number" value={currentLap} onChange={e=>setCurrentLap(parseInt(e.target.value)||1)}
                  style={inputStyle}/>
              </div>
              <div>
                <label style={labelStyle}>COMPOUND A</label>
                <select value={compoundA} onChange={e=>setCompoundA(e.target.value)} style={selectStyle}>
                  {["SOFT","MEDIUM","HARD"].map(c=><option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label style={labelStyle}>COMPOUND B</label>
                <select value={compoundB} onChange={e=>setCompoundB(e.target.value)} style={selectStyle}>
                  {["SOFT","MEDIUM","HARD"].map(c=><option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label style={labelStyle}>STINT AGE A</label>
                <input type="number" value={stintAgeA} onChange={e=>setStintAgeA(parseInt(e.target.value)||0)}
                  style={inputStyle}/>
              </div>
              <div>
                <label style={labelStyle}>STINT AGE B</label>
                <input type="number" value={stintAgeB} onChange={e=>setStintAgeB(parseInt(e.target.value)||0)}
                  style={inputStyle}/>
              </div>
              <div>
                <label style={labelStyle}>PIT TO</label>
                <select value={targetCompound} onChange={e=>setTargetCompound(e.target.value)} style={selectStyle}>
                  {["SOFT","MEDIUM","HARD"].map(c=><option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <button onClick={runUndercut} disabled={ucLoading || !driverA || !driverB}
                style={{padding:mobile?"10px 16px":"6px 14px",fontFamily:T.fontMono,
                  fontSize:mobile?"11px":"9px",letterSpacing:"2px",
                  border:`1px solid ${T.green}`,borderRadius:T.radiusSm,
                  background:"rgba(0,230,118,0.08)",color:T.green,
                  cursor:"pointer",textTransform:"uppercase",alignSelf:"flex-end"}}>
                {ucLoading ? "..." : "ANALYZE"}
              </button>
            </div>

            {undercutResult && (
              <div style={{display:"grid",gridTemplateColumns:mobile?"1fr":"1fr 300px",gap:"16px"}}>
                <div style={{height:mobile?"220px":"300px",position:"relative"}}>
                  <GapChart undercutData={undercutResult} mobile={mobile}/>
                </div>
                <div>
                  <div style={{fontFamily:T.fontMono,fontSize:"9px",letterSpacing:"2px",
                    color:T.dim2,marginBottom:"10px"}}>SCENARIO SUMMARY</div>
                  {Object.entries(undercutResult.scenarios).map(([key, sc]) => {
                    const isRec = undercutResult.recommendation === key;
                    const colorMap = {stay_out: T.dim2, undercut: T.green, overcut: T.orange};
                    return (
                      <div key={key} style={{
                        padding:"10px",marginBottom:"6px",borderRadius:T.radiusSm,
                        background:isRec?`${colorMap[key]}11`:T.bg3,
                        border:`1px solid ${isRec?colorMap[key]:T.border}`}}>
                        <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:"4px"}}>
                          <span style={{fontFamily:T.fontMono,fontSize:"10px",fontWeight:700,
                            color:colorMap[key],textTransform:"uppercase"}}>
                            {key.replace("_"," ")}
                            {isRec && " ★"}
                          </span>
                          <span style={{fontFamily:T.fontDisplay,fontSize:"14px",fontWeight:700,
                            color:sc.final_gap>0?T.red:T.green}}>
                            {sc.final_gap>0?"+":""}{sc.final_gap.toFixed(1)}s
                          </span>
                        </div>
                        <div style={{fontFamily:T.fontMono,fontSize:"8px",color:T.dim2}}>
                          {sc.overtake_lap ? `Overtake on lap ${sc.overtake_lap}` : "No overtake projected"}
                        </div>
                      </div>
                    );
                  })}
                  {undercutResult.tyre_info && (
                    <div style={{marginTop:"10px",padding:"8px",background:T.bg3,borderRadius:T.radiusSm,
                      border:`1px solid ${T.border}`}}>
                      <div style={{fontFamily:T.fontMono,fontSize:"8px",letterSpacing:"2px",
                        color:T.dim2,marginBottom:"6px"}}>TYRE STATUS</div>
                      {["ahead","behind"].map(who => {
                        const info = undercutResult.tyre_info[who];
                        const color = T.tyres[info.compound] || T.dim;
                        return (
                          <div key={who} style={{display:"flex",alignItems:"center",gap:"6px",marginBottom:"4px"}}>
                            <span style={{fontFamily:T.fontMono,fontSize:"9px",color:T.dim2,
                              width:"50px",textTransform:"uppercase"}}>{who}</span>
                            <span style={{fontFamily:T.fontMono,fontSize:"9px",fontWeight:700,
                              padding:"1px 5px",borderRadius:"3px",
                              background:`${color}22`,border:`1px solid ${color}55`,color}}>
                              {info.compound[0]}
                            </span>
                            <span style={{fontFamily:T.fontMono,fontSize:"9px",color:T.dim2}}>
                              {info.stint_age}L old · {info.competitive_remaining}L remaining
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

const labelStyle = {
  display:"block",fontFamily:T.fontMono,fontSize:"8px",letterSpacing:"2px",
  color:T.dim2,marginBottom:"4px",textTransform:"uppercase",
};
const inputStyle = {
  width:"70px",padding:"5px 8px",fontFamily:T.fontMono,fontSize:"11px",
  background:T.bg3,border:`1px solid ${T.border2}`,borderRadius:T.radiusSm,
  color:T.text,outline:"none",
};
const selectStyle = {
  padding:"5px 8px",fontFamily:T.fontMono,fontSize:"11px",
  background:T.bg3,border:`1px solid ${T.border2}`,borderRadius:T.radiusSm,
  color:T.text,outline:"none",
};
