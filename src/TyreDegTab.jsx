// APEX Tyre Degradation Tab
import { useState, useEffect, useRef, useCallback } from "react";
import { T, apiFetch, Card, SectionHeader, Spinner, ErrorBanner, useIsMobile } from "./theme";

/** Same rules as Chart.js dataset build: in-range laps only, pit-out excluded, duration or full sectors. */
function lapHasPlottedTime(l, maxLap) {
  if (!l || l.is_pit_out) return false;
  const n = l.lap_number;
  if (n == null || n < 1 || n > maxLap) return false;
  let duration = l.lap_duration;
  if (!duration || duration <= 0) {
    const s1 = l.s1, s2 = l.s2, s3 = l.s3;
    if (s1 != null && s2 != null && s3 != null) duration = s1 + s2 + s3;
  }
  return !!(duration && duration > 0);
}

export default function TyreDegTab({ sessionKey, drivers, mode }) {
  const mobile = useIsMobile();
  const [stints, setStints] = useState(null);
  const [lapData, setLapData] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const chartRef = useRef(null);
  const chartInst = useRef(null);
  const [activeDrivers, setActiveDrivers] = useState([]);

  const fetchData = useCallback(async () => {
    if (!sessionKey || mode === "upcoming") return;
    setLoading(true); setError(null);
    try {
      const stintData = await apiFetch(`/stints/${sessionKey}`);
      setStints(stintData);

      // Get first 5 drivers by driver number
      const driverNums = Object.keys(stintData).map(Number).slice(0, 5);
      setActiveDrivers(driverNums);

      // Fetch lap data for those drivers
      const laps = {};
      await Promise.all(driverNums.map(async (dn) => {
        try {
          const l = await apiFetch(`/laps/${sessionKey}/${dn}`);
          laps[dn] = l;
        } catch(e) {}
      }));
      setLapData(laps);
    } catch(e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [sessionKey, mode]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Chart rendering
  useEffect(() => {
    // Stint keys drive the chart; drivers only enrich labels (fallback to #number).
    if (!stints || !chartRef.current) return;
    const script = document.createElement("script");
    script.src = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js";
    script.onload = () => {
      if (!window.Chart) return;

      const maxLap = Math.max(...Object.values(stints).flat().map(s => s.lap_end || 0), 1);
      const labels = Array.from({length: maxLap}, (_, i) => i + 1);

      const datasets = activeDrivers
        .filter(dn => lapData[dn])
        .map((dn, idx) => {
          const d = drivers?.find(dr => dr.driver_number === dn);
          const lapTimes = new Array(maxLap).fill(null);
          (lapData[dn] || []).forEach(l => {
            if (!lapHasPlottedTime(l, maxLap)) return;
            let duration = l.lap_duration;
            if (!duration || duration <= 0) {
              const s1 = l.s1, s2 = l.s2, s3 = l.s3;
              if (s1 != null && s2 != null && s3 != null) duration = s1 + s2 + s3;
            }
            if (duration && duration > 0) lapTimes[l.lap_number - 1] = duration;
          });
          return {
            label: d?.name_acronym || `#${dn}`,
            data: lapTimes,
            borderColor: `#${d?.team_colour || "ffffff"}`,
            borderWidth: 1.5, backgroundColor: "transparent",
            pointRadius: 0, fill: false, tension: 0.3, spanGaps: true,
          };
        })
        .filter(ds => ds.data.some(v => v != null));

      chartInst.current?.destroy?.();
      if (datasets.length === 0) {
        chartInst.current = null;
        return;
      }
      chartInst.current = new window.Chart(chartRef.current.getContext("2d"), {
        type: "line", data: { labels, datasets },
        options: {
          responsive:true, maintainAspectRatio:false, animation:false,
          plugins: {
            legend: { display:true, labels:{color:T.dim2, font:{family:"'DM Mono'",size:9}} },
            tooltip: { bodyFont:{family:"'DM Mono'"}, backgroundColor:T.bg2,
              borderColor:T.border2, borderWidth:1,
              callbacks:{label:c=>`${c.dataset.label}: ${c.parsed.y?.toFixed(3)}s`} },
          },
          scales: {
            x: { grid:{color:"rgba(255,255,255,0.04)"}, ticks:{color:T.dim2,font:{family:"'DM Mono'",size:9}},
                 title:{display:true,text:"LAP",color:T.dim2,font:{family:"'DM Mono'",size:9}} },
            y: { grid:{color:"rgba(255,255,255,0.06)"},
                 ticks:{color:T.dim2,font:{family:"'DM Mono'",size:9},callback:v=>`${v.toFixed(1)}s`},
                 title:{display:true,text:"LAP TIME (s)",color:T.dim2,font:{family:"'DM Mono'",size:9}} },
          },
        },
      });
    };
    document.head.appendChild(script);
    return () => { chartInst.current?.destroy?.(); try{document.head.removeChild(script);}catch(e){} };
  }, [stints, activeDrivers, lapData, drivers]);

  if (mode === "upcoming") return (
    <Card><div style={{textAlign:"center",padding:"40px",fontFamily:T.fontMono,fontSize:"10px",color:T.dim2,letterSpacing:"2px"}}>
      TYRE DATA AVAILABLE AFTER SESSION
    </div></Card>
  );
  if (loading) return <Spinner label="Fetching stint data (OpenF1 → FastF1)..."/>;
  if (error) return <ErrorBanner message={error} onRetry={fetchData}/>;
  if (!stints) return null;

  const allDriverNums = Object.keys(stints).map(Number);
  if (allDriverNums.length === 0) {
    return (
      <Card>
        <div style={{textAlign:"center",padding:"40px",fontFamily:T.fontMono,fontSize:mobile?"11px":"10px",color:T.dim2,letterSpacing:"2px",lineHeight:1.6}}>
          TYRE / STINT DATA NOT AVAILABLE
          <div style={{fontSize:"9px",marginTop:"12px",opacity:0.85,letterSpacing:"1px"}}>
            OpenF1 and FastF1 returned no stint data for this session (session may not be complete or not published).
          </div>
        </div>
      </Card>
    );
  }

  const maxLap = Math.max(...Object.values(stints).flat().map(s => s.lap_end || 0), 1);
  // Match chart: only active drivers and laps that fall within stint-derived maxLap (see lapHasPlottedTime).
  const hasAnyLapTimes = activeDrivers.some(dn =>
    (lapData[dn] || []).some(l => lapHasPlottedTime(l, maxLap)),
  );

  return(
    <div>
      <div style={{display:"grid",gridTemplateColumns:mobile?"1fr":"1fr 1fr",gap:"16px",marginBottom:"16px"}}>
        <Card>
          <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:"12px",flexWrap:"wrap",gap:"8px"}}>
            <SectionHeader title="Lap time degradation"/>
            <div style={{display:"flex",gap:"4px",flexWrap:"wrap"}}>
              {allDriverNums.slice(0,10).map(dn => {
                const d = drivers?.find(dr => dr.driver_number === dn);
                const active = activeDrivers.includes(dn);
                return(
                  <button key={dn} onClick={async () => {
                    const next = active ? activeDrivers.filter(x=>x!==dn) : [...activeDrivers,dn];
                    setActiveDrivers(next);
                    if (!active && !lapData[dn]) {
                      try {
                        const l = await apiFetch(`/laps/${sessionKey}/${dn}`);
                        setLapData(prev => ({...prev, [dn]: l}));
                      } catch(e) {}
                    }
                  }} style={{
                    padding:mobile?"6px 10px":"3px 8px",fontFamily:T.fontMono,
                    fontSize:mobile?"10px":"8px",letterSpacing:"1px",
                    border:`1px solid ${active?`#${d?.team_colour||"e8002d"}`:T.border2}`,
                    borderRadius:T.radiusSm,
                    color:active?`#${d?.team_colour||"e8002d"}`:T.dim,
                    background:active?`#${d?.team_colour||"e8002d"}22`:"transparent",
                    cursor:"pointer",textTransform:"uppercase"}}>
                    {d?.name_acronym || dn}
                  </button>
                );
              })}
            </div>
          </div>
          <div style={{height:mobile?"220px":"280px",position:"relative"}}>
            <canvas ref={chartRef}/>
            {!hasAnyLapTimes && (
              <div style={{position:"absolute",inset:0,display:"flex",alignItems:"center",justifyContent:"center",
                background:"rgba(0,0,0,0.3)",fontFamily:T.fontMono,fontSize:mobile?"11px":"10px",color:T.dim2,letterSpacing:"2px",textAlign:"center",padding:24}}>
                LAP TIMES NOT YET AVAILABLE<br/>
                <span style={{fontSize:"9px",marginTop:"6px",opacity:0.8}}>Data may still be processing, or only available from one source</span>
              </div>
            )}
          </div>
        </Card>

        <Card>
          <SectionHeader title="Race strategy · tyre compounds"/>
          {allDriverNums.slice(0,10).map(dn => {
            const d = drivers?.find(dr => dr.driver_number === dn);
            const driverStints = [...(stints[dn] || [])].sort(
              (a,b) => (a.lap_start||0)-(b.lap_start||0) || (a.stint_number||0)-(b.stint_number||0)
            );
            return(
              <div key={dn} style={{display:"flex",alignItems:"center",gap:"8px",marginBottom:"8px"}}>
                <span style={{fontFamily:T.fontMono,fontSize:mobile?"11px":"10px",
                  color:T.dim2,width:"40px",flexShrink:0}}>{d?.name_acronym||dn}</span>
                <div style={{flex:1,display:"flex",gap:"2px",height:mobile?"24px":"20px"}}>
                  {driverStints.map((s,i) => {
                    const compound = (s.compound||"UNKNOWN").toUpperCase();
                    const color = T.tyres[compound] || T.dim;
                    const inferred = Boolean(s.inferred_opening);
                    const tip = inferred
                      ? `Laps ${s.lap_start}–${s.lap_end}: compound not in OpenF1 (gap filled)`
                      : `Laps ${s.lap_start}–${s.lap_end}: ${compound}`;
                    return(
                      <div key={`${s.lap_start}-${s.lap_end}-${i}`} title={tip} style={{
                        flex:s.laps||1, background:color, borderRadius:"3px",
                        display:"flex",alignItems:"center",justifyContent:"center",
                        fontSize:mobile?"9px":"8px",fontWeight:700,letterSpacing:"0.5px",
                        color:compound==="MEDIUM"||compound==="HARD"?"#000":"#fff",
                        opacity:inferred?0.55:0.88,fontFamily:T.fontMono}}>
                        {inferred ? `?${s.laps}` : `${compound[0]}${s.laps}`}
                      </div>
                    );
                  })}
                </div>
                <span style={{fontFamily:T.fontMono,fontSize:mobile?"9px":"8px",color:T.dim2,width:"20px"}}>
                  {Math.max(0,driverStints.length-1)}P
                </span>
              </div>
            );
          })}
        </Card>
      </div>
    </div>
  );
}
