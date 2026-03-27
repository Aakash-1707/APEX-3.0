import { useState, useEffect, useRef, useCallback } from "react";
import { T, apiFetch, Tag, Card, Spinner, ErrorBanner, useIsMobile } from "./theme";
import TelemetryTab from "./TelemetryTab";
import TyreDegTab from "./TyreDegTab";
import { QualiPredictionTab, RacePredictionTab } from "./PredictionTabs";
import StrategyTab from "./StrategyTab";
import StrategyChat from "./StrategyChat";

// ─── HEADER ───────────────────────────────────────────────────────────────────
function Header({mode, raceName, mobile}) {
  const [time,setTime]=useState(new Date());
  useEffect(()=>{const t=setInterval(()=>setTime(new Date()),1000);return()=>clearInterval(t);},[]);
  return(
    <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",
      padding:mobile?"8px 12px":"12px 28px",borderBottom:`1px solid ${T.border}`,
      background:`linear-gradient(180deg,${T.bg1},transparent)`,
      position:"sticky",top:0,zIndex:100,backdropFilter:"blur(8px)",
      flexWrap:mobile?"wrap":"nowrap",gap:mobile?"8px":undefined}}>
      <div style={{display:"flex",alignItems:"center",gap:mobile?"8px":"14px"}}>
        <div style={{display:"flex",alignItems:"center",gap:"8px",padding:"4px 10px 4px 6px",
          border:"1px solid rgba(0,229,255,0.35)",borderRadius:T.radiusSm,
          background:"rgba(0,229,255,0.05)",boxShadow:"0 0 12px rgba(0,229,255,0.12)"}}>
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path d="M9 1L17 9L9 17L1 9Z" stroke="#00e5ff" strokeWidth="1.5"
              fill="rgba(0,229,255,0.1)" style={{filter:"drop-shadow(0 0 4px rgba(0,229,255,0.6))"}}/>
            <path d="M9 5L13 9L9 13L5 9Z" fill="#00e5ff" opacity="0.7"/>
          </svg>
          <span style={{fontFamily:T.fontDisplay,fontSize:mobile?"11px":"13px",fontWeight:900,
            letterSpacing:"3px",color:"#00e5ff",textShadow:"0 0 8px rgba(0,229,255,0.7)"}}>
            APEX
          </span>
        </div>
        {!mobile && <div>
          <div style={{fontFamily:T.fontDisplay,fontSize:"12px",fontWeight:700,letterSpacing:"2px",color:T.text}}>
            F1 STRATEGY <span style={{color:T.red}}>INTELLIGENCE</span>
          </div>
          <div style={{fontFamily:T.fontMono,fontSize:"9px",letterSpacing:"2px",color:T.dim2,marginTop:"1px"}}>
            {raceName ? `2026 · ${raceName.toUpperCase()}` : "2026 SEASON"}
          </div>
        </div>}
      </div>
      <div style={{display:"flex",alignItems:"center",gap:"10px",fontFamily:T.fontMono,fontSize:"10px",letterSpacing:"2px",color:T.dim2}}>
        {mode && <Tag label={mode==="past"?"HISTORICAL":mode==="live"?"LIVE":"PREDICTION"}
          color={mode==="past"?"#27F4D2":mode==="live"?T.red:T.yellow}/>}
        <span>{time.toUTCString().slice(17,25)} UTC</span>
      </div>
    </div>
  );
}

// ─── RACE SELECTOR ────────────────────────────────────────────────────────────
function RaceSelector({calendar, selectedKey, onSelect}) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const selected = calendar.find(r=>r.meeting_key===selectedKey) || calendar[0];

  useEffect(()=>{
    const h = e => { if(ref.current&&!ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return ()=>document.removeEventListener("mousedown", h);
  },[]);

  if (!selected) return null;
  const past = calendar.filter(r=>r.mode==="past");
  const live = calendar.filter(r=>r.mode==="live");
  const upcoming = calendar.filter(r=>r.mode==="upcoming");

  const modeColor = m => m==="past"?T.green:m==="live"?T.red:T.yellow;
  const modeLabel = m => m==="past"?"HISTORICAL":m==="live"?"LIVE":"UPCOMING";

  const cancelColor = "#9e9e9e";

  return(
    <div ref={ref} style={{position:"relative",marginBottom:"20px"}}>
      <button onClick={()=>setOpen(o=>!o)} style={{
        display:"flex",alignItems:"center",gap:"14px",padding:"12px 18px",
        background:T.bg2,border:`1px solid ${open?T.red:T.border2}`,
        borderRadius:T.radius,cursor:"pointer",width:"100%",
        transition:"border-color .15s",outline:"none",textAlign:"left",
        boxShadow:open?`0 0 0 1px ${T.redDim}`:"none",
        opacity:selected.cancelled?0.88:1}}>
        <div style={{flex:1,minWidth:0}}>
          <div style={{display:"flex",alignItems:"center",gap:"8px",flexWrap:"wrap"}}>
            <span style={{fontFamily:T.fontDisplay,fontSize:"14px",fontWeight:700,
              color:selected.cancelled?T.dim2:T.text,letterSpacing:"1px"}}>
              {selected.name?.toUpperCase()}
            </span>
            {selected.cancelled && (
              <span style={{fontFamily:T.fontMono,fontSize:"8px",padding:"3px 8px",
                borderRadius:"3px",letterSpacing:"2px",
                background:"rgba(158,158,158,0.12)",
                border:`1px solid ${cancelColor}66`,
                color:cancelColor}}>
                CANCELLED
              </span>
            )}
            <span style={{fontFamily:T.fontMono,fontSize:"9px",padding:"2px 7px",
              borderRadius:"3px",letterSpacing:"1.5px",
              background:`${modeColor(selected.mode)}11`,
              border:`1px solid ${modeColor(selected.mode)}44`,
              color:modeColor(selected.mode)}}>
              {modeLabel(selected.mode)}
            </span>
          </div>
          <div style={{fontFamily:T.fontMono,fontSize:"9px",color:T.dim2,marginTop:"6px",letterSpacing:"1px",lineHeight:1.4}}>
            {selected.circuit_short_name} · {selected.location} · {new Date(selected.date_start).toLocaleDateString("en-GB",
              {day:"numeric",month:"short",year:"numeric"})}
          </div>
        </div>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none"
          style={{transform:open?"rotate(180deg)":"none",transition:"transform .2s",flexShrink:0}}>
          <path d="M2 4L6 8L10 4" stroke={T.dim2} strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      </button>

      {open&&(
        <div style={{position:"absolute",top:"calc(100% + 8px)",left:0,right:0,zIndex:200,
          background:T.bg1,border:`1px solid ${T.border2}`,borderRadius:T.radius,
          overflow:"hidden",boxShadow:"0 16px 40px rgba(0,0,0,0.6)",maxHeight:"min(72vh,520px)",overflowY:"auto",
          paddingBottom:"4px"}}>
          {[
            {items:past,label:`■ HISTORICAL — ${past.length} COMPLETE`,color:T.green},
            {items:live,label:`● LIVE`,color:T.red},
            {items:upcoming,label:`◇ UPCOMING — ${upcoming.length} REMAINING`,color:T.yellow},
          ].filter(g=>g.items.length>0).map(group=>(
            <div key={group.label}>
              <div style={{padding:"12px 16px 8px",fontFamily:T.fontMono,fontSize:"8px",
                letterSpacing:"3px",color:group.color,borderBottom:`1px solid ${T.border}`}}>
                {group.label}
              </div>
              {group.items.map(r=>(
                <button key={r.meeting_key} onClick={()=>{onSelect(r.meeting_key);setOpen(false);}} style={{
                  display:"flex",alignItems:"center",gap:"12px",width:"100%",padding:"11px 16px",
                  background:r.meeting_key===selectedKey?`${group.color}0a`:"transparent",
                  border:"none",borderBottom:`1px solid ${T.border}`,cursor:"pointer",textAlign:"left",
                  borderLeft:r.meeting_key===selectedKey?`3px solid ${group.color}`:"3px solid transparent",
                  opacity:r.cancelled?0.72:1}}>
                  <span style={{fontFamily:T.fontBody,fontSize:"12px",fontWeight:600,
                    color:r.cancelled?T.dim2:(r.meeting_key===selectedKey?T.text:"#aaa"),
                    flex:1,minWidth:0,textAlign:"left"}}>
                    {r.name}
                    {r.cancelled ? (
                      <span style={{display:"block",fontFamily:T.fontMono,fontSize:"8px",letterSpacing:"1.5px",
                        color:cancelColor,marginTop:"4px"}}>
                        CANCELLED
                      </span>
                    ) : null}
                  </span>
                  <span style={{fontFamily:T.fontMono,fontSize:"9px",color:T.dim2,flexShrink:0}}>
                    {r.circuit_short_name}
                  </span>
                  <span style={{fontFamily:T.fontMono,fontSize:"9px",color:T.dim2,flexShrink:0,minWidth:"52px",textAlign:"right"}}>
                    {new Date(r.date_start).toLocaleDateString("en-GB",{day:"numeric",month:"short"})}
                  </span>
                  {r.meeting_key===selectedKey&&<span style={{color:group.color,flexShrink:0}}>✓</span>}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── SESSION BAR ──────────────────────────────────────────────────────────────
function SessionBar({sessions, session, setSession, mobile}) {
  if (!sessions?.length) return null;
  return(
    <div style={{display:"flex",gap:"4px",marginBottom:"16px",
      overflowX:mobile?"auto":"visible",WebkitOverflowScrolling:"touch",
      paddingBottom:mobile?"4px":undefined}}>
      {sessions.map(s=>(
        <button key={s.session_key} onClick={()=>setSession(s)} style={{
          padding:mobile?"8px 12px":"5px 14px",fontFamily:T.fontMono,
          fontSize:mobile?"10px":"9px",letterSpacing:mobile?"1px":"2px",
          border:`1px solid ${session?.session_key===s.session_key?T.red:T.border2}`,
          borderRadius:T.radiusSm,color:session?.session_key===s.session_key?T.text:T.dim2,
          cursor:"pointer",textTransform:"uppercase",transition:"all .15s",whiteSpace:"nowrap",
          background:session?.session_key===s.session_key?"rgba(232,0,45,0.08)":"transparent",
          flexShrink:0}}>
          {s.session_name}
          {s.status==="completed"?" ✓":s.status==="live"?" ●":""}
        </button>
      ))}
    </div>
  );
}

// ─── TAB BAR ──────────────────────────────────────────────────────────────────
function TabBar({tab, setTab, sessions, mobile}) {
  const hasSprint = sessions?.some(s => s.session_name.toLowerCase().includes("sprint"));
  const tabs = ["Telemetry", "Tyre Deg"];
  
  if (hasSprint) {
    tabs.push("Sprint Quali Pred", "Sprint Race Pred");
  }
  tabs.push("Quali Prediction", "Race Prediction", "Strategy");

  return(
    <div style={{display:"flex",borderBottom:`1px solid ${T.border}`,marginBottom:"20px",
      overflowX:mobile?"auto":"visible",WebkitOverflowScrolling:"touch",
      paddingBottom:mobile?"2px":undefined}}>
      {tabs.map(t=>(
        <button key={t} onClick={()=>setTab(t)} style={{
          padding:mobile?"10px 12px":"10px 20px",fontFamily:T.fontMono,
          fontSize:mobile?"10px":"9px",letterSpacing:mobile?"1px":"2px",
          textTransform:"uppercase",background:"transparent",border:"none",
          borderBottom:`2px solid ${tab===t?T.red:"transparent"}`,
          color:tab===t?T.text:T.dim2,cursor:"pointer",transition:"all .15s",
          marginBottom:"-1px",whiteSpace:"nowrap",flexShrink:0}}>
          {t}
        </button>
      ))}
    </div>
  );
}

// ─── MAIN APP ─────────────────────────────────────────────────────────────────
export default function APEX() {
  const mobile = useIsMobile();
  const [calendar, setCalendar] = useState([]);
  const [selectedKey, setSelectedKey] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [activeSession, setActiveSession] = useState(null);
  const [drivers, setDrivers] = useState([]);
  const [tab, setTab] = useState("Race Prediction");
  const [predictions, setPredictions] = useState(null);
  const [modelMeta, setModelMeta] = useState(null);
  const [predLoading, setPredLoading] = useState(false);
  const [predError, setPredError] = useState(null);
  const [qualiNotReady, setQualiNotReady] = useState(false);
  const [apiOnline, setApiOnline] = useState(null);
  const [lastSourceMode, setLastSourceMode] = useState("auto");
  const [strategyResult, setStrategyResult] = useState(null);

  // Check API health
  useEffect(() => {
    apiFetch("/health").then(() => setApiOnline(true)).catch(() => setApiOnline(false));
  }, []);

  // Load calendar
  useEffect(() => {
    apiFetch("/calendar").then(cal => {
      setCalendar(cal);
      // Auto-select: first past race (most recent) or first upcoming
      const past = cal.filter(r => r.mode === "past");
      const live = cal.filter(r => r.mode === "live");
      if (live.length > 0) setSelectedKey(live[0].meeting_key);
      else if (past.length > 0) setSelectedKey(past[past.length - 1].meeting_key);
      else if (cal.length > 0) setSelectedKey(cal[0].meeting_key);
    }).catch(() => {});
  }, []);

  // Load sessions when meeting changes
  useEffect(() => {
    if (!selectedKey) return;
    setSessions([]); setActiveSession(null); setDrivers([]);
    setPredictions(null); setModelMeta(null); setPredError(null); setQualiNotReady(false);
    setStrategyResult(null);

    apiFetch(`/sessions/${selectedKey}`).then(async (sess) => {
      // If OpenF1 is rate-limited/restricted for a live weekend, auto-fallback
      // to the latest past meeting that actually has sessions.
      if ((!Array.isArray(sess) || sess.length === 0) && calendar.length > 0) {
        const pastCandidates = calendar
          .filter(r => r.meeting_key !== selectedKey && r.mode === "past")
          .sort((a, b) => new Date(b.date_end || 0) - new Date(a.date_end || 0));

        for (const c of pastCandidates) {
          try {
            const fallbackSess = await apiFetch(`/sessions/${c.meeting_key}`);
            if (Array.isArray(fallbackSess) && fallbackSess.length > 0) {
              setSelectedKey(c.meeting_key);
              setPredError(`Live weekend data is restricted by OpenF1 right now. Switched to ${c.name}.`);
              return;
            }
          } catch {
            // try next candidate
          }
        }
      }

      setSessions(Array.isArray(sess) ? sess : []);
      // Prefer main Race (not Sprint); some APIs use session_type only
      const race =
        (Array.isArray(sess) ? sess : []).find(s => s.session_name === "Race") ||
        (Array.isArray(sess) ? sess : []).find(
          s =>
            s.session_type === "Race" &&
            !(s.session_name || "").toLowerCase().includes("sprint")
        );
      setActiveSession(race || (Array.isArray(sess) ? sess[sess.length - 1] : null) || null);
    }).catch(() => {});
  }, [selectedKey, calendar]);

  // Load drivers: try active session first, then any completed session (OpenF1 often has no
  // driver list for a not-yet-run Race, but Quali/FP do).
  useEffect(() => {
    if (!sessions.length) {
      setDrivers([]);
      return;
    }
    if (!activeSession) {
      setDrivers([]);
      return;
    }
    let cancelled = false;
    const tryKeys = [];
    tryKeys.push(activeSession.session_key);
    const completed = [...sessions]
      .filter(s => s.status === "completed")
      .sort((a, b) => new Date(a.date_end || 0) - new Date(b.date_end || 0));
    for (const s of completed.reverse()) {
      if (s.session_key != null) tryKeys.push(s.session_key);
    }
    for (const s of sessions) {
      if (s.session_key != null) tryKeys.push(s.session_key);
    }
    const uniqueKeys = [...new Set(tryKeys)];

    (async () => {
      for (const sk of uniqueKeys) {
        if (cancelled) return;
        try {
          const list = await apiFetch(`/drivers/${sk}`);
          if (Array.isArray(list) && list.length > 0) {
            if (!cancelled) setDrivers(list);
            return;
          }
        } catch {
          /* try next session_key */
        }
      }
      if (!cancelled) setDrivers([]);
    })();
    return () => {
      cancelled = true;
    };
  }, [activeSession, sessions]);

  const runPrediction = useCallback(() => {
    if (!selectedKey || sessions.length === 0) return;

    // Determine which type of race/quali we are predicting based on the active tab
    const isSprintRace = tab === "Sprint Race Pred";
    const isSprintQuali = tab === "Sprint Quali Pred";
    const isSprintView = isSprintRace || isSprintQuali || activeSession?.session_name === "Sprint";
    
    // Find relevant qualifying session to use as base data
    const qualiSession = sessions.find(s =>
      isSprintView 
        ? s.session_name.includes("Sprint Shootout") || s.session_name.includes("Sprint Qualifying") 
        : s.session_name === "Qualifying"
    );

    // Find the relevant race session to predict for
    let targetRaceSession = activeSession;
    if (isSprintRace) {
        targetRaceSession = sessions.find(s => s.session_name.includes("Sprint") && !s.session_name.includes("Shootout") && !s.session_name.includes("Qualifying"));
    } else if (tab === "Race Prediction") {
        targetRaceSession = sessions.find(s => s.session_name === "Race");
    }

    const selected = calendar.find(r => r.meeting_key === selectedKey);
    const circuit = selected?.circuit_short_name || "Australia";

    const hasSprint = sessions.some(s => s.session_name.toLowerCase().includes("sprint"));
    let sourceMode = "auto";
    if (!hasSprint) {
      if (tab === "Quali Prediction") sourceMode = "fp_only";
      else if (tab === "Race Prediction") sourceMode = "full_quali";
    } else {
      if (tab === "Sprint Quali Pred") sourceMode = "fp_only";              // FP1 only weekend
      else if (tab === "Sprint Race Pred") sourceMode = "sprint_quali";     // FP1 + Sprint Quali
      else if (tab === "Quali Prediction") sourceMode = "sprint_quali";     // Practice + Sprint Quali
      else if (tab === "Race Prediction") sourceMode = "full_quali";        // All data incl. full quali
    }

    setPredLoading(true); setPredError(null); setPredictions(null); setQualiNotReady(false);

    const abortController = new AbortController();

    apiFetch("/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: abortController.signal,
      body: JSON.stringify({
        session_key: qualiSession?.status === "completed" ? qualiSession.session_key : null,
        race_session_key: targetRaceSession?.session_key || null,
        meeting_key: selectedKey,
        circuit: circuit,
        n_sims: 100000,
        source_mode: sourceMode,
      }),
    })
    .then(data => {
      setPredictions(data.predictions);
      setModelMeta({...data.model_meta, prediction_basis: data.prediction_basis});
      setLastSourceMode(sourceMode);
      setPredLoading(false);
    })
    .catch(e => {
      if (e.name !== "AbortError") {
        setPredError(e.message);
        setPredLoading(false);
      }
    });

    return () => abortController.abort();
  }, [activeSession, selectedKey, sessions, calendar, tab]);

  const selected = calendar.find(r => r.meeting_key === selectedKey);
  const mode = selected?.mode || "upcoming";
  const hasSessionData = Array.isArray(sessions) && sessions.length > 0;

  return(
    <div style={{minHeight:"100vh",background:T.bg0,color:T.text,fontFamily:T.fontBody,overflowX:"hidden"}}>
      <div style={{position:"fixed",inset:0,
        background:"repeating-linear-gradient(0deg,transparent,transparent 3px,rgba(0,0,0,0.04) 3px,rgba(0,0,0,0.04) 4px)",
        pointerEvents:"none",zIndex:9999}}/>
      <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Orbitron:wght@700;900&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet"/>

      <Header mode={mode} raceName={selected?.name} mobile={mobile}/>

      {apiOnline === false && (
        <div style={{background:"rgba(232,0,45,0.06)",borderBottom:`1px solid ${T.redBorder}`,
          padding:"10px 28px",display:"flex",alignItems:"center",gap:"12px"}}>
          <span style={{color:T.red,fontSize:"14px"}}>⚠</span>
          <span style={{fontFamily:T.fontMono,fontSize:"9px",color:T.dim2,letterSpacing:"1.5px"}}>
            APEX BACKEND OFFLINE · Run: <span style={{color:T.text}}>uvicorn api:app --reload --port 8000</span>
          </span>
        </div>
      )}

      <div style={{maxWidth:"1440px",margin:"0 auto",padding:mobile?"12px 8px":"20px 24px"}}>
        {calendar.length > 0 && (
          <RaceSelector calendar={calendar} selectedKey={selectedKey} onSelect={setSelectedKey}/>
        )}

        {mode==="upcoming" && (
          <div style={{marginBottom:"16px",padding:"10px 16px",
            background:"rgba(255,215,0,0.04)",border:"1px solid rgba(255,215,0,0.2)",
            borderRadius:T.radius,display:"flex",alignItems:"center",gap:"12px"}}>
            <div style={{width:"6px",height:"6px",borderRadius:"50%",background:T.yellow,
              boxShadow:`0 0 6px ${T.yellow}`,flexShrink:0}}/>
            <span style={{fontFamily:T.fontMono,fontSize:"9px",letterSpacing:"2px",color:T.yellow}}>
              PREDICTION MODE — {selected?.name?.toUpperCase()} HAS NOT YET OCCURRED
            </span>
          </div>
        )}

        {mode==="live" && (
          <div style={{marginBottom:"16px",padding:"10px 16px",
            background:"rgba(232,0,45,0.04)",border:"1px solid rgba(232,0,45,0.2)",
            borderRadius:T.radius,display:"flex",alignItems:"center",gap:"12px"}}>
            <div style={{width:"6px",height:"6px",borderRadius:"50%",background:T.red,
              boxShadow:`0 0 6px ${T.red}`,flexShrink:0,animation:"pulse 1.5s infinite"}}/>
            <span style={{fontFamily:T.fontMono,fontSize:"9px",letterSpacing:"2px",color:T.red}}>
              LIVE WEEKEND — {selected?.name?.toUpperCase()}
            </span>
            <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}`}</style>
          </div>
        )}

        {predError && <ErrorBanner message={predError} onRetry={()=>setSelectedKey(selectedKey)} style={{marginBottom:"16px"}}/>}

        <SessionBar sessions={sessions} session={activeSession} setSession={setActiveSession} mobile={mobile}/>
        {!hasSessionData && selectedKey && (
          <Card style={{marginBottom:"16px",border:`1px solid ${T.border2}`}}>
            <div style={{fontFamily:T.fontMono,fontSize:"10px",letterSpacing:"1.5px",color:T.dim2,lineHeight:1.6}}>
              Session data is unavailable right now.
              This usually happens when OpenF1 restricts public access during a live session.
              Select a completed meeting to continue.
            </div>
          </Card>
        )}
        <div style={{display:"flex",alignItems:"center",gap:"10px",marginBottom:"8px",flexWrap:"wrap"}}>
          <button
            onClick={runPrediction}
            disabled={!selectedKey || !hasSessionData || predLoading}
            style={{
              fontFamily:T.fontMono,fontSize:mobile?"11px":"9px",letterSpacing:"2px",
              padding:mobile?"10px 20px":"5px 14px",
              borderRadius:T.radiusSm,
              border:`1px solid ${predLoading ? T.border2 : T.red}`,
              background:predLoading ? "transparent" : "rgba(232,0,45,0.12)",
              color:predLoading ? T.dim2 : T.red,
              cursor:predLoading ? "default" : "pointer",
              textTransform:"uppercase"
            }}
          >
            {predLoading ? "RUNNING..." : "PREDICT"}
          </button>
        </div>
        {hasSessionData && <TabBar tab={tab} setTab={setTab} sessions={sessions} mobile={mobile}/>}

        {hasSessionData && tab==="Telemetry" && (
          <TelemetryTab sessionKey={activeSession?.session_key} drivers={drivers}
            mode={activeSession?.status || mode}/>
        )}
        {hasSessionData && tab==="Tyre Deg" && (
          <TyreDegTab sessionKey={activeSession?.session_key} drivers={drivers}
            mode={activeSession?.status || mode}/>
        )}
        {hasSessionData && tab==="Sprint Quali Pred" && (
          predLoading
            ? <Spinner label={`Running ${(100000).toLocaleString()} Monte Carlo simulations...`}/>
            : <QualiPredictionTab
                sessionKey={sessions.find(s=>s.session_name.includes("Sprint Shootout") || s.session_name.includes("Sprint Qualifying"))?.session_key}
                drivers={drivers} mode={mode}
                predictions={predictions}
                modelMeta={modelMeta}
                sourceMode={lastSourceMode}
                qualiNotReady={false}/>
        )}
        {hasSessionData && tab==="Sprint Race Pred" && (
          predLoading
            ? <Spinner label={`Running ${(100000).toLocaleString()} Monte Carlo simulations...`}/>
            : <RacePredictionTab
                raceSessionKey={sessions.find(s=>s.session_name.includes("Sprint") && !s.session_name.includes("Shootout") && !s.session_name.includes("Qualifying"))?.session_key}
                drivers={drivers} mode={mode}
                predictions={predictions} modelMeta={modelMeta}
                sourceMode={lastSourceMode}
                qualiNotReady={qualiNotReady}/>
        )}
        {hasSessionData && tab==="Quali Prediction" && (
          predLoading
            ? <Spinner label={`Running ${(100000).toLocaleString()} Monte Carlo simulations...`}/>
            : <QualiPredictionTab
                sessionKey={sessions.find(s=>s.session_name==="Qualifying")?.session_key}
                drivers={drivers} mode={mode}
                predictions={predictions}
                modelMeta={modelMeta}
                sourceMode={lastSourceMode}
                qualiNotReady={false}/>
        )}
        {hasSessionData && tab==="Race Prediction" && (
          predLoading
            ? <Spinner label={`Running ${(100000).toLocaleString()} Monte Carlo simulations...`}/>
            : <RacePredictionTab
                raceSessionKey={sessions.find(s=>s.session_name==="Race")?.session_key}
                drivers={drivers} mode={mode}
                predictions={predictions} modelMeta={modelMeta}
                sourceMode={lastSourceMode}
                qualiNotReady={qualiNotReady}/>
        )}
        {hasSessionData && tab==="Strategy" && (
          <StrategyTab
            meetingKey={selectedKey}
            sessions={sessions}
            drivers={drivers}
            circuit={selected?.circuit_short_name || "Australia"}
            mode={mode}
            sessionType={activeSession?.session_name?.includes("Sprint") ? "Sprint" : "Race"}
            strategyResult={strategyResult}
            onSimResult={setStrategyResult}/>
        )}
      </div>

      <StrategyChat
        meetingKey={selectedKey}
        circuit={selected?.circuit_short_name || "Australia"}
        simulationResult={strategyResult}/>
    </div>
  );
}
