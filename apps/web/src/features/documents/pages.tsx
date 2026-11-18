import { pageSize } from "@/lib/pagination";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Download, FileCheck2, History } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DataTable,
  Empty,
  ErrorBox,
  FilterBar,
  Loading,
  PageHeader,
  Pagination,
  RowActions,
  Status,
} from "@/components/common";
import { api, formatDate, formatMeetingDate } from "@/lib/api";
import type { PaginatedResponse, WorkspaceDocumentItem } from "@/lib/types";

const REVIEW_FILTERS = [
  { id: "all", label: "Tất cả biên bản" },
  { id: "reviewed", label: "Đã rà soát" },
  { id: "needs_review", label: "Chưa xác nhận" },
  { id: "stale", label: "Cần cập nhật" },
] as const;

export function DocumentsLibraryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const qParam = searchParams.get("q") || "";
  const limitParam = pageSize(searchParams.get("limit"));
  const reviewParam = searchParams.get("review") || "all";
  const pageParam = Math.max(1, Number(searchParams.get("page") || "1") || 1);

  const [draftQuery, setDraftQuery] = useState(qParam);

  function updateParams(updates: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams);
    for (const [k, v] of Object.entries(updates)) {
      if (!v || v === "all" || (k === "page" && v === "1")) {
        next.delete(k);
      } else {
        next.set(k, v);
      }
    }
    setSearchParams(next);
  }

  const query = useQuery({
    placeholderData: keepPreviousData,
    queryKey: [
      "workspace",
      "documents",
      qParam,
      reviewParam,
      pageParam,
      limitParam,
    ],
    queryFn: () => {
      const qs = new URLSearchParams({
        q: qParam,
        review: reviewParam,
        page: String(pageParam),
        limit: String(limitParam),
      });
      return api<PaginatedResponse<WorkspaceDocumentItem>>(
        `/workspace/documents?${qs.toString()}`,
      );
    },
  });

  const items = query.data?.items || [];
  const total = query.data?.total || 0;
  const hasFilters = Boolean(qParam.trim()) || reviewParam !== "all";

  return (
    <div className="page-container--list">
      <PageHeader
        eyebrow="TÀI NGUYÊN"
        title="Thư viện biên bản"
        description="Tra cứu nhanh bản biên bản đang áp dụng (active version) của từng cuộc họp, kiểm tra tình trạng rà soát và tải file Word (.docx)."
        action={
          <Button asChild variant="outline">
            <Link to="/meetings">Danh sách cuộc họp</Link>
          </Button>
        }
      />

      <FilterBar
        searchValue={draftQuery}
        onSearchChange={(val) => {
          setDraftQuery(val);
          updateParams({ q: val.trim() || null, page: "1" });
        }}
        searchPlaceholder="Tìm theo tên cuộc họp, địa điểm hoặc mẫu biên bản…"
        searchLabel="Tìm kiếm biên bản"
        hasActiveFilters={hasFilters}
        onReset={() => {
          setDraftQuery("");
          setSearchParams(new URLSearchParams());
        }}
        filters={
          <div
            className="minda-filter-pills"
            role="group"
            aria-label="Tình trạng rà soát biên bản"
          >
            {REVIEW_FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                className={
                  "minda-filter-pill" + (reviewParam === f.id ? " active" : "")
                }
                onClick={() => updateParams({ review: f.id, page: "1" })}
              >
                {f.label}
              </button>
            ))}
          </div>
        }
        summary={query.data ? `${total} biên bản` : undefined}
      />

      <ErrorBox
        error={query.error as Error | null}
        onRetry={() => void query.refetch()}
      />

      {query.isPending ? (
        <Loading label="Đang tải thư viện biên bản…" />
      ) : (
        <>
          <DataTable
            label="Danh sách biên bản cuộc họp"
            headers={[
              "Cuộc họp",
              "Mẫu & Phiên bản",
              "Trạng thái rà soát",
              "Cập nhật",
              "Hành động",
            ]}
            isEmpty={items.length === 0}
            empty={
              hasFilters ? (
                <Empty
                  title="Không tìm thấy biên bản khớp bộ lọc"
                  description="Hãy thử đổi bộ lọc trạng thái hoặc từ khóa tìm kiếm."
                  action={
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        setDraftQuery("");
                        setSearchParams(new URLSearchParams());
                      }}
                    >
                      Xóa bộ lọc
                    </Button>
                  }
                />
              ) : (
                <Empty
                  title="Chưa có biên bản nào được xuất bản"
                  description="Sau khi xử lý âm thanh và tạo biên bản trong một cuộc họp, bản biên bản đang áp dụng sẽ xuất hiện tại đây."
                  action={
                    <Button asChild>
                      <Link to="/meetings">Chọn cuộc họp để tạo biên bản</Link>
                    </Button>
                  }
                />
              )
            }
          >
            {items.map((doc) => (
              <tr key={doc.id}>
                <td>
                  <div className="stack compact-stack">
                    <Link
                      to={`/meetings/${doc.meeting_id}?tab=minutes`}
                      style={{ fontWeight: 600 }}
                      title={doc.meeting_title}
                    >
                      {doc.meeting_title}
                    </Link>
                    <small className="muted">
                      Ngày họp: {formatMeetingDate(doc.meeting_date)}
                      {doc.meeting_location ? ` · ${doc.meeting_location}` : ""}
                    </small>
                  </div>
                </td>
                <td>
                  <div className="stack compact-stack">
                    <span>{doc.template_name || "Mẫu biên bản"}</span>
                    <small className="muted">
                      Phiên bản #{doc.version_id.slice(0, 8)}
                    </small>
                  </div>
                </td>
                <td>
                  <div className="stack compact-stack">
                    <Status
                      value={
                        doc.review_status === "stale"
                          ? "stale"
                          : doc.review_status === "reviewed"
                            ? "reviewed"
                            : "minutes_unreviewed"
                      }
                    />
                    {doc.minutes_stale && (
                      <small className="warning-text">
                        Lời chép hoặc nguồn đã thay đổi sau khi tạo bản này
                      </small>
                    )}
                  </div>
                </td>
                <td>
                  <span className="small muted">
                    {formatDate(doc.updated_at)}
                  </span>
                </td>
                <td>
                  <RowActions>
                    <Button asChild variant="outline" size="sm">
                      <Link to={`/meetings/${doc.meeting_id}?tab=minutes`}>
                        <FileCheck2 size={14} />
                        Mở biên bản
                      </Link>
                    </Button>
                    <Button asChild variant="ghost" size="sm">
                      <Link to={`/meetings/${doc.meeting_id}?tab=history`}>
                        <History size={14} />
                        Lịch sử
                      </Link>
                    </Button>
                    {doc.docx && (
                      <a
                        className="download-link"
                        href={`${doc.docx.url}?download=true`}
                        title={
                          doc.minutes_stale
                            ? `Tải phiên bản #${doc.version_id.slice(0, 8)} (Bản cần cập nhật)`
                            : `Tải file Word phiên bản #${doc.version_id.slice(0, 8)}`
                        }
                      >
                        <Download size={14} />
                        {doc.minutes_stale
                          ? `Tải Word (#${doc.version_id.slice(0, 6)} · cũ)`
                          : "Tải Word"}
                      </a>
                    )}
                  </RowActions>
                </td>
              </tr>
            ))}
          </DataTable>

          <Pagination
            page={pageParam}
            limit={limitParam}
            total={total}
            onPageChange={(nextPage) =>
              updateParams({ page: String(nextPage) })
            }
          />
        </>
      )}
    </div>
  );
}
