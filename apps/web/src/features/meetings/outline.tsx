import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronRight, ListTree, Link2, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorBox, Loading } from "@/components/common";
import { api } from "@/lib/api";
import { nodeStyle } from "./graph-data";
import { OutlineEditor } from "./outline-editor";
import "./outline.css";

interface OutlineItem {
  item_id: string;
  role: string;
  text: string;
  claim_ids: string[];
  evidence_ids: string[];
  lifecycle?: string;
  owner?: string | null;
  deadline?: string | null;
  condition?: string | null;
  verification?: string;
  priority?: "required" | "optional";
  included?: boolean;
  field_evidence?: Record<string, { unit_id: string; quote: string }>;
}
interface OutlineSection {
  section_id: string;
  title: string;
  summary: string;
  topic_id: string | null;
  item_count: number;
  is_review: boolean;
  writing_status: string;
  items: OutlineItem[];
}
interface OutlineResponse {
  available: boolean;
  items: OutlineSection[];
  total: number;
  metadata?: { item_count: number; review_count: number; plan_id?: string };
}

function OutlineSectionView({
  section,
  base,
  onExplore,
  graphHref,
}: {
  section: OutlineSection;
  base: string;
  onExplore?: (id: string) => void;
  graphHref: (id: string) => string;
}) {
  const [page, setPage] = useState(0);
  const more = useQuery({
    queryKey: ["outline-items", base, section.section_id, page],
    queryFn: ({ signal }) =>
      api<{ items: OutlineItem[] }>(
        `${base.replace("/outline?", "/outline/items?")}&section_id=${encodeURIComponent(section.section_id)}&page=${page}&limit=6`,
        { signal },
      ),
    enabled: page > 0,
    staleTime: Infinity,
  });
  const items = page > 0 ? more.data?.items || [] : section.items;
  return (
    <details
      className={`minutes-outline-section ${section.is_review ? "is-review" : ""}`}
    >
      <summary>
        <ChevronRight size={15} />
        <strong>{section.title}</strong>
        <span>{section.item_count} ý</span>
      </summary>
      {section.summary && (
        <p className="minutes-outline-scope">{section.summary}</p>
      )}
      {more.isFetching && <Loading />}
      <ErrorBox error={more.error} onRetry={() => void more.refetch()} />
      <ol className="minutes-outline-items">
        {items.map((item) => (
          <li key={item.item_id}>
            <div className="minutes-outline-item-header">
              <span style={{ color: nodeStyle(item.role).color }}>
                {section.is_review
                  ? "Lời chép chưa rõ"
                  : nodeStyle(item.role).label}
              </span>
              {item.included === false && <em>Đã lược</em>}
              {item.lifecycle &&
                ["withdrawn", "superseded"].includes(item.lifecycle) && (
                  <em>
                    {item.lifecycle === "withdrawn" ? "Đã rút" : "Đã thay thế"}
                  </em>
                )}
            </div>
            <p>{item.text}</p>
            {(item.owner || item.deadline || item.condition) && (
              <div className="minutes-outline-slots">
                {item.owner && <span>Phụ trách: {item.owner}</span>}
                {item.deadline && <span>Thời hạn: {item.deadline}</span>}
                {item.condition && <span>Điều kiện: {item.condition}</span>}
              </div>
            )}
            {!!Object.keys(item.field_evidence || {}).length && (
              <details className="minutes-outline-field-evidence">
                <summary>Căn cứ từng thuộc tính</summary>
                {Object.entries(item.field_evidence || {}).map(([field, anchor]) => (
                  <p key={field}>
                    {({ owner: "Phụ trách", deadline: "Thời hạn", condition: "Điều kiện",
                      document_version: "Phiên bản tài liệu" } as Record<string, string>)[field]} ·{" "}
                    {onExplore ? (
                      <button type="button" onClick={() => onExplore(anchor.unit_id)}>{anchor.quote}</button>
                    ) : (
                      <Link to={graphHref(anchor.unit_id)}>{anchor.quote}</Link>
                    )}
                  </p>
                ))}
              </details>
            )}
            {onExplore ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onExplore(item.claim_ids[0] || item.item_id)}
              >
                <Link2 size={13} />
                Xem căn cứ
              </Button>
            ) : (
              <Button asChild variant="ghost" size="sm">
                <Link to={graphHref(item.claim_ids[0] || item.item_id)}>
                  <Link2 size={13} />
                  Xem căn cứ
                </Link>
              </Button>
            )}
          </li>
        ))}
      </ol>
      {section.item_count > 6 && (
        <div className="minutes-outline-pagination">
          <Button
            variant="ghost"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            Trước
          </Button>
          <span>
            {page || 1} / {Math.ceil(section.item_count / 6)}
          </span>
          <Button
            variant="ghost"
            size="sm"
            disabled={(page || 1) * 6 >= section.item_count}
            onClick={() => setPage((p) => (p || 1) + 1)}
          >
            Tiếp
          </Button>
        </div>
      )}
    </details>
  );
}

export function MeetingOutline({
  meetingId,
  versionId,
  compact = false,
  onExplore,
  editable = false,
}: {
  meetingId: string;
  versionId: string;
  compact?: boolean;
  onExplore?: (id: string) => void;
  editable?: boolean;
}) {
  const [open, setOpen] = useState(!compact);
  const [editing, setEditing] = useState(false);
  const [page, setPage] = useState(1);
  const base = `/meetings/${meetingId}/minutes/outline?version_id=${encodeURIComponent(versionId)}`;
  const data = useQuery({
    queryKey: ["meeting-outline", meetingId, versionId, page],
    queryFn: ({ signal }) =>
      api<OutlineResponse>(`${base}&page=${page}&limit=6`, { signal }),
    enabled: open,
    staleTime: Infinity,
  });
  return (
    <section className="minutes-outline" aria-label="Dàn ý biên bản">
      <button
        className="minutes-outline-heading"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <ListTree size={19} />
        <span>
          <strong>Dàn ý biên bản</strong>
          <small>Chủ đề, diễn biến, kết luận và phân công có căn cứ</small>
        </span>
        {data.data?.metadata && (
          <span className="minutes-outline-count">
            {data.data.metadata.item_count} ý
          </span>
        )}
        <ChevronDown size={17} className={open ? "is-open" : ""} />
      </button>
      {open && (
        <div className="minutes-outline-body">
          {editable && data.data?.metadata?.plan_id && (
            <Button type="button" variant="outline" size="sm" onClick={() => setEditing(true)}>
              <Pencil size={14} />
              Chỉnh dàn ý
            </Button>
          )}
          {editing && <OutlineEditor meetingId={meetingId} close={() => setEditing(false)} />}
          <p className="minutes-outline-note">
            Dàn ý đã dùng để biên soạn phiên bản này. Mở căn cứ để đối chiếu;
            các ý chưa rõ được giữ riêng cho việc rà soát. Các chủ đề liên quan
            có thể được gộp thành một mục để biên bản liền mạch.
          </p>
          {data.isPending && <Loading />}
          <ErrorBox error={data.error} onRetry={() => void data.refetch()} />
          {data.data && !data.data.available && (
            <p className="minutes-outline-note">
              Phiên bản cũ chưa lưu dàn ý. Tạo lại biên bản từ lời chép để có
              dàn ý và đồ thị được cập nhật.
            </p>
          )}
          {data.data?.available && !data.data.items.length && (
            <p className="minutes-outline-note">
              Chưa có ý đủ rõ để biên soạn nội dung chính.
            </p>
          )}
          <div className="minutes-outline-grid">
            {data.data?.items.map((section) => (
              <OutlineSectionView
                key={`${versionId}-${section.section_id}`}
                section={section}
                base={base}
                onExplore={onExplore}
                graphHref={(id) =>
                  `/meetings/${meetingId}?${new URLSearchParams({ tab: "graph", graph_version: versionId, graph_node: id })}`
                }
              />
            ))}
          </div>
          {data.data && data.data.total > 6 && (
            <div className="minutes-outline-pagination">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Các mục trước
              </Button>
              <span>
                {page} / {Math.ceil(data.data.total / 6)}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page * 6 >= data.data.total}
                onClick={() => setPage((p) => p + 1)}
              >
                Các mục tiếp theo
              </Button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
