import { useState, useRef, useEffect, useCallback } from "react";

const API = "https://pharmagraph-backend-916510424773.us-central1.run.app";

const SUGGESTIONS = [
  "How do ibuprofen and warfarin together effect?",
  "Side effects of aspirin?",
  "Mixing metformin and alcohol?",
];

const GREEN = "#118250";
const MILKY = "#F8F6F1";

const NODE_COLORS = [
  "#118250", "#2D9E6B", "#E8A838", "#D4763B",
  "#B85C8A", "#5B6FBE", "#3AABCC", "#8B5CF6",
  "#E05555", "#1A6B3A",
];

function renderMarkdown(text) {
  const lines = text.split("\n");
  const elements = [];
  let listItems = [];

  const flushList = () => {
    if (listItems.length === 0) return;
    elements.push(
      <ol key={`list-${elements.length}`} style={{
        margin: "8px 0", paddingLeft: 22,
        display: "flex", flexDirection: "column", gap: 6,
      }}>
        {listItems.map((item, i) => (
          <li key={i} style={{ fontSize: 14, lineHeight: 1.65, color: "#222" }}>
            {renderInline(item)}
          </li>
        ))}
      </ol>
    );
    listItems = [];
  };

  lines.forEach((line, i) => {
    const headingMatch = line.match(/^\*\*(.+?)\*\*:?\s*$/);
    if (headingMatch) {
      flushList();
      elements.push(
        <p key={i} style={{
          fontWeight: 700, fontSize: 14, color: GREEN,
          margin: "12px 0 4px", letterSpacing: "0.01em",
        }}>
          {headingMatch[1].replace(/:$/, "")}
        </p>
      );
      return;
    }
    const bulletMatch = line.match(/^\*+\s+(.+)/);
    if (bulletMatch) { listItems.push(bulletMatch[1]); return; }
    if (line.trim() === "") {
      flushList();
      elements.push(<div key={i} style={{ height: 6 }} />);
      return;
    }
    flushList();
    elements.push(
      <p key={i} style={{ fontSize: 14, lineHeight: 1.65, color: "#222", margin: "2px 0" }}>
        {renderInline(line)}
      </p>
    );
  });
  flushList();
  return elements;
}

function renderInline(text) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return parts.map((p, i) =>
    i % 2 === 1
      ? <strong key={i} style={{ fontWeight: 600, color: "#111" }}>{p}</strong>
      : p
  );
}

// ── Graph ─────────────────────────────────────────────────────────────────────
// Shows drug IDs (shorter than names) in bigger circles
// Canvas is wider (600x460) and centered in its panel
function GraphViz({ graphPath, queriedDrugs }) {
  const canvasRef = useRef(null);
  const animRef = useRef(null);
  const nodesRef = useRef([]);
  const [selectedNode, setSelectedNode] = useState(null);

  useEffect(() => {
    setSelectedNode(null);
    if (!graphPath || graphPath.length === 0) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width;
    const H = canvas.height;

    const nodeMap = {};
    const edgeSet = [];

    const addNode = (id, label, displayId, type, desc = "") => {
      if (!nodeMap[id]) nodeMap[id] = { id, label, displayId, type, desc };
    };

    // queried drugs as primary — use drug name as displayId (already short enough)
    queriedDrugs.forEach(d => addNode(d, d, d, "primary"));

    // cross-interactions between queried drugs
    graphPath.forEach(e => {
      if (!e.drug_a || !e.drug_b) return;
      const aQ = queriedDrugs.some(d => d.toUpperCase() === e.drug_a.toUpperCase());
      const bQ = queriedDrugs.some(d => d.toUpperCase() === e.drug_b.toUpperCase());
      if (aQ && bQ) {
        addNode(e.drug_a, e.drug_a, e.drug_a, "primary", e.description);
        addNode(e.drug_b, e.drug_b, e.drug_b, "primary", e.description);
        edgeSet.push({ from: e.drug_a, to: e.drug_b, desc: e.description });
      }
    });

    // max 3 neighbors per queried drug — use drug_b id from graph_path
    const neighborCount = {};
    queriedDrugs.forEach(d => { neighborCount[d] = 0; });

    graphPath.forEach(e => {
      if (!e.drug_a || !e.drug_b) return;
      const aQ = queriedDrugs.some(d => d.toUpperCase() === e.drug_a.toUpperCase());
      const bQ = queriedDrugs.some(d => d.toUpperCase() === e.drug_b.toUpperCase());

      if (aQ && !bQ && (neighborCount[e.drug_a] || 0) < 3) {
        // drug_b is neighbor — use its name as display but keep it short
        const shortName = e.drug_b.length > 11 ? e.drug_b.slice(0, 10) + "…" : e.drug_b;
        addNode(e.drug_b, e.drug_b, shortName, "neighbor", e.description);
        edgeSet.push({ from: e.drug_a, to: e.drug_b, desc: e.description });
        neighborCount[e.drug_a] = (neighborCount[e.drug_a] || 0) + 1;
      } else if (bQ && !aQ && (neighborCount[e.drug_b] || 0) < 3) {
        const shortName = e.drug_a.length > 11 ? e.drug_a.slice(0, 10) + "…" : e.drug_a;
        addNode(e.drug_a, e.drug_a, shortName, "neighbor", e.description);
        edgeSet.push({ from: e.drug_a, to: e.drug_b, desc: e.description });
        neighborCount[e.drug_b] = (neighborCount[e.drug_b] || 0) + 1;
      }
    });

    // enzyme nodes
    graphPath.forEach(e => {
      if (!e.enzyme) return;
      if (queriedDrugs.some(d => d.toUpperCase() === (e.drug || "").toUpperCase())) {
        const eKey = `enz_${e.enzyme}`;
        const shortEnz = e.enzyme.length > 11 ? e.enzyme.slice(0, 10) + "…" : e.enzyme;
        addNode(eKey, e.enzyme, shortEnz, "enzyme");
        edgeSet.push({ from: e.drug, to: eKey, desc: "metabolized by" });
      }
    });

    const nodeList = Object.values(nodeMap);
    const cx = W / 2;
    const cy = H / 2;
    // wider oval: rx > ry so nodes spread more horizontally
    const rx = W * 0.40;
    const ry = H * 0.36;

    nodesRef.current = nodeList.map((n, i) => {
      const angle = (2 * Math.PI * i) / nodeList.length - Math.PI / 2;
      const isPrimary = n.type === "primary";
      return {
        ...n,
        x: cx + rx * Math.cos(angle),
        y: cy + ry * Math.sin(angle),
        baseX: cx + rx * Math.cos(angle),
        baseY: cy + ry * Math.sin(angle),
        phase: Math.random() * Math.PI * 2,
        color: isPrimary ? GREEN : NODE_COLORS[(i + 2) % NODE_COLORS.length],
        // bigger circles: primary=38, neighbor=30, enzyme=22
        r: isPrimary ? 38 : n.type === "enzyme" ? 22 : 30,
      };
    });

    let t = 0;
    const draw = () => {
      ctx.clearRect(0, 0, W, H);
      t += 0.01;

      nodesRef.current.forEach(n => {
        n.x = n.baseX + Math.sin(t + n.phase) * 4;
        n.y = n.baseY + Math.cos(t * 0.7 + n.phase) * 3.5;
      });

      // edges
      edgeSet.forEach(({ from, to }) => {
        const a = nodesRef.current.find(n => n.id === from);
        const b = nodesRef.current.find(n => n.id === to);
        if (!a || !b) return;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = "rgba(17,130,80,0.14)";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      });

      // nodes
      nodesRef.current.forEach(n => {
        const grd = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.r * 2.1);
        grd.addColorStop(0, n.color + "44");
        grd.addColorStop(1, "transparent");
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r * 2.1, 0, Math.PI * 2);
        ctx.fillStyle = grd;
        ctx.fill();

        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fillStyle = n.color;
        ctx.shadowColor = n.color;
        ctx.shadowBlur = 12;
        ctx.fill();
        ctx.shadowBlur = 0;

        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(255,255,255,0.6)";
        ctx.lineWidth = 2.5;
        ctx.stroke();

        // label: use displayId, bigger font for bigger circles
        ctx.fillStyle = "#fff";
        ctx.font = `600 ${n.r >= 38 ? 12 : n.r >= 30 ? 10 : 9}px 'DM Sans', sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(n.displayId, n.x, n.y);
      });

      animRef.current = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(animRef.current);
  }, [graphPath, queriedDrugs]);

  const handleClick = useCallback((e) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const cx = (e.clientX - rect.left) * (canvas.width / rect.width);
    const cy = (e.clientY - rect.top) * (canvas.height / rect.height);
    const hit = nodesRef.current.find(n => {
      const dx = n.x - cx, dy = n.y - cy;
      return Math.sqrt(dx * dx + dy * dy) < n.r + 8;
    });
    setSelectedNode(hit || null);
  }, []);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <canvas
        ref={canvasRef}
        width={600}
        height={460}
        onClick={handleClick}
        style={{
          width: "100%",
          height: "100%",
          cursor: "pointer",
          borderRadius: 16,
          display: "block",
        }}
      />
      {selectedNode && (
        <div style={{
          position: "absolute", bottom: 12, left: 12, right: 12,
          background: "rgba(248,246,241,0.97)",
          border: `1.5px solid ${GREEN}33`,
          borderRadius: 12, padding: "12px 14px",
          boxShadow: "0 4px 20px rgba(17,130,80,0.10)",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <span style={{ fontFamily: "'DM Sans',sans-serif", fontWeight: 700, fontSize: 13, color: GREEN }}>
              {selectedNode.label}
            </span>
            <button onClick={() => setSelectedNode(null)} style={{
              background: "none", border: "none", cursor: "pointer",
              color: "#aaa", fontSize: 18, lineHeight: 1, padding: 0,
            }}>×</button>
          </div>
          {selectedNode.desc && (
            <p style={{
              margin: "6px 0 0", fontFamily: "'DM Sans',sans-serif",
              fontSize: 12, color: "#444", lineHeight: 1.5,
            }}>
              {selectedNode.desc.slice(0, 220)}{selectedNode.desc.length > 220 ? "…" : ""}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function TypingDots() {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 5,
      padding: "12px 18px", background: "#fff",
      borderRadius: "18px 18px 18px 4px",
      alignSelf: "flex-start",
      boxShadow: "0 2px 12px rgba(0,0,0,0.06)",
    }}>
      <span style={{ fontFamily: "'DM Sans',sans-serif", fontSize: 13, color: "#888", fontStyle: "italic", marginRight: 4 }}>
        searching
      </span>
      {[0, 1, 2].map(i => (
        <span key={i} style={{
          width: 6, height: 6, borderRadius: "50%", background: GREEN,
          display: "inline-block",
          animation: `dot-blink 1.2s ${i * 0.2}s infinite`,
        }} />
      ))}
    </div>
  );
}

function Message({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div style={{ display: "flex", justifyContent: isUser ? "flex-end" : "flex-start", marginBottom: 14 }}>
      <div style={{
        maxWidth: "80%", padding: "13px 18px",
        borderRadius: isUser ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
        background: isUser ? GREEN : "#fff",
        color: isUser ? "#fff" : "#222",
        fontFamily: "'DM Sans',sans-serif",
        boxShadow: "0 2px 12px rgba(0,0,0,0.07)",
      }}>
        {isUser
          ? <span style={{ fontSize: 14, lineHeight: 1.6 }}>{msg.content}</span>
          : <div>{renderMarkdown(msg.content)}</div>
        }
        {msg.sources?.length > 0 && (
          <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${GREEN}22` }}>
            <span style={{ fontSize: 11, color: "#999", fontWeight: 600 }}>
              PubMed: {msg.sources.slice(0, 5).join(", ")}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [graphData, setGraphData] = useState(null);
  const [queriedDrugs, setQueriedDrugs] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(true);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const send = async (text) => {
    const q = (text || input).trim();
    if (!q || loading) return;
    setInput("");
    setShowSuggestions(false);
    setMessages(prev => [...prev, { role: "user", content: q }]);
    setLoading(true);
    try {
      const res = await fetch(`${API}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q }),
      });
      const data = await res.json();
      if (data.answer) {
        setMessages(prev => [...prev, {
          role: "assistant", content: data.answer, sources: data.sources,
        }]);
        if (data.graph_path?.length > 0) {
          setGraphData(data.graph_path);
          setQueriedDrugs(data.drugs_found || []);
        }
      } else {
        setMessages(prev => [...prev, {
          role: "assistant",
          content: data.error || "Something went wrong. Please try again.",
        }]);
      }
    } catch {
      setMessages(prev => [...prev, {
        role: "assistant", content: "Could not reach the server. Please try again.",
      }]);
    }
    setLoading(false);
  };

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const hasChat = messages.length > 0;

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=Playfair+Display:wght@700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body { height: 100%; background: ${MILKY}; overflow: hidden; }
        @keyframes dot-blink {
          0%,80%,100% { opacity:.2; transform:scale(0.8); }
          40% { opacity:1; transform:scale(1.2); }
        }
        @keyframes fadeSlideUp {
          from { opacity:0; transform:translateY(16px); }
          to   { opacity:1; transform:translateY(0); }
        }
        @keyframes fadeIn { from{opacity:0;} to{opacity:1;} }
        textarea { resize:none; }
        textarea:focus { outline:none; }
        ::-webkit-scrollbar { width:5px; }
        ::-webkit-scrollbar-thumb { background:#ddd; border-radius:3px; }
      `}</style>

      <div style={{
        display: "flex",
        height: "100vh",
        overflow: "hidden",
        background: MILKY,
        fontFamily: "'DM Sans',sans-serif",
      }}>

        {/* LEFT: chat column */}
        <div style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          overflow: "hidden",
          padding: "0 24px",
          minWidth: 0,
        }}>
          <div style={{
            textAlign: "center",
            paddingTop: hasChat ? 22 : 70,
            paddingBottom: 4,
            flexShrink: 0,
            transition: "padding 0.4s ease",
            width: "100%",
          }}>
            <h1 style={{
              fontFamily: "'Playfair Display',serif",
              fontSize: hasChat ? 26 : 50,
              fontWeight: 700, color: GREEN,
              letterSpacing: "-1px",
              transition: "font-size 0.4s ease",
              animation: "fadeSlideUp 0.5s ease",
            }}>
              PharmaGraph
            </h1>
            {!hasChat && (
              <p style={{ marginTop: 8, fontSize: 13, color: "#999", animation: "fadeIn 0.8s 0.3s both" }}>
                For educational purposes only.{" "}
                <a href="https://www.drugbank.com" target="_blank" rel="noreferrer"
                  style={{ color: GREEN, textDecoration: "none", fontWeight: 600 }}>
                  Special thanks to DrugBank ↗
                </a>
              </p>
            )}
          </div>

          {showSuggestions && (
            <div style={{
              display: "flex", gap: 10, marginTop: 30, marginBottom: 26,
              flexWrap: "wrap", justifyContent: "center",
              flexShrink: 0, width: "100%", maxWidth: 620,
              animation: "fadeSlideUp 0.7s 0.2s both",
            }}>
              {SUGGESTIONS.map((s, i) => (
                <button key={i} onClick={() => send(s)} style={{
                  padding: "9px 18px", borderRadius: 999,
                  border: `1.5px solid ${GREEN}44`,
                  background: "#fff", color: "#333",
                  fontFamily: "'DM Sans',sans-serif",
                  fontSize: 13, cursor: "pointer", fontWeight: 500,
                  boxShadow: "0 2px 8px rgba(17,130,80,0.06)",
                  transition: "all 0.18s",
                }}
                  onMouseEnter={e => { e.target.style.background = GREEN; e.target.style.color = "#fff"; }}
                  onMouseLeave={e => { e.target.style.background = "#fff"; e.target.style.color = "#333"; }}
                >{s}</button>
              ))}
            </div>
          )}

          {hasChat && (
            <div style={{
              width: "100%", maxWidth: 660,
              flex: 1, overflowY: "auto",
              padding: "8px 0 12px",
              animation: "fadeIn 0.4s ease",
            }}>
              {messages.map((m, i) => <Message key={i} msg={m} />)}
              {loading && <TypingDots />}
              <div ref={bottomRef} />
            </div>
          )}

          <div style={{
            width: "100%", maxWidth: 660,
            flexShrink: 0, paddingBottom: 22, paddingTop: 8,
            animation: hasChat ? "none" : "fadeSlideUp 0.8s 0.4s both",
          }}>
            <div style={{
              background: "#fff", borderRadius: 18,
              border: `1.5px solid ${GREEN}2e`,
              boxShadow: "0 4px 20px rgba(17,130,80,0.07)",
              padding: "14px 14px 10px 18px",
              display: "flex", flexDirection: "column", gap: 8,
            }}>
              <textarea
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKey}
                placeholder="Ask about drug interactions..."
                rows={3}
                style={{
                  border: "none", background: "transparent",
                  fontFamily: "'DM Sans',sans-serif",
                  fontSize: 15, color: "#222", width: "100%", lineHeight: 1.6,
                }}
              />
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button onClick={() => send()}
                  disabled={loading || !input.trim()}
                  style={{
                    background: loading || !input.trim() ? "#ccc" : "#111",
                    color: "#fff", border: "none", borderRadius: 10,
                    padding: "8px 20px",
                    fontFamily: "'DM Sans',sans-serif",
                    fontSize: 13, fontWeight: 600,
                    cursor: loading || !input.trim() ? "not-allowed" : "pointer",
                    transition: "background 0.2s",
                  }}>
                  Enter
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT: graph panel
            - position sticky so it never scrolls with chat
            - wider (480px) and shifted left via negative margin
            - graph canvas 600x460 fills it fully, centered via flex */}
        {graphData && (
          <div style={{
            width: 500,
            flexShrink: 0,
            height: "100vh",
            position: "sticky",
            top: 0,
            alignSelf: "flex-start",
            marginLeft: -60,
            padding: "22px 24px 22px 36px",
            display: "flex",
            flexDirection: "column",
            animation: "fadeSlideUp 0.5s ease",
          }}>
            <p style={{
              fontFamily: "'DM Sans',sans-serif",
              fontSize: 11, fontWeight: 700, color: GREEN,
              letterSpacing: "0.06em", textTransform: "uppercase",
              marginBottom: 10, paddingLeft: 4, flexShrink: 0,
              textAlign: "center",
            }}>
              Here are other connections that might be interesting
            </p>
            <div style={{
              flex: 1,
              background: "#fff",
              borderRadius: 20,
              border: `1.5px solid ${GREEN}1a`,
              boxShadow: "0 8px 36px rgba(17,130,80,0.08)",
              overflow: "hidden",
              position: "relative",
              minHeight: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}>
              <GraphViz graphPath={graphData} queriedDrugs={queriedDrugs} />
            </div>
          </div>
        )}
      </div>
    </>
  );
}
