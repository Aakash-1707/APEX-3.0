// APEX Strategy Chat — Claude-powered strategy assistant
import { useState, useRef, useEffect, useCallback } from "react";
import { T, apiFetch, useIsMobile } from "./theme";

function ChatMessage({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div style={{
      display: "flex",
      justifyContent: isUser ? "flex-end" : "flex-start",
      marginBottom: "10px",
    }}>
      <div style={{
        maxWidth: "85%",
        padding: "10px 14px",
        borderRadius: isUser ? "12px 12px 2px 12px" : "12px 12px 12px 2px",
        background: isUser ? "rgba(232,0,45,0.12)" : T.bg3,
        border: `1px solid ${isUser ? "rgba(232,0,45,0.25)" : T.border}`,
      }}>
        {!isUser && (
          <div style={{
            fontFamily: T.fontMono, fontSize: "8px", letterSpacing: "2px",
            color: "#00e5ff", marginBottom: "6px",
          }}>APEX STRATEGIST</div>
        )}
        <div style={{
          fontFamily: T.fontBody, fontSize: "12px", color: T.text,
          lineHeight: "1.6", whiteSpace: "pre-wrap",
        }}>
          {formatMessage(msg.content)}
        </div>
        <div style={{
          fontFamily: T.fontMono, fontSize: "8px", color: T.dim2,
          marginTop: "4px", textAlign: isUser ? "right" : "left",
        }}>
          {msg.timestamp || ""}
        </div>
      </div>
    </div>
  );
}

function formatMessage(text) {
  if (!text) return "";
  return text
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/\*(.*?)\*/g, "$1");
}

export default function StrategyChat({ meetingKey, circuit, simulationResult, onNarration }) {
  const mobile = useIsMobile();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [hasNarrated, setHasNarrated] = useState(false);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    if (simulationResult && !hasNarrated) {
      generateNarration();
      setHasNarrated(true);
    }
  }, [simulationResult, hasNarrated]);

  const generateNarration = useCallback(async () => {
    if (!meetingKey || !simulationResult) return;
    setLoading(true);
    try {
      const data = await apiFetch("/strategy/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          meeting_key: meetingKey,
          circuit: circuit || "Australia",
          message: "Provide a strategy briefing for this race based on the simulation results.",
          simulation_context: simulationResult,
          conversation_history: [],
        }),
      });
      const narration = data.response || data.message || "Strategy analysis unavailable.";
      setMessages(prev => [...prev, {
        role: "assistant",
        content: narration,
        timestamp: new Date().toLocaleTimeString(),
      }]);
      if (onNarration) onNarration(narration);
    } catch (e) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `Strategy analysis: ${e.message}`,
        timestamp: new Date().toLocaleTimeString(),
      }]);
    } finally {
      setLoading(false);
    }
  }, [meetingKey, circuit, simulationResult, onNarration]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg = {
      role: "user",
      content: text,
      timestamp: new Date().toLocaleTimeString(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const history = messages.map(m => ({role: m.role, content: m.content}));
      const data = await apiFetch("/strategy/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          meeting_key: meetingKey,
          circuit: circuit || "Australia",
          message: text,
          simulation_context: simulationResult || null,
          conversation_history: history,
        }),
      });
      setMessages(prev => [...prev, {
        role: "assistant",
        content: data.response || data.message || "No response.",
        timestamp: new Date().toLocaleTimeString(),
      }]);
    } catch (e) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `Error: ${e.message}`,
        timestamp: new Date().toLocaleTimeString(),
      }]);
    } finally {
      setLoading(false);
    }
  }, [input, loading, messages, meetingKey, circuit, simulationResult]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  if (!isOpen) {
    return (
      <button onClick={() => setIsOpen(true)} style={{
        position: "fixed", bottom: mobile ? "12px" : "20px",
        right: mobile ? "12px" : "24px", zIndex: 1000,
        width: mobile ? "48px" : "52px", height: mobile ? "48px" : "52px",
        borderRadius: "50%",
        background: "linear-gradient(135deg, #e8002d, #ff6d00)",
        border: "none", cursor: "pointer",
        boxShadow: "0 4px 20px rgba(232,0,45,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center",
        transition: "transform .2s",
      }}
        onMouseEnter={e => e.target.style.transform = "scale(1.1)"}
        onMouseLeave={e => e.target.style.transform = "scale(1)"}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
          <path d="M12 2C6.48 2 2 5.58 2 10c0 2.12 1.07 4.04 2.79 5.43L4 20l4.5-2.25C9.61 17.91 10.79 18 12 18c5.52 0 10-3.58 10-8S17.52 2 12 2z"
            fill="white" opacity="0.9"/>
          <circle cx="8" cy="10" r="1.2" fill="#e8002d"/>
          <circle cx="12" cy="10" r="1.2" fill="#e8002d"/>
          <circle cx="16" cy="10" r="1.2" fill="#e8002d"/>
        </svg>
      </button>
    );
  }

  return (
    <div style={{
      position: "fixed",
      bottom: mobile ? 0 : "20px",
      right: mobile ? 0 : "24px",
      width: mobile ? "100%" : "400px",
      height: mobile ? "70vh" : "520px",
      zIndex: 1000,
      background: T.bg1,
      border: `1px solid ${T.border2}`,
      borderRadius: mobile ? "16px 16px 0 0" : "12px",
      boxShadow: "0 8px 40px rgba(0,0,0,0.6)",
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{
        padding: "12px 16px",
        borderBottom: `1px solid ${T.border}`,
        display: "flex", alignItems: "center", gap: "10px",
        background: `linear-gradient(180deg, ${T.bg2}, transparent)`,
      }}>
        <div style={{
          width: "8px", height: "8px", borderRadius: "50%",
          background: "#00e5ff",
          boxShadow: "0 0 8px rgba(0,229,255,0.6)",
        }}/>
        <div style={{ flex: 1 }}>
          <div style={{
            fontFamily: T.fontDisplay, fontSize: "11px", fontWeight: 700,
            letterSpacing: "2px", color: T.text,
          }}>APEX STRATEGIST</div>
          <div style={{
            fontFamily: T.fontMono, fontSize: "8px",
            color: T.dim2, letterSpacing: "1px",
          }}>
            {loading ? "ANALYZING..." : "POWERED BY CLAUDE"}
          </div>
        </div>
        <button onClick={() => setIsOpen(false)} style={{
          background: "transparent", border: "none", cursor: "pointer",
          color: T.dim2, fontSize: "18px", padding: "4px",
        }}>×</button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} style={{
        flex: 1, overflowY: "auto", padding: "12px",
        display: "flex", flexDirection: "column",
      }}>
        {messages.length === 0 && !loading && (
          <div style={{
            textAlign: "center", padding: "40px 20px",
            fontFamily: T.fontMono, fontSize: "10px",
            color: T.dim2, letterSpacing: "1px",
          }}>
            <div style={{ marginBottom: "12px", fontSize: "24px" }}>
              <svg width="32" height="32" viewBox="0 0 18 18" fill="none" style={{margin:"0 auto",display:"block"}}>
                <path d="M9 1L17 9L9 17L1 9Z" stroke="#00e5ff" strokeWidth="1.5"
                  fill="rgba(0,229,255,0.1)"/>
                <path d="M9 5L13 9L9 13L5 9Z" fill="#00e5ff" opacity="0.7"/>
              </svg>
            </div>
            APEX STRATEGY ASSISTANT<br/><br/>
            Ask me about tyre strategy, undercuts,<br/>
            safety car scenarios, or race simulations.
            <div style={{ marginTop: "16px", display: "flex", flexDirection: "column", gap: "6px" }}>
              {[
                "What's the best strategy for this race?",
                "What if a safety car comes out on lap 25?",
                "Should Hamilton undercut Russell?",
              ].map(q => (
                <button key={q} onClick={() => { setInput(q); inputRef.current?.focus(); }}
                  style={{
                    padding: "8px 12px", fontSize: "10px", fontFamily: T.fontMono,
                    background: T.bg3, border: `1px solid ${T.border2}`,
                    borderRadius: T.radiusSm, color: T.dim2,
                    cursor: "pointer", textAlign: "left",
                  }}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg, i) => <ChatMessage key={i} msg={msg}/>)}
        {loading && (
          <div style={{
            display: "flex", gap: "4px", padding: "12px",
            justifyContent: "flex-start",
          }}>
            {[0, 1, 2].map(i => (
              <div key={i} style={{
                width: "6px", height: "6px", borderRadius: "50%",
                background: "#00e5ff", opacity: 0.5,
                animation: `chatDot 1s ${i * 0.15}s infinite`,
              }}/>
            ))}
            <style>{`@keyframes chatDot{0%,80%,100%{opacity:.3;transform:scale(1)}40%{opacity:1;transform:scale(1.3)}}`}</style>
          </div>
        )}
      </div>

      {/* Input */}
      <div style={{
        padding: "10px 12px",
        borderTop: `1px solid ${T.border}`,
        display: "flex", gap: "8px",
        background: T.bg2,
      }}>
        <input
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about strategy..."
          disabled={loading}
          style={{
            flex: 1, padding: "8px 12px",
            fontFamily: T.fontMono, fontSize: "11px",
            background: T.bg3, border: `1px solid ${T.border2}`,
            borderRadius: T.radiusSm, color: T.text,
            outline: "none",
          }}
        />
        <button onClick={sendMessage} disabled={loading || !input.trim()}
          style={{
            padding: "8px 14px", fontFamily: T.fontMono, fontSize: "9px",
            letterSpacing: "2px",
            background: input.trim() ? "rgba(232,0,45,0.15)" : "transparent",
            border: `1px solid ${input.trim() ? T.red : T.border2}`,
            borderRadius: T.radiusSm,
            color: input.trim() ? T.red : T.dim2,
            cursor: input.trim() ? "pointer" : "default",
            textTransform: "uppercase",
          }}>
          SEND
        </button>
      </div>
    </div>
  );
}
