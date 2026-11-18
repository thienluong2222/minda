import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  FileText,
  Network,
  Search,
  X,
} from "lucide-react";
import { Empty, ErrorBox, Loading, Notice } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, api, formatDate, time } from "@/lib/api";
import type { Meeting, MinutesVersion, Version } from "@/lib/types";
import { GraphCanvas } from "./graph-canvas";
import { MeetingOutline } from "./outline";
import { edgeKinds, nodeKinds, nodeStyle } from "./graph-data";
import type { GraphEdge, GraphNode, GraphView } from "./graph-data";
import "./graph.css";

interface Page<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
}
interface GraphMeta {
  graph_id: string;
  node_count: number;
  edge_count: number;
}

function Kind({ node }: { node: GraphNode }) {
  const style =
    node.attributes.editorial_role === "review"
      ? { label: "Lời chép chưa rõ", color: "#8a5b12" }
      : nodeStyle(node.kind);
  return (
    <span className="meeting-graph-kind">
      <i style={{ background: style.color }} />
      {style.label}
    </span>
  );
}
function Pager({
  page,
  total,
  limit,
  onChange,
  disabled = false,
}: {
  page: number;
  total: number;
  limit: number;
  onChange: (n: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="meeting-graph-pager">
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Trang đồ thị trước"
        disabled={disabled || page <= 1}
        onClick={() => onChange(page - 1)}
      >
        <ChevronLeft size={16} />
      </Button>
      <span>
        {page} / {Math.max(1, Math.ceil(total / limit))}
      </span>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Trang đồ thị sau"
        disabled={disabled || page * limit >= total}
        onClick={() => onChange(page + 1)}
      >
        <ChevronRight size={16} />
      </Button>
    </div>
  );
}

export default function MeetingGraphView({ meeting }: { meeting: Meeting }) {
  const [params, setParams] = useSearchParams();
  const versionId = params.get("graph_version") || meeting.active_minutes_id;
  const focus = params.get("graph_node") || "";
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [searchPage, setSearchPage] = useState(1);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [edge, setEdge] = useState<GraphEdge | null>(null);
  const [layout, setLayout] = useState<"auto" | "concentric" | "breadthfirst">(
    "auto",
  );
  const [viewMode, setViewMode] = useState<"content" | "technical">("content");
  const viewLimit = focus ? (viewMode === "content" ? 8 : 16) : 40;
  const [allEvidence, setAllEvidence] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(search.trim());
      setSearchPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  useEffect(() => {
    setPage(1);
    setSelected(null);
    setEdge(null);
  }, [versionId, focus]);
  useEffect(() => {
    setAllEvidence(false);
  }, [selected?.node_id, edge]);
  const version = useQuery({
    queryKey: ["graph-minutes-version", meeting.id, versionId],
    queryFn: () =>
      api<{ version: MinutesVersion | null; stale: boolean }>(
        `/meetings/${meeting.id}/minutes?version_id=${encodeURIComponent(versionId!)}`,
      ),
    enabled: !!versionId,
  });
  const base = `/meetings/${meeting.id}/minutes/graph`;
  const versionQuery = new URLSearchParams({ version_id: versionId || "" });
  const hasGraph = !!version.data?.version?.graph_id;
  const meta = useQuery({
    queryKey: ["graph-meta", meeting.id, versionId],
    queryFn: () => api<GraphMeta>(`${base}?${versionQuery}`),
    enabled: hasGraph,
    staleTime: Infinity,
  });
  const view = useQuery({
    queryKey: [
      "graph-view",
      meeting.id,
      versionId,
      focus,
      page,
      viewLimit,
      viewMode,
    ],
    queryFn: ({ signal }) =>
      api<GraphView>(
        `${base}/view?${new URLSearchParams({ version_id: versionId!, node_id: focus, page: String(page), limit: String(viewLimit), mode: viewMode })}`,
        { signal },
      ),
    enabled: hasGraph,
    staleTime: Infinity,
  });
  const searching = !!query || !!kind;
  const results = useQuery({
    queryKey: ["graph-search", meeting.id, versionId, query, kind, searchPage],
    queryFn: ({ signal }) =>
      api<Page<GraphNode>>(
        `${base}/nodes?${new URLSearchParams({ version_id: versionId!, q: query, kind, page: String(searchPage), limit: "30" })}`,
        { signal },
      ),
    enabled: hasGraph && searching,
    staleTime: Infinity,
  });
  const history = useQuery({
    queryKey: ["graph-versions", meeting.id, meeting.active_minutes_id],
    queryFn: () =>
      api<{ minutes: Version[] }>(`/meetings/${meeting.id}/history`),
    enabled: !!meeting.active_minutes_id,
  });
  const inspectId = edge?.source || selected?.node_id;
  const detail = useQuery({
    queryKey: ["graph-view", meeting.id, versionId, inspectId, 1, 40],
    queryFn: ({ signal }) =>
      api<GraphView>(
        `${base}/view?${new URLSearchParams({ version_id: versionId!, node_id: inspectId!, page: "1", limit: "40" })}`,
        { signal },
      ),
    enabled: hasGraph && !!inspectId,
    staleTime: Infinity,
  });
  useEffect(() => {
    if (focus && view.data?.focus_id === focus) {
      setSelected(
        view.data.nodes.find((node) => node.node_id === focus) || null,
      );
      setEdge(null);
    }
  }, [focus, view.data]);
  function explore(id: string) {
    const next = new URLSearchParams(params);
    next.set("graph_node", id);
    setPage(1);
    setSelected(null);
    setEdge(null);
    setParams(next);
  }
  function overview() {
    const next = new URLSearchParams(params);
    next.delete("graph_node");
    setPage(1);
    setSelected(null);
    setEdge(null);
    setParams(next);
  }
  const inspectNodes = new Map(
    [...(view.data?.nodes || []), ...(detail.data?.nodes || [])].map((n) => [
      n.node_id,
      n,
    ]),
  );
  const inspected = selected
    ? inspectNodes.get(selected.node_id) || selected
    : null;
  const currentField = (field: "owner" | "deadline" | "condition") =>
    inspected?.attributes.amendments?.[field]?.value ?? inspected?.attributes[field];
  const evidenceIds = edge
    ? edge.evidence_ids
    : (detail.data?.edges || [])
        .filter(
          (e) => e.kind === "evidenced_by" && e.source === selected?.node_id,
        )
        .map((e) => e.target);
  const evidence = [...new Set(evidenceIds)]
    .map((id) => inspectNodes.get(id))
    .filter((n): n is GraphNode => !!n);
  const versionSelect = (
    <div className="meeting-graph-version">
      <label htmlFor="graph-version">Phiên bản biên bản</label>
      <select
        id="graph-version"
        value={versionId || ""}
        onChange={(e) => {
          const next = new URLSearchParams(params);
          next.set("graph_version", e.target.value);
          next.delete("graph_node");
          setSelected(null);
          setEdge(null);
          setPage(1);
          setParams(next);
        }}
      >
        {!(history.data?.minutes || []).some((v) => v.id === versionId) &&
          versionId && <option value={versionId}>Phiên bản đang xem</option>}
        {(history.data?.minutes || []).map((v, i, all) => (
          <option key={v.id} value={v.id}>
            Bản {all.length - i} · {formatDate(v.created_at)}
            {v.id === meeting.active_minutes_id ? " · Hiện tại" : ""}
          </option>
        ))}
      </select>
    </div>
  );
  if (!versionId)
    return (
      <Empty
        title="Chưa có đồ thị cuộc họp"
        description="Tạo biên bản khi chế độ đồ thị được bật để khám phá chủ đề, sự kiện và căn cứ lời chép tại đây."
        action={
          <Button asChild>
            <Link to={`?tab=minutes`}>Đến phần biên bản</Link>
          </Button>
        }
      />
    );
  if (version.isPending) return <Loading />;
  if (version.error)
    return (
      <ErrorBox error={version.error} onRetry={() => void version.refetch()} />
    );
  if (!hasGraph)
    return (
      <section className="meeting-graph">
        {versionSelect}
        <Empty
          title="Phiên bản này chưa có đồ thị"
          description="Biên bản được tạo trước khi bật đồ thị hoặc bằng chế độ cũ. Hãy tạo một phiên bản biên bản mới khi quản trị viên đã bật chế độ đồ thị."
          action={
            <Button asChild>
              <Link to="?tab=minutes">Đến phần biên bản</Link>
            </Button>
          }
        />
      </section>
    );
  const nodes = searching ? results.data?.items || [] : view.data?.nodes || [];
  const focusNode = view.data?.nodes.find((n) => n.node_id === focus);
  function choose(id: string) {
    const n = view.data?.nodes.find((n) => n.node_id === id);
    if (n) {
      setSelected(n);
      setEdge(null);
    }
  }
  return (
    <section className="meeting-graph" aria-label="Khám phá đồ thị cuộc họp">
      <header className="meeting-graph-header">
        <div className="meeting-graph-title">
          <span className="meeting-graph-mark">
            <Network size={23} />
          </span>
          <div>
            <h2>Đồ thị cuộc họp</h2>
            <p>Đi từ chủ đề đến từng ý kiến và căn cứ lời chép.</p>
          </div>
        </div>
        {versionSelect}
      </header>
      {(version.data?.stale || meeting.minutes_stale) && (
        <Notice tone="warning">
          Đồ thị phản ánh lời chép tại thời điểm tạo phiên bản biên bản này. Nội
          dung cuộc họp đã thay đổi; hãy tạo lại biên bản để cập nhật.
        </Notice>
      )}
      <MeetingOutline
        key={versionId}
        meetingId={meeting.id}
        versionId={versionId}
        onExplore={explore}
      />
      <div className="meeting-graph-summary">
        <span>
          <strong>
            {meta.data?.node_count.toLocaleString("vi-VN") ?? "—"}
          </strong>{" "}
          nút toàn cuộc họp
        </span>
        <span>
          <strong>
            {meta.data?.edge_count.toLocaleString("vi-VN") ?? "—"}
          </strong>{" "}
          liên kết
        </span>
        <span className="meeting-graph-summary-note">
          Chủ đề và sự kiện · Căn cứ mở riêng khi cần
        </span>
      </div>
      <ErrorBox error={meta.error} onRetry={() => void meta.refetch()} />
      <div className="meeting-graph-shell">
        <aside
          className="meeting-graph-browser"
          aria-label="Danh sách nút đồ thị"
        >
          <div className="meeting-graph-browser-tools">
            <h3>Tìm trong cuộc họp</h3>
            <div className="meeting-graph-search">
              <Search size={15} />
              <Input
                aria-label="Tìm nội dung trong đồ thị"
                placeholder="Chủ đề, ý kiến, người nói…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <select
              aria-label="Lọc loại nút"
              value={kind}
              onChange={(e) => {
                setKind(e.target.value);
                setSearchPage(1);
              }}
            >
              <option value="">Tất cả loại nội dung</option>
              {Object.entries(nodeKinds).map(([key, value]) => (
                <option key={key} value={key}>
                  {value.label}
                </option>
              ))}
            </select>
            <div className="meeting-graph-list-caption">
              <span>
                {searching ? "Kết quả toàn đồ thị" : "Trong vùng đang xem"}
              </span>
              <strong>
                {searching ? (results.data?.total ?? "…") : nodes.length}
              </strong>
            </div>
          </div>
          <div className="meeting-graph-node-list">
            {searching && results.isPending && <Loading />}
            <ErrorBox
              error={results.error}
              onRetry={() => void results.refetch()}
            />
            {!nodes.length && !results.isPending && (
              <p className="meeting-graph-no-results">
                Không có nội dung phù hợp.
              </p>
            )}
            {nodes.map((n) => (
              <button
                key={n.node_id}
                className={`meeting-graph-node-row ${selected?.node_id === n.node_id ? "active" : ""}`}
                aria-pressed={selected?.node_id === n.node_id}
                onClick={() => {
                  if (
                    searching &&
                    !view.data?.nodes.some((v) => v.node_id === n.node_id)
                  )
                    explore(n.node_id);
                  else {
                    setSelected(n);
                    setEdge(null);
                  }
                }}
              >
                <Kind node={n} />
                <span>{n.label}</span>
              </button>
            ))}
          </div>
          {searching && results.data && (
            <Pager
              page={searchPage}
              total={results.data.total}
              limit={30}
              onChange={setSearchPage}
            />
          )}
        </aside>
        <div className="meeting-graph-stage">
          <div className="meeting-graph-stage-toolbar">
            <div className="meeting-graph-trail">
              <Button
                variant="ghost"
                size="sm"
                onClick={overview}
                disabled={!focus}
              >
                <ArrowLeft size={14} />
                Tổng quan
              </Button>
              {focusNode && (
                <span title={focusNode.label}>{focusNode.label}</span>
              )}
            </div>
            <select
              aria-label="Mức chi tiết đồ thị"
              value={viewMode}
              onChange={(event) => {
                setViewMode(event.target.value as typeof viewMode);
                setPage(1);
              }}
            >
              <option value="content">Nội dung chính</option>
              <option value="technical">Toàn bộ cấu trúc</option>
            </select>
            <select
              aria-label="Bố cục đồ thị"
              value={layout}
              onChange={(e) => setLayout(e.target.value as typeof layout)}
            >
              <option value="auto">Tự sắp xếp</option>
              <option value="concentric">Tỏa tròn</option>
              <option value="breadthfirst">Phân tầng</option>
            </select>
          </div>
          {view.isPending ? (
            <div className="meeting-graph-stage-empty">
              <Loading />
            </div>
          ) : view.error ? (
            <div className="meeting-graph-stage-empty">
              <ErrorBox
                error={view.error}
                onRetry={() => void view.refetch()}
              />
              {view.error instanceof ApiError &&
                view.error.code === "GRAPH_NODE_NOT_FOUND" && (
                  <Button variant="outline" onClick={overview}>
                    Về tổng quan
                  </Button>
                )}
            </div>
          ) : view.data && view.data.nodes.length ? (
            <GraphCanvas
              data={view.data}
              selected={selected?.node_id || null}
              layout={layout}
              onNode={choose}
              onEdge={(e) => {
                setEdge(e);
                setSelected(null);
              }}
              onExplore={explore}
            />
          ) : (
            <div className="meeting-graph-stage-empty">
              <p>Không có nút ở trang này.</p>
              <Button variant="outline" onClick={() => setPage(1)}>
                Về trang đầu
              </Button>
            </div>
          )}
          <div className="meeting-graph-stage-footer">
            <span aria-live="polite">
              {view.data?.nodes.length ?? 0} nút ·{" "}
              {view.data?.edges.length ?? 0} liên kết đang hiển thị
            </span>
            {view.data && (
              <Pager
                page={page}
                total={view.data.total}
                limit={viewLimit}
                onChange={(p) => {
                  setPage(p);
                  setSelected(null);
                  setEdge(null);
                }}
              />
            )}
          </div>
          {view.data &&
            (view.data.has_more || page > 1 || view.data.truncated) && (
              <p className="meeting-graph-limits">
                {focus
                  ? "Các liên kết của nút được chia theo trang. "
                  : "Các nhóm và chủ đề được chia theo trang. "}
                {view.data.truncated
                  ? "Vùng này còn nội dung; chọn một nút rồi mở liên kết để xem sâu hơn."
                  : "Chuyển trang để xem phần tiếp theo."}
              </p>
            )}
        </div>
        <aside
          className="meeting-graph-inspector"
          aria-label="Chi tiết và căn cứ"
        >
          <div className="meeting-graph-inspector-heading">
            <h3>{edge ? "Quan hệ" : "Chi tiết và căn cứ"}</h3>
            {(inspected || edge) && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Đóng chi tiết nút"
                onClick={() => {
                  setSelected(null);
                  setEdge(null);
                }}
              >
                <X size={16} />
              </Button>
            )}
          </div>
          {!inspected && !edge ? (
            <div className="meeting-graph-inspector-empty">
              <Network size={32} />
              <h3>Mỗi ý đều có ngữ cảnh</h3>
              <p>
                Chọn một nút để đọc đầy đủ nội dung. Mở liên kết để lần theo chủ
                đề, người phát biểu và lời chép gốc.
              </p>
              {focusNode && (
                <Button
                  variant="outline"
                  onClick={() => choose(focusNode.node_id)}
                >
                  Xem nút đang mở
                </Button>
              )}
            </div>
          ) : (
            <div className="meeting-graph-inspector-body">
              {inspected && (
                <>
                  <Kind node={inspected} />
                  <p className="meeting-graph-full-text">{inspected.label}</p>
                  {(inspected.attributes.needs_review ||
                    (inspected.attributes.verification !== "supported" &&
                      !!inspected.attributes.verification)) && (
                    <span className="meeting-graph-review">
                      Cần đối chiếu lại với lời chép
                    </span>
                  )}
                  {inspected.attributes.extraction === "source_fallback" && (
                    <p className="meeting-graph-extraction">
                      Nội dung giữ từ lời chép gốc; chưa được biên tập thành sự
                      kiện hoàn chỉnh.
                    </p>
                  )}
                  <dl className="meeting-graph-properties">
                    {inspected.attributes.speaker && (
                      <>
                        <dt>Người nói</dt>
                        <dd>{inspected.attributes.speaker}</dd>
                      </>
                    )}
                    {inspected.attributes.start_sec != null && (
                      <>
                        <dt>Thời gian</dt>
                        <dd>
                          {time(inspected.attributes.start_sec)} –{" "}
                          {time(
                            inspected.attributes.end_sec ??
                              inspected.attributes.start_sec,
                          )}
                        </dd>
                      </>
                    )}
                    {currentField("owner") && (
                      <>
                        <dt>Phụ trách</dt>
                        <dd>{currentField("owner")}</dd>
                      </>
                    )}
                    {currentField("deadline") && (
                      <>
                        <dt>{inspected.attributes.amendments?.deadline ? "Thời hạn hiện hành" : "Thời hạn"}</dt>
                        <dd>{currentField("deadline")}</dd>
                      </>
                    )}
                    {inspected.attributes.amendments?.deadline && inspected.attributes.deadline && (
                      <>
                        <dt>Thời hạn ban đầu</dt>
                        <dd>{inspected.attributes.deadline}</dd>
                      </>
                    )}
                    {currentField("condition") && (
                      <>
                        <dt>Điều kiện</dt>
                        <dd>{currentField("condition")}</dd>
                      </>
                    )}
                  </dl>
                  <Button
                    variant="outline"
                    className="meeting-graph-explore"
                    onClick={() => explore(inspected.node_id)}
                  >
                    Mở liên kết của nút
                    <ArrowRight size={15} />
                  </Button>
                  {inspected.attributes.sources?.map((source, i) => (
                    <blockquote className="meeting-graph-source" key={i}>
                      <span>
                        <FileText size={13} />
                        {time(source.start_sec)} – {time(source.end_sec)}
                      </span>
                      <p>{source.text}</p>
                    </blockquote>
                  ))}
                </>
              )}
              {edge && (
                <>
                  <span className="meeting-graph-kind">
                    {edgeKinds[edge.kind] || edge.kind}
                  </span>
                  <p className="meeting-graph-full-text">
                    {inspectNodes.get(edge.source)?.label || edge.source}
                  </p>
                  <ArrowRight size={18} />
                  <p className="meeting-graph-full-text">
                    {inspectNodes.get(edge.target)?.label || edge.target}
                  </p>
                  {!edge.asserted && (
                    <p className="meeting-graph-extraction">
                      {edge.weight != null
                        ? "Liên kết gợi ý từ gom cụm."
                        : "Liên kết cần đối chiếu với lời chép."}
                    </p>
                  )}
                  {edge.weight != null && (
                    <p className="meeting-graph-extraction">
                      Mức thuộc cụm: {edge.weight.toFixed(3)}. Giá trị này thể
                      hiện mức liên quan chủ đề, không đo độ chính xác của nội
                      dung.
                    </p>
                  )}
                  <Button
                    variant="outline"
                    onClick={() => explore(edge.source)}
                  >
                    Mở nút nguồn
                    <ArrowRight size={15} />
                  </Button>
                </>
              )}
              {detail.isPending && <Loading />}
              <ErrorBox
                error={detail.error}
                onRetry={() => void detail.refetch()}
              />
              {evidence.length > 0 && (
                <div className="meeting-graph-evidence">
                  <h4>
                    Căn cứ lời chép <span>{evidence.length}</span>
                  </h4>
                  {(allEvidence ? evidence : evidence.slice(0, 5)).map((n) => (
                    <button
                      className="meeting-graph-evidence-card"
                      key={n.node_id}
                      onClick={() => {
                        setSelected(n);
                        setEdge(null);
                      }}
                    >
                      <span>
                        {n.attributes.speaker || "Lời chép"}
                        {n.attributes.start_sec != null
                          ? ` · ${time(n.attributes.start_sec)}`
                          : ""}
                      </span>
                      <p>{n.label}</p>
                    </button>
                  ))}
                  {evidence.length > 5 && (
                    <Button
                      variant="ghost"
                      onClick={() => setAllEvidence((v) => !v)}
                    >
                      {allEvidence
                        ? "Thu gọn"
                        : `Xem ${evidence.length - 5} đoạn còn lại`}
                    </Button>
                  )}
                </div>
              )}
              {detail.data &&
                (detail.data.has_more || detail.data.truncated) && (
                  <p className="meeting-graph-extraction">
                    Đang xem một phần căn cứ và liên kết. Mở nút và chuyển trang
                    để đọc tiếp.
                  </p>
                )}
            </div>
          )}
        </aside>
      </div>
      <footer className="meeting-graph-legend">
        <span>
          <i className="meeting-graph-solid" />
          Quan hệ được trích xuất
        </span>
        <span>
          <i className="meeting-graph-dashed" />
          Liên quan chủ đề / gợi ý
        </span>
        <p>
          Luôn đối chiếu căn cứ trước khi xác nhận quyết định hoặc nhiệm vụ.
        </p>
      </footer>
    </section>
  );
}
