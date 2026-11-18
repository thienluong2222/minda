import { pageSize } from "@/lib/pagination";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ExternalLink, RotateCcw, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Action,
  DataTable,
  Empty,
  ErrorBox,
  FilterBar,
  Loading,
  Notice,
  PageHeader,
  Pagination,
  RowActions,
  Status,
} from "@/components/common";
import { api, formatDate, jobErrorMessage, labels, post } from "@/lib/api";
import type {
  Capabilities,
  PaginatedResponse,
  WorkspaceJobItem,
} from "@/lib/types";

const JOB_STATES = [
  { id: "all", label: "Tất cả trạng thái" },
  { id: "running", label: "Đang xử lý" },
  { id: "queued", label: "Đang chờ" },
  { id: "failed", label: "Thất bại" },
  { id: "interrupted", label: "Gián đoạn" },
  { id: "succeeded", label: "Hoàn tất" },
  { id: "cancelled", label: "Đã hủy" },
] as const;

const JOB_KINDS = [
  { id: "all", label: "Mọi loại tác vụ" },
  { id: "transcribe", label: "Xử lý âm thanh" },
  { id: "generate_minutes", label: "Tạo biên bản" },
  { id: "edit_facts", label: "Lưu biên bản" },
  { id: "format_minutes", label: "Đổi thể thức" },
  { id: "restore_minutes", label: "Khôi phục biên bản" },
  { id: "ingest_template", label: "Đọc mẫu" },
  { id: "review_template", label: "Duyệt mẫu" },
  { id: "enroll_voice", label: "Tạo hồ sơ giọng" },
] as const;

export function UserJobsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const qParam = searchParams.get("q") || "";
  const limitParam = pageSize(searchParams.get("limit"));
  const stateParam = searchParams.get("state") || "all";
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

  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<Capabilities>("/capabilities"),
    refetchInterval: 10000,
  });

  const query = useQuery({
    placeholderData: keepPreviousData,
    queryKey: [
      "workspace",
      "jobs",
      qParam,
      stateParam,
      kindParam,
      pageParam,
      limitParam,
    ],
    queryFn: () => {
      const qs = new URLSearchParams({
        q: qParam,
        state: stateParam === "all" ? "" : stateParam,
        kind: kindParam === "all" ? "" : kindParam,
        page: String(pageParam),
        limit: String(limitParam),
      });
      return api<PaginatedResponse<WorkspaceJobItem>>(
        `/workspace/jobs?${qs.toString()}`,
      );
    },
    refetchInterval: (q) =>
      q.state.data?.items.some((j) => ["queued", "running"].includes(j.state))
        ? 2500
        : 10000,
  });

  const items = query.data?.items || [];
  const total = query.data?.total || 0;
  const hasFilters =
    Boolean(qParam.trim()) || stateParam !== "all" || kindParam !== "all";

  const workerOffline = capabilities.data?.worker?.online === false;
  const hasActiveOrInterrupted = items.some((j) =>
    ["queued", "running", "interrupted"].includes(j.state),
  );

  function resourceHref(job: WorkspaceJobItem): string | null {
    if (!job.allowed_actions.includes("open_resource")) return null;
    if (job.resource_type === "meeting") {
      const tab = job.kind === "transcribe" ? "sources" : "minutes";
      return `/meetings/${job.resource_id}?tab=${tab}&job=${job.id}`;
    }
    if (job.resource_type === "template") {
      return `/templates/${job.resource_id}`;
    }
    if (job.resource_type === "speaker") {
      return `/voices/${job.resource_id}`;
    }
    return null;
  }

  return (
    <div className="page-container--list">
      <PageHeader
        eyebrow="CÔNG VIỆC"
        title="Tác vụ xử lý của tôi"
        description="Theo dõi tiến độ xử lý âm thanh, tạo biên bản, chuẩn hóa mẫu và đăng ký hồ sơ giọng thuộc tài khoản của bạn."
      />

      {workerOffline && hasActiveOrInterrupted && (
        <Notice tone="warning">
          <strong>Worker xử lý nền hiện chưa phản hồi heartbeat:</strong> Các
          tác vụ đang ở trạng thái <em>Đang chờ</em> hoặc <em>Đang xử lý</em>{" "}
          trong cơ sở dữ liệu có thể bị tạm dừng cho đến khi tiến trình worker
          hoạt động trở lại.{" "}
          {capabilities.data?.worker?.last_seen
            ? `Lần phản hồi gần nhất: ${formatDate(capabilities.data.worker.last_seen)}.`
            : "Chưa ghi nhận phản hồi worker."}
        </Notice>
      )}

      <FilterBar
        searchValue={draftQuery}
        onSearchChange={(val) => {
          setDraftQuery(val);
          updateParams({ q: val.trim() || null, page: "1" });
        }}
        searchPlaceholder="Tìm theo tên cuộc họp, mẫu, loại tác vụ hoặc thông báo lỗi…"
        searchLabel="Tìm kiếm tác vụ"
        hasActiveFilters={hasFilters}
        onReset={() => {
          setDraftQuery("");
          setSearchParams(new URLSearchParams());
        }}
        filters={
          <>
            <select
              aria-label="Lọc theo trạng thái tác vụ"
              value={stateParam}
              onChange={(e) =>
                updateParams({ state: e.target.value, page: "1" })
              }
              style={{ width: "auto", minWidth: 160 }}
            >
              {JOB_STATES.map((st) => (
                <option key={st.id} value={st.id}>
                  {st.label}
                </option>
              ))}
            </select>
            <select
              aria-label="Lọc theo loại tác vụ"
              value={kindParam}
              onChange={(e) =>
                updateParams({ kind: e.target.value, page: "1" })
              }
              style={{ width: "auto", minWidth: 170 }}
            >
              {JOB_KINDS.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.label}
                </option>
              ))}
            </select>
          </>
        }
        summary={query.data ? `${total} tác vụ` : undefined}
      />

      <ErrorBox
        error={query.error as Error | null}
        onRetry={() => void query.refetch()}
      />

      {query.isPending ? (
        <Loading label="Đang tải danh sách tác vụ…" />
      ) : (
        <>
          <DataTable
            label="Danh sách tác vụ cá nhân"
            headers={[
              "Loại tác vụ",
              "Tài nguyên",
              "Trạng thái & giai đoạn",
              "Thời gian",
              "Hành động",
            ]}
            isEmpty={items.length === 0}
            empty={
              hasFilters ? (
                <Empty
                  title="Không tìm thấy tác vụ phù hợp bộ lọc"
                  description="Thử xóa bộ lọc trạng thái hoặc từ khóa tìm kiếm để xem toàn bộ lịch sử tác vụ."
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
                  title="Chưa có tác vụ xử lý nào"
                  description="Khi bạn xử lý âm thanh cuộc họp, tạo biên bản hoặc tải lên mẫu biên bản mới, tiến độ sẽ xuất hiện tại đây."
                  action={
                    <Button asChild>
                      <Link to="/meetings">Mở danh sách cuộc họp</Link>
                    </Button>
                  }
                />
              )
            }
          >
            {items.map((job) => {
              const href = resourceHref(job);
              return (
                <tr key={job.id}>
                  <td>
                    <div className="stack compact-stack">
                      <strong>{labels[job.kind] || job.kind}</strong>
                      <small className="muted">Mã: #{job.id.slice(0, 8)}</small>
                    </div>
                  </td>
                  <td>
                    {href ? (
                      <Link to={href} style={{ fontWeight: 500 }}>
                        {job.resource_title || job.resource_id}
                      </Link>
                    ) : (
                      <span>{job.resource_title || job.resource_id}</span>
                    )}
                  </td>
                  <td>
                    <div className="stack compact-stack">
                      <div className="row wrap" style={{ gap: 6 }}>
                        <Status value={job.state} />
                        {job.cancel_requested && job.state === "running" && (
                          <span className="status-badge warn">
                            Đang chờ dừng
                          </span>
                        )}
                      </div>
                      <small className="muted">{job.stage}</small>
                      {job.error && (
                        <small className="danger-text">
                          <AlertTriangle
                            size={12}
                            style={{ display: "inline", marginRight: 4 }}
                          />
                          {jobErrorMessage(job.error)}
                        </small>
                      )}
                      {job.state === "interrupted" && (
                        <small className="warning-text">
                          Tiến trình worker đã dừng giữa chừng (hết hạn lease).
                          Hệ thống không hỗ trợ tiếp tục từ checkpoint dở dang;
                          hãy nhấn &ldquo;Thử lại&rdquo; để chạy lại tác vụ từ
                          đầu nếu dữ liệu đầu vào chưa đổi.
                        </small>
                      )}
                    </div>
                  </td>
                  <td>
                    <div className="stack compact-stack">
                      <small className="muted">
                        Tạo: {formatDate(job.created_at)}
                      </small>
                      {job.completed_at && (
                        <small className="muted">
                          Xong: {formatDate(job.completed_at)}
                        </small>
                      )}
                    </div>
                  </td>
                  <td>
                    <RowActions>
                      {job.allowed_actions.includes("cancel") && (
                        <Action
                          variant="outline"
                          message="Đã gửi yêu cầu hủy tác vụ"
                          run={() => post(`/jobs/${job.id}/cancel`)}
                        >
                          <Square size={14} />
                          Hủy
                        </Action>
                      )}
                      {job.allowed_actions.includes("retry") && (
                        <Action
                          variant="outline"
                          message="Đã xếp hàng thử lại tác vụ"
                          run={() => post(`/jobs/${job.id}/retry`)}
                        >
                          <RotateCcw size={14} />
                          Thử lại
                        </Action>
                      )}
                      {href && (
                        <Button asChild variant="ghost" size="sm">
                          <Link to={href}>
                            Mở
                            <ExternalLink size={14} />
                          </Link>
                        </Button>
                      )}
                    </RowActions>
                  </td>
                </tr>
              );
            })}
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
