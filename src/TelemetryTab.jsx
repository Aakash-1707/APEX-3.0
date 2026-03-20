// APEX Telemetry Tab — Track map + driver comparison (fastest lap only)
import { useState, useEffect, useRef, useCallback } from "react";
import { T, apiFetch, Card, SectionHeader, Tag, Spinner, ErrorBanner, useIsMobile } from "./theme";

function LegendItem({ color, label }) {
  return (
    <div style={{display:"flex",alignItems:"center",gap:"8px"}}>
      <div style={{width:"12px",height:"5px",background:color,borderRadius:"1px"}}/>
      <span style={{fontFamily:T.fontMono,fontSize:"8px",letterSpacing:"1.5px",color:T.dim2}}>{label}</span>
    </div>
  );
}

export default function TelemetryTab({ sessionKey, drivers, mode }) {
  const mobile = useIsMobile();
  const allDrivers = drivers || [];
  const [selectedDrivers, setSelectedDrivers] = useState([]);
  const [telemetry, setTelemetry] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const progressRef = useRef(0);
  const playingRef = useRef(false);
  const animRef = useRef(null);
  const canvasRef = useRef(null);
  const lastProgressUpdate = useRef(0);

  const toggleDriver = (dn) => {
    setSelectedDrivers(prev => {
      if (prev.includes(dn)) return prev.length > 1 ? prev.filter(d => d !== dn) : prev;
      if (prev.length >= 2) return prev; // max 2 drivers
      return [...prev, dn];
    });
  };

  useEffect(() => {
    if (allDrivers.length >= 2 && selectedDrivers.length === 0) {
      setSelectedDrivers([allDrivers[0]?.driver_number, allDrivers[1]?.driver_number].filter(Boolean));
    }
  }, [allDrivers, selectedDrivers.length]);

  // Fetch telemetry for selected drivers (fastest lap only — API default)
  const fetchTelemetry = useCallback(async () => {
    if (!sessionKey || selectedDrivers.length === 0 || mode === "upcoming") return;
    setLoading(true); setError(null);
    try {
      const results = await Promise.all(
        selectedDrivers.map(dn => apiFetch(`/telemetry/${sessionKey}/${dn}`))
      );
      const next = {};
      selectedDrivers.forEach((dn, i) => { next[dn] = results[i]; });
      setTelemetry(next);
    } catch(e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [sessionKey, selectedDrivers, mode]);

  useEffect(() => { fetchTelemetry(); }, [fetchTelemetry]);

  const primaryTelem = selectedDrivers[0] ? telemetry[selectedDrivers[0]] : null;

  // Build track points from first selected driver (fastest lap)
  const trackPts = primaryTelem?.x?.length > 0
    ? primaryTelem.x.map((x, i) => [x, 1 - (primaryTelem.y[i] ?? 0)])
    : null;

  // Zone color — F1-style gradient: red (slow/brake) → orange → yellow → grey → white (fast)
  const zoneColor = (speed, brake) => {
    if (brake >= 50) return "#E8002D";           // Heavy braking — F1 red
    if (brake > 0) return "#E84420";             // Trail braking — dark orange-red
    if (speed < 100) return "#E8002D";           // Hairpin / very slow
    if (speed < 150) return "#F05028";           // Low speed corner — orange-red
    if (speed < 200) return "#F08030";           // Medium-low corner — orange
    if (speed < 250) return "#D0A040";           // Medium speed — muted gold
    if (speed < 300) return "#8A8A8A";           // High speed — grey
    return "#D0D0D0";                            // Full throttle / DRS — light grey
  };

  const drawTrack = useCallback((progA, progB) => {
    const canvas = canvasRef.current;
    if (!canvas || !trackPts) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const displayW = rect.width;
    const displayH = rect.height;
    if (canvas.width !== Math.round(displayW * dpr) || canvas.height !== Math.round(displayH * dpr)) {
      canvas.width = Math.round(displayW * dpr);
      canvas.height = Math.round(displayH * dpr);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const W = displayW, H = displayH;
    const pad = 40;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Fit track in canvas preserving aspect ratio (OpenF1 x,y are proportional)
    const trackW = Math.max(...trackPts.map(([x]) => x)) - Math.min(...trackPts.map(([x]) => x)) || 1;
    const trackH = Math.max(...trackPts.map(([,y]) => y)) - Math.min(...trackPts.map(([,y]) => y)) || 1;
    const canvasW = W - pad * 2, canvasH = H - pad * 2;
    const scale = Math.min(canvasW / trackW, canvasH / trackH);
    const ox = Math.min(...trackPts.map(([x]) => x));
    const oy = Math.min(...trackPts.map(([,y]) => y));
    const scaledW = trackW * scale;
    const scaledH = trackH * scale;
    const offsetX = pad + (canvasW - scaledW) / 2;
    const offsetY = pad + (canvasH - scaledH) / 2;
    const toCanvas = ([x, y]) => [
      offsetX + (x - ox) * scale,
      offsetY + (y - oy) * scale,
    ];

    // --- Track outline (dark underlay for contrast) ---
    ctx.save();
    ctx.beginPath();
    trackPts.forEach(([x, y], i) => {
      const [cx, cy] = toCanvas([x, y]);
      i === 0 ? ctx.moveTo(cx, cy) : ctx.lineTo(cx, cy);
    });
    ctx.closePath();
    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.lineWidth = 18;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();
    ctx.restore();

    // --- Speed/brake-colored track (aligned per-point from OpenF1) ---
    for (let i = 0; i < trackPts.length - 1; i++) {
      const [x1, y1] = toCanvas(trackPts[i]);
      const [x2, y2] = toCanvas(trackPts[i + 1]);
      const spd = primaryTelem?.speed?.[i] ?? 200;
      const brake = primaryTelem?.brake?.[i] ?? 0;
      const color = zoneColor(spd, brake);

      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.strokeStyle = color;
      ctx.lineWidth = 6;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.stroke();
    }

    // --- S/F line ---
    if (trackPts[0]) {
      const [fx,fy] = toCanvas(trackPts[0]);
      ctx.save();
      ctx.fillStyle = "#fff"; ctx.globalAlpha = 0.8;
      ctx.fillRect(fx-8,fy-2,16,4);
      ctx.globalAlpha = 1;
      ctx.fillStyle = "#fff"; ctx.font = "bold 9px 'DM Mono'";
      ctx.textAlign = "center"; ctx.textBaseline = "bottom";
      ctx.fillText("S/F", fx, fy - 6);
      ctx.restore();
    }

    // --- Driver trail (interpolated for smooth animation) ---
    const drawDriverTrail = (progVal, teamColor, acronym, trailLen) => {
      const nPts = trackPts.length;
      const exactIdx = Math.max(0, Math.min(1, progVal)) * (nPts - 1);
      const idx0 = Math.floor(exactIdx);
      const idx1 = Math.min(idx0 + 1, nPts - 1);
      const frac = exactIdx - idx0;

      // Trail (last ~15 points behind current position)
      for (let t = trailLen; t >= 0; t--) {
        const tIdx = Math.round(exactIdx - t);
        if (tIdx < 0 || tIdx >= nPts) continue;
        const [tx, ty] = toCanvas(trackPts[tIdx]);
        const alpha = ((trailLen - t) / trailLen) * 0.5;
        const size = 1.5 + ((trailLen - t) / trailLen) * 2;
        ctx.beginPath();
        ctx.arc(tx, ty, size, 0, Math.PI * 2);
        ctx.fillStyle = teamColor;
        ctx.globalAlpha = alpha;
        ctx.fill();
        ctx.globalAlpha = 1;
      }

      // Main dot — interpolate between adjacent points for smooth movement
      const [x0, y0] = toCanvas(trackPts[idx0]);
      const [x1, y1] = toCanvas(trackPts[idx1]);
      const dx = x0 + (x1 - x0) * frac;
      const dy = y0 + (y1 - y0) * frac;

      // Outer glow
        ctx.beginPath(); ctx.arc(dx, dy, 12, 0, Math.PI*2);
        ctx.fillStyle = teamColor; ctx.globalAlpha = 0.15; ctx.fill();
        ctx.globalAlpha = 1;

        // Inner dot
        ctx.beginPath(); ctx.arc(dx, dy, 6, 0, Math.PI*2);
        ctx.fillStyle = teamColor;
        ctx.shadowColor = teamColor; ctx.shadowBlur = 16;
        ctx.fill();
        ctx.shadowBlur = 0;

        // White ring
        ctx.beginPath(); ctx.arc(dx, dy, 7, 0, Math.PI*2);
        ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.globalAlpha = 0.6;
        ctx.stroke(); ctx.globalAlpha = 1;

        // Label
        ctx.fillStyle = "#fff"; ctx.font = "bold 10px 'DM Mono'";
        ctx.textAlign = "center"; ctx.textBaseline = "bottom";
        ctx.shadowColor = "rgba(0,0,0,0.8)"; ctx.shadowBlur = 4;
        ctx.fillText(acronym, dx, dy - 14);
        ctx.shadowBlur = 0;
    };

    // --- Draw all selected drivers (synced at same progress) ---
    selectedDrivers.forEach((dn, i) => {
      const info = allDrivers.find(d => d.driver_number === dn);
      const color = `#${info?.team_colour || "27F4D2"}`;
      const prog = i === 0 ? progA : progB;
      drawDriverTrail(prog, color, info?.name_acronym || "", 12);
    });

    const legend = [
      ["#E8002D","HEAVY BRAKE"],["#E84420","BRAKING"],["#F05028","LOW SPEED"],
      ["#F08030","MID-LOW"],["#D0A040","MID SPEED"],["#8A8A8A","HIGH SPEED"],["#D0D0D0","FULL THROTTLE"],
    ];
    legend.forEach(([c,l],i)=>{
      ctx.globalAlpha = 0.8;
      ctx.fillStyle=c; ctx.fillRect(12,12+i*15,8,5);
      ctx.fillStyle="#7a7a9a"; ctx.font="8px 'DM Mono'"; ctx.textAlign="left";
      ctx.fillText(l,24,17+i*15);
      ctx.globalAlpha = 1;
    });
  }, [trackPts, primaryTelem, selectedDrivers, allDrivers]);

  // Chart.js for speed/throttle/brake — only re-create when telemetry changes (not on progress)
  const chartRefs = { speed: useRef(null), throttle: useRef(null), brake: useRef(null) };
  const chartInstances = useRef({});
  const chartDataRef = useRef(null);

  useEffect(() => {
    if (!primaryTelem || selectedDrivers.length === 0) return;
    chartDataRef.current = { primaryTelem, selectedDrivers, telemetry };
    const script = document.createElement("script");
    script.src = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js";
    script.onload = () => {
      const labels = primaryTelem.speed?.map((_, i) => i) || [];
      const cfgs = {
        speed: { key: "speed", min: 50, max: 360, u: "km/h" },
        throttle: { key: "throttle", min: 0, max: 105, u: "%" },
        brake: { key: "brake", min: 0, max: 105, u: "%" },
      };
      Object.entries(cfgs).forEach(([chartKey, cfg]) => {
        if (!chartRefs[chartKey].current || !window.Chart) return;
        chartInstances.current[chartKey]?.destroy?.();
        const datasets = selectedDrivers.map((dn, i) => {
          const t = telemetry[dn];
          const info = allDrivers.find(d => d.driver_number === dn);
          const c = `#${info?.team_colour || "448aff"}`;
          const data = t?.[cfg.key] || [];
          return {
            data,
            borderColor: i === 0 ? c : `${c}99`,
            borderWidth: i === 0 ? 1.5 : 1,
            borderDash: i > 0 ? [4, 2] : [],
            backgroundColor: "transparent",
            pointRadius: 0,
          };
        });
        chartInstances.current[chartKey] = new window.Chart(chartRefs[chartKey].current.getContext("2d"), {
          type: "line",
          data: { labels, datasets },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            resizeDelay: 250,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: {
              x: { display: false },
              y: {
                grid: { color: "rgba(255,255,255,0.06)" },
                min: cfg.min,
                max: cfg.max,
                ticks: { color: T.dim2, font: { family: "'DM Mono'", size: 9 }, callback: v => `${v}${cfg.u}` },
              },
            },
          },
        });
      });
      drawTrack(0, 0.03);
    };
    document.head.appendChild(script);
    return () => {
      Object.values(chartInstances.current).forEach(c => c?.destroy?.());
      try { document.head.removeChild(script); } catch (e) {}
    };
  }, [primaryTelem, selectedDrivers, telemetry, drawTrack, allDrivers]);

  // Animation loop — speed based on actual lap time (~90s default)
  useEffect(() => {
    let lastTime = 0;
    const lapTimeSec = primaryTelem?.lap_time ?? 90;
    const progressPerSec = 1 / lapTimeSec;
    const loop = (timestamp) => {
      if (playingRef.current && primaryTelem) {
        const dt = lastTime ? (timestamp - lastTime) / 1000 : 0.016;
        lastTime = timestamp;
        progressRef.current = (progressRef.current + dt * progressPerSec) % 1;
        if (timestamp - lastProgressUpdate.current > 80) {
          lastProgressUpdate.current = timestamp;
          setProgress(progressRef.current);
        }
        const gapB = Math.max(0, progressRef.current - 0.012);
        drawTrack(progressRef.current, gapB);
      } else {
        lastTime = 0;
      }
      animRef.current = requestAnimationFrame(loop);
    };
    animRef.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(animRef.current);
  }, [drawTrack, primaryTelem]);

  const togglePlay = () => { playingRef.current = !playingRef.current; setPlaying(p => !p); };
  const reset = () => { playingRef.current = false; setPlaying(false); progressRef.current = 0; setProgress(0); drawTrack(0, 0.03); };

  const liveValues = selectedDrivers.map(dn => {
    const t = telemetry[dn];
    const n = t?.speed?.length ?? 1;
    const idx = Math.min(Math.floor(progress * Math.max(0, n - 1)), n - 1);
    return {
      driver_number: dn,
      speed: t?.speed?.[idx] || 0,
      throttle: t?.throttle?.[idx] || 0,
      brake: t?.brake?.[idx] || 0,
      gear: t?.gear?.[idx] || 0,
    };
  });

  if (mode === "upcoming") return (
    <Card><div style={{textAlign:"center",padding:"40px",fontFamily:T.fontMono,fontSize:"10px",color:T.dim2,letterSpacing:"2px"}}>
      TELEMETRY AVAILABLE AFTER SESSION
    </div></Card>
  );
  if (loading) return <Spinner label="Fetching telemetry (OpenF1 → FastF1)..."/>;
  if (error) return <ErrorBanner message={error} onRetry={fetchTelemetry}/>;

  const telemetryFailedBoth =
    sessionKey &&
    mode !== "upcoming" &&
    selectedDrivers.length > 0 &&
    selectedDrivers.every(dn => Object.prototype.hasOwnProperty.call(telemetry, dn) && !(telemetry[dn]?.n_points > 0));
  if (telemetryFailedBoth) {
    return (
      <Card>
        <div style={{textAlign:"center",padding:"40px",fontFamily:T.fontMono,fontSize:mobile?"11px":"10px",color:T.dim2,letterSpacing:"2px",lineHeight:1.6}}>
          TELEMETRY NOT AVAILABLE
          <div style={{fontSize:"9px",marginTop:"12px",opacity:0.85,letterSpacing:"1px"}}>
            OpenF1 and FastF1 returned no usable telemetry for the selected driver(s) in this session.
          </div>
        </div>
      </Card>
    );
  }

  const fastestLap = primaryTelem?.lap_time ? primaryTelem.lap_time.toFixed(3) + "s" : "—";

  return(
    <div>
      {/* Driver checkboxes — fastest lap per driver */}
      <div style={{display:"flex",alignItems:mobile?"flex-start":"center",gap:mobile?"8px":"16px",marginBottom:"16px",flexWrap:"wrap"}}>
        <span style={{fontFamily:T.fontMono,fontSize:mobile?"10px":"9px",letterSpacing:"2px",color:T.dim2}}>SELECT 2 DRIVERS</span>
        <div style={{display:"flex",flexWrap:"wrap",gap:mobile?"6px":"8px"}}>
          {allDrivers.map(d => {
            const checked = selectedDrivers.includes(d.driver_number);
            const lapTime = telemetry[d.driver_number]?.lap_time;
            const disabled = !checked && selectedDrivers.length >= 2;
            return (
              <label key={d.driver_number} style={{
                display:"flex",alignItems:"center",gap:"6px",cursor:disabled ? "not-allowed" : "pointer",
                padding:mobile?"6px 10px":"4px 10px",borderRadius:T.radiusSm,
                border:`1px solid ${checked ? `#${d.team_colour||"448aff"}` : disabled ? T.border : T.border2}`,
                background:checked ? `${d.team_colour ? "#"+d.team_colour+"22" : "rgba(68,138,255,0.1)"}` : disabled ? "rgba(255,255,255,0.02)" : "transparent",
                opacity: disabled ? 0.5 : 1,
              }}>
                <input type="checkbox" checked={checked} disabled={disabled} onChange={()=>toggleDriver(d.driver_number)}
                  style={{accentColor:`#${d.team_colour||"448aff"}`,width:mobile?"16px":"auto",height:mobile?"16px":"auto"}}/>
                <span style={{width:"6px",height:"6px",borderRadius:"50%",background:`#${d.team_colour||"448aff"}`}}/>
                <span style={{fontFamily:T.fontMono,fontSize:mobile?"11px":"10px",color:T.text}}>{d.name_acronym}</span>
                {!mobile && lapTime && <span style={{fontFamily:T.fontMono,fontSize:"8px",color:T.dim2}}>{lapTime.toFixed(3)}s</span>}
              </label>
            );
          })}
        </div>
        {!mobile && <div style={{flex:1}}/>}
        <Tag label={`FASTEST LAP · ${fastestLap}`} color={T.yellow}/>
      </div>

      {/* Track + Live readout */}
      <div style={{display:"grid",gridTemplateColumns:mobile?"1fr":"1fr 300px",gap:"16px",marginBottom:"16px"}}>
        <Card style={{padding:"12px"}}>
          <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:"8px",flexWrap:mobile?"wrap":"nowrap",gap:mobile?"6px":undefined}}>
            <SectionHeader title="Track map · GPS (OpenF1 / FastF1)"/>
            <div style={{display:"flex",gap:"6px"}}>
              <button onClick={togglePlay} style={{padding:mobile?"8px 16px":"5px 16px",fontFamily:T.fontMono,fontSize:mobile?"11px":"9px",
                letterSpacing:"2px",background:playing?"rgba(232,0,45,0.1)":"rgba(0,230,118,0.08)",
                border:`1px solid ${playing?T.red:T.green}`,borderRadius:T.radiusSm,
                color:playing?T.red:T.green,cursor:"pointer",textTransform:"uppercase"}}>
                {playing?"⏸ PAUSE":"▶ PLAY"}
              </button>
              <button onClick={reset} style={{padding:mobile?"8px 12px":"5px 12px",fontFamily:T.fontMono,fontSize:mobile?"11px":"9px",
                background:"transparent",border:`1px solid ${T.border2}`,borderRadius:T.radiusSm,
                color:T.dim2,cursor:"pointer",letterSpacing:"2px"}}>↺ RESET</button>
            </div>
          </div>
          <div style={{height:"3px",background:T.dim,borderRadius:"2px",marginBottom:"8px",overflow:"hidden"}}>
            <div style={{width:`${progress*100}%`,height:"100%",background:`linear-gradient(90deg, ${T.red}, #ff6d00)`,
              boxShadow:`0 0 8px ${T.red}`,transition:"width .03s linear"}}/>
          </div>
          <canvas ref={canvasRef}
            style={{width:"100%",height:mobile?"280px":"420px",background:T.bg1,borderRadius:"6px",
              border:`1px solid ${T.border}`,display:"block"}}/>
        </Card>

        <div style={{display:mobile?"grid":"flex",gridTemplateColumns:mobile?"1fr 1fr":undefined,
          flexDirection:mobile?undefined:"column",gap:"8px"}}>
          <SectionHeader title="Live readout"/>
          {[
            {key:"speed",label:"SPEED",unit:"km/h",color:T.blue,max:360},
            {key:"throttle",label:"THROTTLE",unit:"%",color:T.green,max:100},
            {key:"brake",label:"BRAKE",unit:"%",color:T.red,max:100},
            {key:"gear",label:"GEAR",unit:"",color:T.yellow,max:8},
          ].map(m=>(
            <Card key={m.label} style={{padding:mobile?"8px 10px":"10px 14px"}}>
              <div style={{fontFamily:T.fontMono,fontSize:mobile?"9px":"8px",letterSpacing:"3px",color:T.dim2,marginBottom:"6px"}}>{m.label}</div>
              {liveValues.map(lv => {
                const info = allDrivers.find(d => d.driver_number === lv.driver_number);
                const v = lv[m.key];
                return (
                  <div key={lv.driver_number} style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:"4px"}}>
                    <span style={{fontFamily:T.fontMono,fontSize:mobile?"10px":"9px",color:`#${info?.team_colour||"448aff"}`,minWidth:"28px"}}>
                      {info?.name_acronym || lv.driver_number}
                    </span>
                    <span style={{fontFamily:T.fontDisplay,fontSize:mobile?"14px":"16px",fontWeight:700,color:m.color}}>
                      {v}<span style={{fontSize:"9px",color:T.dim2,marginLeft:"2px"}}>{m.unit}</span>
                    </span>
                    {!mobile && <div style={{flex:1,maxWidth:"80px",height:"4px",background:T.dim,borderRadius:"1px",overflow:"hidden",marginLeft:"8px"}}>
                      <div style={{width:`${Math.min(100,(v/m.max)*100)}%`,height:"100%",background:m.color,borderRadius:"1px",transition:"width .05s"}}/>
                    </div>}
                  </div>
                );
              })}
            </Card>
          ))}
          <div style={{display:"flex",flexDirection:mobile?"row":"column",flexWrap:mobile?"wrap":"nowrap",
            gap:"6px",background:"rgba(0,0,0,0.4)",padding:"10px",borderRadius:"4px",border:`1px solid ${T.border}`,
            gridColumn:mobile?"1 / -1":undefined}}>
              <LegendItem color="#E8002D" label="HEAVY BRAKE"/>
              <LegendItem color="#E84420" label="BRAKING"/>
              <LegendItem color="#F05028" label="LOW SPEED"/>
              <LegendItem color="#F08030" label="MID-LOW"/>
              <LegendItem color="#D0A040" label="MID SPEED"/>
              <LegendItem color="#8A8A8A" label="HIGH SPEED"/>
              <LegendItem color="#D0D0D0" label="FULL THROTTLE"/>
            </div>
        </div>
      </div>

      {/* Trace charts */}
      {[
        {key:"speed",label:"SPEED",unit:"km/h",color:"#448aff",h:100},
        {key:"throttle",label:"THROTTLE",unit:"%",color:"#00e676",h:72},
        {key:"brake",label:"BRAKE",unit:"%",color:T.red,h:72},
      ].map(tr=>(
        <Card key={tr.key} style={{padding:"12px 16px",marginBottom:"8px"}}>
          <div style={{display:"flex",alignItems:"center",gap:"8px",marginBottom:"8px",flexWrap:"wrap"}}>
            <div style={{width:"3px",height:"14px",background:tr.color,borderRadius:"2px"}}/>
            <span style={{fontFamily:T.fontMono,fontSize:"9px",letterSpacing:"3px",color:T.dim2,textTransform:"uppercase"}}>{tr.label} · {tr.unit}</span>
            <div style={{flex:1}}/>
            {selectedDrivers.map((dn,i)=>{
              const info = allDrivers.find(d=>d.driver_number===dn);
              return <span key={dn} style={{fontFamily:T.fontMono,fontSize:"9px",color:`#${info?.team_colour||"448aff"}`,marginLeft:i>0?"12px":0}}>
                {i>0?"· ":""}{info?.name_acronym||dn}
              </span>;
            })}
          </div>
          <div style={{height:`${tr.h}px`}}><canvas ref={chartRefs[tr.key]}/></div>
        </Card>
      ))}
    </div>
  );
}
