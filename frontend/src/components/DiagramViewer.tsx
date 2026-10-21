import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, ReactFlowProvider,
  getNodesBounds, getViewportForBounds, useReactFlow,
  type Edge, type Node, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import { toPng, toSvg } from "html-to-image";
import { api } from "../api";
import type { DiagramData, DNode } from "../types";

/*
 * Interactive diagram viewer (React Flow + dagre layout).
 * The diagram data always comes from the server, already validated; this file
 * only lays it out and makes it explorable. Nothing here invents content.
 */

const NODE_W = 210;
const NODE_H = 74;

// Every role has a text badge and a shape, so meaning never relies on colour alone.
const ROLE: Record<string, { badge: string; icon: string; cls: string }> = {
  root: { badge: "Topic", icon: "◎", cls: "r-root" },
  branch: { badge: "Branch", icon: "◆", cls: "r-branch" },
  leaf: { badge: "Detail", icon: "•", cls: "r-leaf" },
  concept: { badge: "Concept", icon: "◇", cls: "r-concept" },
  example: { badge: "Example", icon: "✎", cls: "r-example" },
  note: { badge: "Note", icon: "ℹ", cls: "r-note" },
  start: { badge: "Start", icon: "▶", cls: "r-start" },
  action: { badge: "Step", icon: "→", cls: "r-action" },
  decision: { badge: "Decision", icon: "?", cls: "r-decision" },
  end: { badge: "End", icon: "■", cls: "r-end" },
  role: { badge: "Role", icon: "◎", cls: "r-root" },
  group: { badge: "Group", icon: "▤", cls: "r-branch" },
  strength: { badge: "Strength (evidence)", icon: "✓", cls: "r-strength" },
  improve: { badge: "To improve (evidence)", icon: "!", cls: "r-improve" },
  unassessed: { badge: "Not assessed yet", icon: "○", cls: "r-unassessed" },
  step: { badge: "Step", icon: "①", cls: "r-branch" },
  guidance: { badge: "Guidance", icon: "ℹ", cls: "r-leaf" },
  milestone: { badge: "Milestone", icon: "⚑", cls: "r-branch" },
  task: { badge: "Task", icon: "☐", cls: "r-task" },
};
// Resume skill-match diagrams use the same shapes with resume wording.
const RESUME_BADGE: Record<string, string> = {
  strength: "Shown in resume", improve: "Partly shown", unassessed: "Not mentioned", role: "Target role",
};
const roleInfo = (n: { role: string; importance?: string }, resume: boolean) => {
  const r = ROLE[n.role] || ROLE.leaf;
  return resume && RESUME_BADGE[n.role] ? { ...r, badge: RESUME_BADGE[n.role] } : r;
};
const STATUS_LABEL = { pending: "To do", in_progress: "In progress", done: "Done" } as const;
const DIRECTION: Record<string, "LR" | "TB"> = {
  mindmap: "LR", concept: "LR", flowchart: "TB", skillgap: "LR", star: "TB", roadmap: "TB",
};
const ARROWS = new Set(["concept", "flowchart", "star", "roadmap"]);

type NodeData = { node: DNode; kind: string; resume: boolean; hasChildren: boolean; collapsed: boolean; onToggle: (id: string) => void };

function DiagramNode({ data, selected }: NodeProps<Node<NodeData>>) {
  const { node, hasChildren, collapsed, onToggle, kind, resume } = data;
  const r = roleInfo(node, resume);
  const vertical = DIRECTION[kind] === "TB";
  return (
    <div
      className={`dg-node ${r.cls} ${selected ? "is-selected" : ""} ${node.status === "done" ? "is-done" : ""}`}
      title={node.detail || node.label}
    >
      <Handle type="target" position={vertical ? Position.Top : Position.Left} className="dg-handle" />
      <span className="dg-badge"><span aria-hidden="true">{r.icon}</span> {r.badge}
        {node.status && <em className={`dg-status s-${node.status}`}>{STATUS_LABEL[node.status]}</em>}
      </span>
      <span className="dg-label">{node.label}</span>
      {node.note && <span className="dg-noted" aria-label="has a note">✎ note</span>}
      {hasChildren && (
        <button
          className="dg-toggle nodrag"
          aria-label={collapsed ? `Expand ${node.label}` : `Collapse ${node.label}`}
          onClick={(e) => { e.stopPropagation(); onToggle(node.id); }}
        >{collapsed ? "+" : "−"}</button>
      )}
      <Handle type="source" position={vertical ? Position.Bottom : Position.Right} className="dg-handle" />
    </div>
  );
}
const nodeTypes = { card: DiagramNode };

function layout(d: DiagramData, visible: Set<string>) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: DIRECTION[d.kind] || "LR", nodesep: 26, ranksep: 70, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  d.nodes.filter((n) => visible.has(n.id)).forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  d.edges.filter((e) => visible.has(e.source) && visible.has(e.target)).forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  const pos: Record<string, { x: number; y: number }> = {};
  g.nodes().forEach((id) => {
    const p = g.node(id);
    if (p) pos[id] = { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 };
  });
  return pos;
}

const reducedMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

interface Props {
  materialId?: string;      // saved diagrams can be edited, noted and tracked
  data: DiagramData;
  onPractice?: (topic: string, questions: string[]) => void;
  onAsk?: (node: DNode) => void;
  onRegenerate?: () => void;
  regenerating?: boolean;
}

function Viewer({ materialId, data, onPractice, onAsk, onRegenerate, regenerating }: Props) {
  const [diagram, setDiagram] = useState<DiagramData>(data);
  const resume = diagram.nodes.some((n) => n.importance);
  useEffect(() => setDiagram(data), [data]);
  const children = useMemo(() => {
    const m: Record<string, string[]> = {};
    diagram.edges.forEach((e) => { (m[e.source] ||= []).push(e.target); });
    return m;
  }, [diagram]);
  const roots = useMemo(() => {
    const targets = new Set(diagram.edges.map((e) => e.target));
    return diagram.nodes.filter((n) => !targets.has(n.id)).map((n) => n.id);
  }, [diagram]);

  // Big mind maps start with their details folded, so labels stay readable.
  const initialCollapsed = useCallback(() => {
    if (diagram.nodes.length <= 18 || !["mindmap", "skillgap"].includes(diagram.kind)) return new Set<string>();
    const depth1 = new Set(roots.flatMap((r) => children[r] || []));
    return new Set([...depth1].filter((id) => (children[id] || []).length > 0));
  }, [diagram, roots, children]);
  const [collapsed, setCollapsed] = useState<Set<string>>(initialCollapsed);
  useEffect(() => setCollapsed(initialCollapsed()), [initialCollapsed]);
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [labelDraft, setLabelDraft] = useState("");
  const [noteDraft, setNoteDraft] = useState("");
  const [msg, setMsg] = useState("");
  const [fullscreen, setFullscreen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const rf = useReactFlow();

  const visible = useMemo(() => {
    const hidden = new Set<string>();
    const hide = (id: string) => (children[id] || []).forEach((c) => {
      if (!hidden.has(c)) { hidden.add(c); hide(c); }
    });
    collapsed.forEach(hide);
    return new Set(diagram.nodes.map((n) => n.id).filter((id) => !hidden.has(id)));
  }, [diagram, collapsed, children]);

  const toggle = useCallback((id: string) => setCollapsed((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  }), []);

  const { nodes, edges } = useMemo(() => {
    const pos = layout(diagram, visible);
    const ns: Node<NodeData>[] = diagram.nodes.filter((n) => visible.has(n.id)).map((n) => ({
      id: n.id, type: "card", position: pos[n.id] || { x: 0, y: 0 },
      data: { node: n, kind: diagram.kind, resume, hasChildren: (children[n.id] || []).length > 0, collapsed: collapsed.has(n.id), onToggle: toggle },
      selected: n.id === selected, ariaLabel: `${roleInfo(n, resume).badge}: ${n.label}`,
    }));
    const es: Edge[] = diagram.edges.filter((e) => visible.has(e.source) && visible.has(e.target)).map((e, i) => ({
      id: `e${i}-${e.source}-${e.target}`, source: e.source, target: e.target, label: e.label || undefined,
      type: diagram.kind === "mindmap" ? "default" : "smoothstep",
      markerEnd: ARROWS.has(diagram.kind) ? { type: MarkerType.ArrowClosed, width: 18, height: 18 } : undefined,
      className: "dg-edge", labelBgPadding: [4, 2] as [number, number], labelBgBorderRadius: 4,
    }));
    return { nodes: ns, edges: es };
  }, [diagram, visible, children, collapsed, toggle, selected, resume]);

  // Keep text readable: never shrink below ~55% on a computer; phones may go a bit smaller (then pan).
  const fit = useCallback(() => rf.fitView({
    padding: 0.15, minZoom: (wrapRef.current?.clientWidth || 1000) < 640 ? 0.4 : 0.55, maxZoom: 1.2,
    duration: reducedMotion() ? 0 : 300,
  }), [rf]);
  useEffect(() => { const t = window.setTimeout(fit, 60); return () => window.clearTimeout(t); }, [visible.size, fit, fullscreen]);

  useEffect(() => {
    const onFs = () => setFullscreen(document.fullscreenElement === wrapRef.current);
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  const sel = diagram.nodes.find((n) => n.id === selected) || null;
  useEffect(() => { setEditing(false); setLabelDraft(sel?.label || ""); setNoteDraft(sel?.note || ""); setMsg(""); }, [selected]); // eslint-disable-line react-hooks/exhaustive-deps

  const updateNode = (id: string, patch: Partial<DNode>) =>
    setDiagram((d) => ({ ...d, nodes: d.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)) }));

  const saveEdit = async (patch: { label?: string; note?: string }) => {
    if (!sel || !materialId) return;
    try {
      await api.editNode(materialId, sel.id, patch);
      updateNode(sel.id, patch);
      setEditing(false);
      setMsg("Saved.");
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  const setStatus = async (status: NonNullable<DNode["status"]>) => {
    if (!sel || !materialId) return;
    try {
      await api.setProgressItem(`roadmap:${materialId}:${sel.id}`, status);
      updateNode(sel.id, { status });
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  const exportImage = async (format: "png" | "svg") => {
    setMsg("");
    const viewport = wrapRef.current?.querySelector<HTMLElement>(".react-flow__viewport");
    const shown = rf.getNodes();
    if (!viewport || shown.length === 0) {
      setMsg("There is nothing to export yet.");
      return;
    }
    const bounds = getNodesBounds(shown);
    const width = Math.min(4000, Math.max(800, Math.ceil(bounds.width + 120)));
    const height = Math.min(4000, Math.max(500, Math.ceil(bounds.height + 120)));
    const vp = getViewportForBounds(bounds, width, height, 0.2, 2, 0.06);
    const bg = getComputedStyle(document.body).getPropertyValue("--paper").trim() || "#ffffff";
    const opts = {
      backgroundColor: bg, width, height, pixelRatio: 2,
      // Fonts come from Google's site, which the browser won't let us copy into
      // the image; the export uses the system sans-serif font instead.
      skipFonts: true,
      style: { width: `${width}px`, height: `${height}px`, transform: `translate(${vp.x}px, ${vp.y}px) scale(${vp.zoom})` },
    };
    try {
      const url = format === "png" ? await toPng(viewport, opts) : await toSvg(viewport, opts);
      if (!url || url.length < 2000) throw new Error("empty image");
      const a = document.createElement("a");
      a.href = url;
      a.download = `${(diagram.title || "diagram").replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.${format}`;
      a.click();
      setMsg(`Downloaded as ${format.toUpperCase()}.`);
    } catch {
      setMsg("The image could not be created in this browser. Try the other format or Print.");
    }
  };

  const goFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await wrapRef.current?.requestFullscreen();
    } catch {
      setMsg("Full screen is not available here.");
    }
  };

  const legendRoles = [...new Set(diagram.nodes.map((n) => n.role))].filter((r) => ROLE[r]);

  return (
    <div className={`dg-wrap ${fullscreen ? "is-fullscreen" : ""}`} ref={wrapRef}>
      <div className="dg-toolbar" role="toolbar" aria-label="Diagram controls">
        <button onClick={fit}>Fit to view</button>
        <button onClick={() => { setCollapsed(new Set()); setSelected(null); }}>Expand all</button>
        <button onClick={() => { setCollapsed(initialCollapsed()); setSelected(null); window.setTimeout(fit, 60); }}>Reset</button>
        <button onClick={goFullscreen}>{fullscreen ? "Exit full screen" : "Full screen"}</button>
        <button onClick={() => exportImage("png")}>Download PNG</button>
        <button onClick={() => exportImage("svg")}>Download SVG</button>
        {onRegenerate && <button onClick={onRegenerate} disabled={regenerating}>{regenerating ? "Regenerating…" : "Regenerate"}</button>}
      </div>
      {msg && <p className="dg-msg" role="status">{msg}</p>}
      <div className="dg-body">
        <div className="dg-canvas" aria-label={`${diagram.title}. Use Tab to move between parts and Enter to open one.`}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodeClick={(_, n) => setSelected(n.id)}
            onPaneClick={() => setSelected(null)}
            onSelectionChange={({ nodes: s }) => { if (s[0]) setSelected(s[0].id); }}
            nodesDraggable
            nodesConnectable={false}
            edgesFocusable={false}
            minZoom={0.3}
            maxZoom={2}
            proOptions={{ hideAttribution: false }}
            fitView
          >
            <Background gap={22} size={1} />
            <Controls showInteractive={false} />
            {diagram.nodes.length > 12 && <MiniMap pannable zoomable ariaLabel="Overview of the whole diagram" />}
          </ReactFlow>
        </div>
        <aside className="dg-panel" aria-live="polite">
          {!sel ? (
            <>
              <h3>{diagram.title}</h3>
              {diagram.summary && <p>{diagram.summary}</p>}
              <p className="muted">Click any box to see its explanation{materialId ? ", add a note" : ""} or practise it. Drag to move around, scroll or pinch to zoom.</p>
              <ul className="dg-legend" aria-label="Legend">
                {legendRoles.map((r) => (
                  <li key={r}><span className={`dg-chip ${ROLE[r].cls}`} aria-hidden="true">{ROLE[r].icon}</span>{roleInfo({ role: r }, resume).badge}</li>
                ))}
              </ul>
            </>
          ) : (
            <>
              <p className="dg-kicker">{roleInfo(sel, resume).badge}</p>
              {editing ? (
                <div className="dg-edit">
                  <label>Label<input value={labelDraft} maxLength={70} onChange={(e) => setLabelDraft(e.target.value)} /></label>
                  <div className="row-actions">
                    <button className="primary" onClick={() => saveEdit({ label: labelDraft })} disabled={!labelDraft.trim()}>Save label</button>
                    <button onClick={() => setEditing(false)}>Cancel</button>
                  </div>
                </div>
              ) : (
                <h3>{sel.label} {materialId && <button className="link" onClick={() => setEditing(true)}>Edit</button>}</h3>
              )}
              {sel.detail && <p>{sel.detail}</p>}
              {sel.evidence && <p className="dg-evidence"><b>Evidence:</b> {sel.evidence}</p>}
              {sel.importance && <p className="muted">The job lists this as {sel.importance}.</p>}
              {diagram.kind === "roadmap" && sel.role === "task" && materialId && (
                <label className="dg-status-pick">Progress
                  <select value={sel.status || "pending"} onChange={(e) => void setStatus(e.target.value as NonNullable<DNode["status"]>)}>
                    <option value="pending">To do</option>
                    <option value="in_progress">In progress</option>
                    <option value="done">Done</option>
                  </select>
                </label>
              )}
              {sel.questions && sel.questions.length > 0 && (
                <>
                  <h4>Practice questions</h4>
                  <ul className="plain dots">{sel.questions.map((q) => <li key={q}>{q}</li>)}</ul>
                </>
              )}
              <div className="row-actions wrap">
                {onPractice && <button className="primary" onClick={() => onPractice(sel.label, sel.questions || [])}>Practise this with the coach</button>}
                {onAsk && <button onClick={() => onAsk(sel)}>Ask the assistant</button>}
              </div>
              {materialId && (
                <div className="dg-note">
                  <label>My note<textarea rows={3} maxLength={1000} value={noteDraft} onChange={(e) => setNoteDraft(e.target.value)} /></label>
                  <button onClick={() => saveEdit({ note: noteDraft })}>Save note</button>
                </div>
              )}
              <button className="quiet" onClick={() => setSelected(null)}>Back to overview</button>
            </>
          )}
        </aside>
      </div>
    </div>
  );
}

export default function DiagramViewer(props: Props) {
  if (!props.data?.nodes?.length) {
    return <p className="error-text">This diagram has no content. Try regenerating it.</p>;
  }
  return (
    <ReactFlowProvider>
      <Viewer {...props} />
    </ReactFlowProvider>
  );
}
