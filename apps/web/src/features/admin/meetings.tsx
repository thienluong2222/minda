import { pageSize } from "@/lib/pagination";
import { useUser } from "@/app";
import {
  Empty,
  ErrorBox,
  Loading,
  Modal,
  PageHeader,
  Panel,
  Pagination,
  Status,
} from "@/components/common";
import { Button } from "@/components/ui/button";
import { api, formatDate } from "@/lib/api";
import type { AdminMeeting, AdminUser } from "@/lib/types";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { RefreshCw, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

export function AdminMeetings() {
  const self = useUser();
  const [params, setParams] = useSearchParams();
  const currentSearch = params.get("q") || "";
  const [search, setSearch] = useState(currentSearch);
  useEffect(() => setSearch(currentSearch), [currentSearch]);
  const [selected, setSelected] = useState<AdminMeeting | null>(null);
  const limit = pageSize(params.get("limit"));
  const page = Math.max(1, Number(params.get("page")) || 1);
  const data = useQuery({
    queryKey: ["admin-meetings", params.toString()],
    queryFn: () =>
      api<{
        items: AdminMeeting[];
        total: number;
        page: number;
        limit: number;
      }>(
        "/admin/meetings?" +
          new URLSearchParams({
            ...Object.fromEntries(params),
            limit: String(limit),
          }),
      ),
    placeholderData: keepPreviousData,
    refetchInterval: 5000,
  });
  const users = useQuery({
    queryKey: ["admin-user-options"],
    queryFn: () => api<AdminUser[]>("/admin/users"),
    refetchInterval: 10000,
  });
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  }
  return (
    <>
      <PageHeader
        eyebrow="QUẢN TRỊ"
        title="Cuộc họp toàn hệ thống"
        description="Tra cứu cuộc họp của tất cả tài khoản, người sở hữu và trạng thái xử lý."
        action={
          <Button
            variant="outline"
            disabled={data.isFetching}
            aria-label="Làm mới danh sách cuộc họp"
            onClick={() => void data.refetch()}
          >
            <RefreshCw size={16} /> Làm mới
          </Button>
        }
      />
      <Panel>
        <div className="list-toolbar">
          <form
            className="search-field"
            onSubmit={(event) => {
              event.preventDefault();
              filter("q", search.trim());
            }}
          >
            <Search size={17} />
            <input
              aria-label="Tìm cuộc họp hệ thống"
              placeholder="Tên cuộc họp hoặc người sở hữu…"
              maxLength={200}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <Button variant="ghost" type="submit">
              Tìm
            </Button>
          </form>
          <select
            aria-label="Lọc người sở hữu"
            value={params.get("owner_id") || ""}
            onChange={(event) => filter("owner_id", event.target.value)}
          >
            <option value="">Tất cả người sở hữu</option>
            {users.data?.map((user) => (
              <option key={user.id} value={user.id}>
                {user.display_name} · @{user.username}
              </option>
            ))}
          </select>
          <select
            aria-label="Lọc trạng thái cuộc họp hệ thống"
            value={params.get("state") || ""}
            onChange={(event) => filter("state", event.target.value)}
          >
            <option value="">Tất cả trạng thái</option>
            <option value="draft">Bản nháp</option>
            <option value="processing">Đang xử lý</option>
            <option value="transcript_ready">Có transcript</option>
            <option value="minutes_ready">Có biên bản</option>
          </select>
          <select
            aria-label="Lọc thùng rác hệ thống"
            value={params.get("trashed") || "active"}
            onChange={(event) => filter("trashed", event.target.value)}
          >
            <option value="active">Đang sử dụng</option>
            <option value="trashed">Trong thùng rác</option>
            <option value="all">Tất cả cuộc họp</option>
          </select>
        </div>
        <ErrorBox error={data.error} />
        <ErrorBox error={users.error} />
        {data.isPending ? (
          <Loading />
        ) : data.data?.items.length ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Cuộc họp</th>
                  <th>Người sở hữu</th>
                  <th>Trạng thái</th>
                  <th>Kết quả</th>
                  <th>Cập nhật</th>
                  <th>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {data.data.items.map((meeting) => (
                  <tr key={meeting.id}>
                    <td>
                      <strong>{meeting.title}</strong>
                      <small>{meeting.date || "Chưa có ngày họp"}</small>
                      {meeting.trashed && <small>Trong thùng rác</small>}
                    </td>
                    <td>
                      <strong>{meeting.owner_name}</strong>
                      <small>@{meeting.owner_username || "—"}</small>
                    </td>
                    <td>
                      <Status
                        value={meeting.active_job ? "running" : meeting.state}
                      />
                    </td>
                    <td>
                      <small>{meeting.source_count} nguồn ghi âm</small>
                      <small>
                        {meeting.has_transcript
                          ? "Có transcript"
                          : "Chưa có transcript"}
                      </small>
                      <small>
                        {meeting.has_minutes
                          ? meeting.minutes_stale
                            ? "Biên bản cần cập nhật"
                            : "Có biên bản"
                          : "Chưa có biên bản"}
                      </small>
                    </td>
                    <td>{formatDate(meeting.updated_at)}</td>
                    <td>
                      <div className="row wrap">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setSelected(meeting)}
                          aria-label={"Thông tin " + meeting.title}
                        >
                          Thông tin
                        </Button>
                        {meeting.owner_id === self.id && (
                          <Button variant="ghost" size="sm" asChild>
                            <Link to={"/meetings/" + meeting.id}>
                              Mở cuộc họp
                            </Link>
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : !data.error ? (
          <Empty
            title="Không tìm thấy cuộc họp"
            description="Thử thay đổi người sở hữu, trạng thái hoặc phạm vi thùng rác."
          />
        ) : null}
        <Pagination
          page={page}
          limit={limit}
          total={data.data?.total || 0}
          onPageChange={(next) => filter("page", String(next))}
        />
      </Panel>
      <Modal
        open={!!selected}
        onOpenChange={(open) => !open && setSelected(null)}
        title={selected?.title || "Thông tin cuộc họp"}
        description="Thông tin quản lý cuộc họp và trạng thái kết quả."
      >
        {selected && (
          <div className="detail-list">
            <div>
              <span>Người sở hữu</span>
              <strong>
                {selected.owner_name} · @{selected.owner_username || "—"}
              </strong>
            </div>
            <div>
              <span>Ngày họp</span>
              <strong>{selected.date || "Chưa cung cấp"}</strong>
            </div>
            <div>
              <span>Địa điểm</span>
              <strong>{selected.location || "Chưa cung cấp"}</strong>
            </div>
            <div>
              <span>Trạng thái</span>
              <Status
                value={selected.active_job ? "running" : selected.state}
              />
            </div>
            <div>
              <span>Nguồn ghi âm</span>
              <strong>{selected.source_count}</strong>
            </div>
            <div>
              <span>Ngày tạo</span>
              <strong>{formatDate(selected.created_at)}</strong>
            </div>
            <div>
              <span>Cập nhật</span>
              <strong>{formatDate(selected.updated_at)}</strong>
            </div>
            <div>
              <span>Mã cuộc họp</span>
              <code>{selected.id}</code>
            </div>
          </div>
        )}
      </Modal>
    </>
  );
}
