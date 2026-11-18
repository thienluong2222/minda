export interface GraphSource {
  turn_id: string;
  text: string;
  source_id?: string;
  start_sec: number;
  end_sec: number;
}
export interface GraphNode {
  node_id: string;
  kind: string;
  label: string;
  attributes: {
    sources?: GraphSource[];
    speaker?: string;
    start_sec?: number;
    end_sec?: number;
    needs_review?: boolean;
    owner?: string | null;
    deadline?: string | null;
    condition?: string | null;
    amendments?: Partial<Record<"owner" | "deadline" | "condition" | "document_version", { value: string }>>;
    verification?: string;
    lifecycle?: string;
    extraction?: string;
    warnings?: string[];
    short_label?: string;
    summary?: string;
    event_count?: number;
    decision_count?: number;
    task_count?: number;
    editorial_role?: string;
  };
}
export interface GraphEdge {
  source: string;
  target: string;
  kind: string;
  evidence_ids: string[];
  asserted: boolean;
  weight?: number | null;
  projection?: boolean;
}
export interface GraphView {
  nodes: GraphNode[];
  edges: GraphEdge[];
  focus_id: string | null;
  page: number;
  limit: number;
  total: number;
  has_more: boolean;
  truncated: boolean;
  mode?: "content" | "technical";
}
export const nodeKinds: Record<string, { label: string; color: string }> = {
  meeting: { label: "Cuộc họp", color: "#334155" },
  session: { label: "Phiên họp", color: "#64748b" },
  episode: { label: "Phần thảo luận", color: "#64748b" },
  topic_group: { label: "Nhóm chủ đề", color: "#7c3aed" },
  topic: { label: "Chủ đề", color: "#7c3aed" },
  issue: { label: "Vấn đề", color: "#7c3aed" },
  evidence: { label: "Lời chép gốc", color: "#64748b" },
  person: { label: "Người nói", color: "#0369a1" },
  actor: { label: "Người phụ trách", color: "#0369a1" },
  document_version: { label: "Phiên bản tài liệu", color: "#475569" },
  information: { label: "Thông tin", color: "#4f6b60" },
  proposal: { label: "Đề xuất", color: "#2563eb" },
  question: { label: "Câu hỏi", color: "#0891b2" },
  response: { label: "Trả lời", color: "#0891b2" },
  objection: { label: "Phản đối", color: "#be123c" },
  agreement: { label: "Đồng thuận", color: "#15803d" },
  decision: { label: "Quyết định", color: "#15803d" },
  task: { label: "Nhiệm vụ", color: "#b45309" },
  withdrawal: { label: "Rút lại", color: "#be123c" },
  amendment: { label: "Điều chỉnh", color: "#b45309" },
  vote: { label: "Biểu quyết", color: "#15803d" },
  unresolved: { label: "Chưa thống nhất", color: "#be123c" },
  filler: { label: "Lời dẫn", color: "#64748b" },
};
export const edgeKinds: Record<string, string> = {
  contains: "Bao gồm",
  next: "Tiếp theo",
  about: "Liên quan chủ đề",
  spoken_by: "Người phát biểu",
  evidenced_by: "Có căn cứ từ",
  assigned_to: "Giao cho",
  refers_to: "Đề cập",
  supports: "Ủng hộ",
  opposes: "Phản đối",
  amends: "Điều chỉnh",
  withdraws: "Rút lại",
  supersedes: "Thay thế",
  accepts: "Chấp thuận",
  depends_on: "Phụ thuộc",
  applies_to_version: "Áp dụng phiên bản",
  same_topic_candidate: "Có thể cùng chủ đề",
  on_issue: "Thuộc vấn đề",
};
export function nodeStyle(kind: string) {
  return nodeKinds[kind] || { label: kind, color: "#64748b" };
}
