import { pageSize } from "@/lib/pagination";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  FileSpreadsheet,
  FileText,
  FolderOpen,
} from "lucide-react";
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
import { api, formatDate } from "@/lib/api";
import type { PaginatedResponse, ReviewQueueItem } from "@/lib/types";

const REVIEW_KINDS = [
  { id: "all", label: "Tất cả" },
  { id: "minutes", label: "Biên bản" },
  { id: "transcript", label: "Lời chép" },
  { id: "templates", label: "Mẫu biên bản" },
] as const;

export function ReviewQueuePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const qParam = searchParams.get("q") || "";
  const limitParam = pageSize(searchParams.get("limit"));
  const kindParam = searchParams.get("kind") || "all";
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
    queryKey: ["workspace", "review", qParam, kindParam, pageParam, limitParam],
    queryFn: () => {
      const qs = new URLSearchParams({
        q: qParam,
        kind: kindParam,
        page: String(pageParam),
        limit: String(limitParam),
      });
      return api<PaginatedResponse<ReviewQueueItem>>(
        `/workspace/review?${qs.toString()}`,
      );
    },
  });

  const hasFilters = Boolean(qParam.trim()) || kindParam !== "all";
  const items = query.data?.items || [];
  const total = query.data?.total || 0;

  return (
    <div className="page-container--list">
      <PageHeader
        eyebrow="CÔNG VIỆC"
        title="Hàng đợi cần rà soát"
        description="Tập hợp các cuộc họp có lời chép cần kiểm tra, biên bản chưa xác nhận hoặc cần cập nhật, và mẫu biên bản của bạn đang chờ duyệt."
        action={
          <Button asChild variant="outline">
            <Link to="/meetings">
              <FolderOpen size={16} />
              Danh sách cuộc họp
            </Link>
          </Button>
        }
      />

      <FilterBar
        searchValue={draftQuery}
        onSearchChange={(val) => {
          setDraftQuery(val);
          updateParams({ q: val.trim() || null, page: "1" });
        }}
        searchPlaceholder="Tìm theo tên cuộc họp, mẫu hoặc lý do cần rà…"
        searchLabel="Tìm mục cần rà soát"
        hasActiveFilters={hasFilters}
        onReset={() => {
          setDraftQuery("");
          setSearchParams(new URLSearchParams());
        }}
        filters={
          <div
            className="minda-filter-pills"
            role="group"
            aria-label="Phân loại mục cần rà"
          >
            {REVIEW_KINDS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={
                  "minda-filter-pill" + (kindParam === item.id ? " active" : "")
                }
                onClick={() => updateParams({ kind: item.id, page: "1" })}
              >
                {item.label}
              </button>
            ))}
          </div>
        }
        summary={query.data ? `${total} mục cần rà soát` : undefined}
      />

      <ErrorBox
        error={query.error as Error | null}
        onRetry={() => void query.refetch()}
      />

      {query.isPending ? (
        <Loading label="Đang tổng hợp danh sách cần rà soát…" />
      ) : (
        <>
          <DataTable
            label="Danh sách tài nguyên cần rà soát"
            headers={[
              "Tài nguyên",
              "Lý do cần rà soát",
              "Số mục",
              "Cập nhật",
              "Hành động",
            ]}
            isEmpty={items.length === 0}
            empty={
              hasFilters ? (
                <Empty
                  title="Không có mục cần rà nào khớp bộ lọc"
                  description="Thử xóa từ khóa hoặc chuyển sang nhóm 'Tất cả' để kiểm tra các phần khác."
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
                  title="Không còn mục nào cần rà soát"
                  description="Tất cả lời chép, biên bản và mẫu biên bản của bạn đều đã được kiểm tra và xác nhận."
                  action={
                    <div className="row wrap">
                      <Button asChild>
                        <Link to="/meetings">Xem danh sách cuộc họp</Link>
                      </Button>
                      <Button asChild variant="outline">
                        <Link to="/documents">Mở thư viện biên bản</Link>
                      </Button>
                    </div>
                  }
                />
              )
            }
          >
            {items.map((item) => (
              <tr key={item.id}>
                <td>
                  <div className="stack compact-stack">
                    <div className="row wrap" style={{ gap: 8 }}>
                      {item.resource_type === "template" ? (
                        <FileSpreadsheet size={16} className="muted" />
                      ) : (
                        <FileText size={16} className="muted" />
                      )}
                      <Link
                        to={item.target_url}
                        style={{ fontWeight: 600 }}
                        title={item.title}
                      >
                        {item.title}
                      </Link>
                    </div>
                    <small className="muted">
                      {item.resource_type === "template"
                        ? "Mẫu biên bản"
                        : "Cuộc họp"}{" "}
                      · {item.subtitle}
                    </small>
                  </div>
                </td>
                <td>
                  <div className="stack compact-stack">
                    <div className="row wrap" style={{ gap: 6 }}>
                      {item.reason_codes.map((code) => (
                        <Status key={code} value={code} />
                      ))}
                    </div>
                    <small className="muted">{item.reasons.join(" · ")}</small>
                  </div>
                </td>
                <td>
                  <strong>{item.review_count}</strong>
                  {item.version_id && (
                    <div>
                      <small className="muted">
                        Phiên bản #{item.version_id.slice(0, 8)}
                      </small>
                    </div>
                  )}
                </td>
                <td>
                  <span className="small muted">
                    {formatDate(item.updated_at)}
                  </span>
                </td>
                <td>
                  <RowActions>
                    <Button asChild size="sm">
                      <Link to={item.target_url}>
                        {item.resource_type === "template"
                          ? "Mở duyệt mẫu"
                          : item.target_tab === "minutes"
                            ? "Rà biên bản"
                            : "Rà lời chép"}
                        <ArrowRight size={14} />
                      </Link>
                    </Button>
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
