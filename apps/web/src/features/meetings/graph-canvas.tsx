import cytoscape from "cytoscape";
import type { Core, StylesheetJson } from "cytoscape";
import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Maximize2, Minus, Plus } from "lucide-react";
import { edgeKinds, nodeStyle } from "./graph-data";
import type { GraphEdge, GraphView } from "./graph-data";

const style: StylesheetJson = [
  {
    selector: "node",
    style: {
      shape: "round-rectangle",
      width: 132,
      height: 66,
      label: "data(label)",
      "background-color": "#ffffff",
      "border-width": 2,
      "border-color": "data(color)",
      color: "#243044",
      "font-size": 13,
      "min-zoomed-font-size": 10,
      "font-family": "Geist Variable, sans-serif",
      "text-wrap": "wrap",
      "text-max-width": "114px",
      "text-valign": "center",
      "text-halign": "center",
      "text-events": "yes",
      "overlay-opacity": 0,
    },
  },
  {
    selector: 'node[kind = "topic"], node[kind = "topic_group"]',
    style: {
      "background-color": "#f5f0ff",
      "font-weight": 600,
    },
  },
  {
    selector: 'node[kind = "evidence"]',
    style: { "border-style": "dashed", "background-color": "#f8fafc" },
  },
  {
    selector: 'node[state = "withdrawn"], node[state = "superseded"]',
    style: {
      "background-color": "#f1f3f6",
      "border-style": "dashed",
      color: "#64748b",
    },
  },
  {
    selector: "node.focus",
    style: { "border-width": 4, width: 156, height: 82 },
  },
  {
    selector: "node.chosen",
    style: {
      "underlay-color": "#3f7159",
      "underlay-opacity": 0.16,
      "underlay-padding": 8,
    },
  },
  {
    selector: "edge",
    style: {
      width: 1.3,
      "line-color": "#acb6c5",
      "target-arrow-color": "#acb6c5",
      "target-arrow-shape": "triangle",
      "arrow-scale": 0.7,
      "curve-style": "bezier",
      "font-size": 10,
      color: "#475569",
      "text-background-color": "#ffffff",
      "text-background-opacity": 0.95,
      "text-background-padding": "3px",
      "text-rotation": "autorotate",
      "overlay-opacity": 0,
    },
  },
  {
    selector: "edge.inferred",
    style: {
      "line-style": "dashed",
      "line-color": "#a78bca",
      "target-arrow-color": "#a78bca",
    },
  },
  {
    selector: "edge.semantic",
    style: { label: "data(label)", "min-zoomed-font-size": 10 },
  },
  {
    selector: "edge.chosen",
    style: {
      width: 3,
      label: "data(label)",
      "line-color": "#3f7159",
      "target-arrow-color": "#3f7159",
    },
  },
];

export function GraphCanvas({
  data,
  selected,
  layout,
  onNode,
  onEdge,
  onExplore,
}: {
  data: GraphView;
  selected: string | null;
  layout: "auto" | "concentric" | "breadthfirst";
  onNode: (id: string) => void;
  onEdge: (edge: GraphEdge) => void;
  onExplore: (id: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const graph = useRef<Core | null>(null);
  const views = useRef(
    new Map<
      string,
      {
        positions: Record<string, { x: number; y: number }>;
        zoom: number;
        pan: { x: number; y: number };
        layout: string;
      }
    >(),
  );
  const created = useRef(false);
  const currentLayout = useRef(layout);
  currentLayout.current = layout;
  const viewKey = `${data.mode || "technical"}:${data.focus_id || "overview"}:${data.page}:${data.nodes.map((node) => node.node_id).join(",")}`;
  const handlers = useRef({ onNode, onEdge, onExplore });
  handlers.current = { onNode, onEdge, onExplore };
  useEffect(() => {
    if (!host.current) return;
    const previous = views.current.get(viewKey);
    const cy = cytoscape({
      container: host.current,
      style,
      minZoom: 0.12,
      maxZoom: 2.5,
      wheelSensitivity: 0.25,
      pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
      elements: [
        ...data.nodes.map((n) => ({
          data: {
            id: n.node_id,
            kind: n.kind,
            state: n.attributes.lifecycle || "stated",
            color: nodeStyle(n.kind).color,
            label:
              data.mode === "content"
                ? (n.attributes.short_label || n.label).slice(0, 72)
                : n.label.length > 65
                  ? n.label.slice(0, 62) + "…"
                  : n.label,
          },
          position: previous?.positions[n.node_id],
          classes: n.node_id === data.focus_id ? "focus" : "",
        })),
        ...data.edges.map((edge, i) => ({
          data: {
            id: `edge-${i}`,
            source: edge.source,
            target: edge.target,
            label: edgeKinds[edge.kind] || edge.kind,
            edgeIndex: i,
          },
          classes: `${!edge.asserted ? "inferred" : ""} ${data.mode === "content" && !["about", "contains"].includes(edge.kind) ? "semantic" : ""}`,
        })),
      ],
      layout: { name: "preset" },
    });
    graph.current = cy;
    created.current = true;
    cy.on("tap", "node", (e) => handlers.current.onNode(e.target.id()));
    cy.on("dbltap", "node", (e) => handlers.current.onExplore(e.target.id()));
    cy.on("tap", "edge", (e) => {
      cy.edges().removeClass("chosen");
      e.target.addClass("chosen");
      handlers.current.onEdge(data.edges[e.target.data("edgeIndex")]);
    });
    const resize = new ResizeObserver(() => {
      cy.resize();
    });
    resize.observe(host.current);
    return () => {
      const positions: Record<string, { x: number; y: number }> = {};
      cy.nodes().forEach((node) => {
        positions[node.id()] = { ...node.position() };
      });
      views.current.set(viewKey, {
        positions,
        zoom: cy.zoom(),
        pan: { ...cy.pan() },
        layout: currentLayout.current,
      });
      if (views.current.size > 20)
        views.current.delete(views.current.keys().next().value!);
      resize.disconnect();
      cy.destroy();
      graph.current = null;
    };
  }, [data]);
  useEffect(() => {
    const cy = graph.current;
    if (!cy) return;
    const previous = views.current.get(viewKey);
    if (created.current && previous?.layout === layout) {
      cy.nodes().forEach((node) => {
        if (previous.positions[node.id()])
          node.position(previous.positions[node.id()]);
      });
      cy.zoom(previous.zoom);
      cy.pan(previous.pan);
      created.current = false;
      return;
    }
    created.current = false;
    if (layout === "auto" && !data.focus_id) {
      cy.layout({
        name: "grid",
        cols: cy.width() < 450 ? 2 : 3,
        padding: 45,
        avoidOverlap: true,
        spacingFactor: 1.2,
      }).run();
      return;
    }
    cy.layout(
      layout !== "breadthfirst"
        ? {
            name: "concentric",
            animate: false,
            padding: 45,
            minNodeSpacing: 35,
            concentric: (n) =>
              n.id() === data.focus_id
                ? 10
                : n.data("kind") !== "evidence"
                  ? 3
                  : 1,
            levelWidth: () => 1,
          }
        : {
            name: "breadthfirst",
            directed: true,
            spacingFactor: 1.3,
            padding: 45,
            animate: false,
          },
    ).run();
  }, [data, layout]);
  useEffect(() => {
    const cy = graph.current;
    if (!cy) return;
    cy.nodes().removeClass("chosen");
    if (selected) cy.edges().removeClass("chosen");
    if (selected) cy.getElementById(selected).addClass("chosen");
  }, [selected, data]);
  const zoom = (factor: number) => {
    const cy = graph.current;
    if (cy)
      cy.zoom({
        level: cy.zoom() * factor,
        renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 },
      });
  };
  return (
    <div className="meeting-graph-canvas-wrap">
      <div
        ref={host}
        className="meeting-graph-canvas"
        role="img"
        aria-label={`Đồ thị gồm ${data.nodes.length} nút và ${data.edges.length} liên kết. Dùng danh sách bên trái để chọn bằng bàn phím.`}
      />
      <div className="meeting-graph-controls" aria-label="Điều khiển đồ thị">
        <Button
          variant="outline"
          size="icon"
          title="Phóng to"
          aria-label="Phóng to đồ thị"
          onClick={() => zoom(1.3)}
        >
          <Plus size={16} />
        </Button>
        <Button
          variant="outline"
          size="icon"
          title="Thu nhỏ"
          aria-label="Thu nhỏ đồ thị"
          onClick={() => zoom(1 / 1.3)}
        >
          <Minus size={16} />
        </Button>
        <Button
          variant="outline"
          size="icon"
          title="Vừa khung"
          aria-label="Đưa đồ thị vừa khung"
          onClick={() => graph.current?.fit(undefined, 45)}
        >
          <Maximize2 size={16} />
        </Button>
      </div>
      <p className="meeting-graph-hint">
        Kéo để di chuyển · Cuộn để thu phóng · Bấm đúp để mở liên kết
      </p>
    </div>
  );
}
