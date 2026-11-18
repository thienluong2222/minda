import { pageSize, useListPage } from "@/lib/pagination";
import { useUser } from "@/app";
import {
  Action,
  DownloadLink,
  Empty,
  ErrorBox,
  JsonDetails,
  Loading,
  Modal,
  Notice,
  PageHeader,
  Panel,
  Pagination,
  Status,
  useWork,
} from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { AdminMeetings } from "@/features/admin/meetings";
import { NotFoundState } from "@/features/auth/pages";
import {
  TemplateDetail,
  TemplateNewPage,
  Templates,
} from "@/features/templates/pages";
import { api, formatDate, labels, patch, post, size } from "@/lib/api";
import { useUnsavedForm } from "@/lib/unsaved";
import type {
  PaginatedResponse,
  Artifact,
  AdminUser,
  Audit,
  Capabilities,
  Experiment,
  Job,
  Meeting,
  Preset,
  User,
} from "@/lib/types";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Database,
  Plus,
  RefreshCw,
  Search,
  UploadCloud,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Route, Routes, useSearchParams } from "react-router-dom";

function Overview() {
  const data = useQuery({
    queryKey: ["admin-overview"],
    queryFn: () =>
      api<{
        users: number;
        meetings: number;
        jobs: Record<string, number>;
        disk: { free_bytes: number; total_bytes: number };
        capabilities: Capabilities;
        database: string;
      }>("/admin/overview"),
    refetchInterval: 5000,
  });
  const d = data.data;
  return (
    <>
      <PageHeader
        eyebrow="QUẢN TRỊ"
        title="Tổng quan hệ thống"
        description="Theo dõi vận hành, hàng đợi và khả năng xử lý của hệ thống."
      />
      <ErrorBox error={data.error} />
      {d ? (
        <>
          <div className="stat-grid four">
            <Link
              className="stat-card stat-dark"
              to="/admin/users"
              aria-label="Xem danh sách tài khoản"
            >
              <span>Tài khoản</span>
              <strong>{d.users}</strong>
              <small>Xem danh sách tài khoản →</small>
            </Link>
            <Link
              className="stat-card"
              to="/admin/meetings"
              aria-label="Xem danh sách cuộc họp"
            >
              <span>Cuộc họp</span>
              <strong>{d.meetings}</strong>
              <small>Xem cuộc họp toàn hệ thống →</small>
            </Link>
            <Link
              className="stat-card"
              to="/admin/jobs?state=queued"
              aria-label="Xem tác vụ đang chờ"
            >
              <span>Tác vụ đang chờ</span>
              <strong>{d.jobs.queued || 0}</strong>
              <small>{d.jobs.running || 0} tác vụ đang chạy →</small>
            </Link>
            <Link
              className="stat-card"
              to="/admin/jobs?state=failed"
              aria-label="Xem tác vụ cần kiểm tra"
            >
              <span>Tác vụ cần kiểm tra</span>
              <strong>
                {(d.jobs.failed || 0) + (d.jobs.interrupted || 0)}
              </strong>
              <small>Xem lịch sử lỗi & gián đoạn →</small>
            </Link>
          </div>
          <div className="two-columns">
            <Panel
              title="Hàng đợi xử lý"
              description="Số lượng tác vụ thực tế theo trạng thái."
            >
              <div className="job-chart">
                {Object.entries(d.jobs).map(([state, count]) => (
                  <div key={state}>
                    <span>{labels[state] || state}</span>
                    <div>
                      <i
                        style={{
                          width: `${(Math.max(0, count) / Math.max(1, ...Object.values(d.jobs))) * 100}%`,
                        }}
                      />
                    </div>
                    <strong>{count}</strong>
                  </div>
                ))}
              </div>
              <Link className="panel-link" to="/admin/jobs">
                Quản lý hàng đợi
                <ArrowUpRight size={16} />
              </Link>
            </Panel>
            <Panel title="Tình trạng vận hành">
              <div className="detail-list">
                <div>
                  <span>API & MongoDB</span>
                  <Status value="ready" />
                </div>
                <div>
                  <span>Worker</span>
                  <Status
                    value={
                      d.capabilities.worker.online ? "ready" : "interrupted"
                    }
                  />
                </div>
                <div>
                  <span>Dung lượng trống trên ổ đĩa</span>
                  <strong>{size(d.disk.free_bytes)}</strong>
                </div>
                <div>
                  <span>Database hiện tại</span>
                  <code>{d.database}</code>
                </div>
                <div>
                  <span>OCR tiếng Việt / Preview DOCX</span>
                  <strong>
                    {d.capabilities.documents.ocr ? "Sẵn sàng" : "Chưa có"} /{" "}
                    {d.capabilities.documents.preview ? "Sẵn sàng" : "Chưa có"}
                  </strong>
                </div>
              </div>
              <div className="row wrap" style={{ gap: 16 }}>
                <Link className="panel-link" to="/admin/system">
                  Tình trạng hệ thống chi tiết
                  <ArrowUpRight size={16} />
                </Link>
                <Link className="panel-link" to="/admin/models">
                  Kiểm tra cấu hình model
                  <ArrowUpRight size={16} />
                </Link>
              </div>
            </Panel>
          </div>
        </>
      ) : data.isPending ? (
        <Loading />
      ) : null}
    </>
  );
}

function UsersPage() {
  const self = useUser();
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page")) || 1);
  const limit = pageSize(params.get("limit"));
  const currentSearch = params.get("q") || "";
  const [search, setSearch] = useState(currentSearch);
  useEffect(() => setSearch(currentSearch), [currentSearch]);
  const data = useQuery({
    queryKey: ["admin-users", params.toString()],
    queryFn: () =>
      api<PaginatedResponse<AdminUser>>(
        "/admin/users?" +
          new URLSearchParams({
            ...Object.fromEntries(params),
            page: String(page),
            limit: String(limit),
          }),
      ),
    placeholderData: keepPreviousData,
    refetchInterval: 5000,
  });
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  }
  const [open, setOpen] = useState(false),
    [username, setUsername] = useState(""),
    [name, setName] = useState(""),
    [password, setPassword] = useState(""),
    [role, setRole] = useState("user"),
    [reset, setReset] = useState<User | null>(null),
    [detailUser, setDetailUser] = useState<AdminUser | null>(null);
  const { busy, work } = useWork();
  return (
    <>
      <PageHeader
        eyebrow="PHÂN QUYỀN"
        title="Tài khoản hệ thống"
        description="Cấp tài khoản, quản lý vai trò và khóa quyền truy cập."
        action={
          <Button
            onClick={() => {
              setPassword("");
              setOpen(true);
            }}
          >
            <Plus size={16} />
            Tạo tài khoản
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
              aria-label="Tìm tài khoản"
              placeholder="Tên hoặc tên đăng nhập…"
              maxLength={200}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <Button variant="ghost" type="submit">
              Tìm
            </Button>
          </form>
          <select
            aria-label="Lọc vai trò tài khoản"
            value={params.get("role") || ""}
            onChange={(event) => filter("role", event.target.value)}
          >
            <option value="">Tất cả vai trò</option>
            <option value="admin">Quản trị viên</option>
            <option value="user">Người dùng</option>
          </select>
          <select
            aria-label="Lọc trạng thái tài khoản"
            value={params.get("active") || ""}
            onChange={(event) => filter("active", event.target.value)}
          >
            <option value="">Tất cả tài khoản</option>
            <option value="true">Đang hoạt động</option>
            <option value="false">Đã khóa</option>
          </select>
          <Button
            variant="outline"
            aria-label="Làm mới danh sách tài khoản"
            disabled={data.isFetching}
            onClick={() => void data.refetch()}
          >
            <RefreshCw size={15} /> Làm mới
          </Button>
        </div>
        <ErrorBox error={data.error} />
        {data.isPending ? (
          <Loading />
        ) : data.data?.items.length === 0 ? (
          <Empty
            title="Không tìm thấy tài khoản"
            description="Thử bỏ bộ lọc hoặc thay đổi từ khóa."
          />
        ) : data.data ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Người dùng</th>
                  <th>Vai trò</th>
                  <th>Trạng thái</th>
                  <th>Cuộc họp</th>
                  <th>Ngày tạo</th>
                  <th>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {data.data?.items.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <strong>{u.display_name}</strong>
                      <small>
                        @{u.username}
                        {u.id === self.id ? " · Bạn" : ""}
                      </small>
                    </td>
                    <td>
                      <select
                        aria-label={"Vai trò " + u.username}
                        value={u.role}
                        disabled={u.id === self.id}
                        onChange={(e) =>
                          void work(
                            () =>
                              patch("/admin/users/" + u.id, {
                                role: e.target.value,
                              }),
                            "Đã cập nhật vai trò",
                          )
                        }
                      >
                        <option value="user">Người dùng</option>
                        <option value="admin">Quản trị viên</option>
                      </select>
                    </td>
                    <td>
                      <Status
                        value={u.active ? "account_active" : "account_locked"}
                      />
                    </td>
                    <td>
                      <Link
                        className="panel-link"
                        to={"/admin/meetings?owner_id=" + u.id}
                      >
                        {u.meeting_count} cuộc họp <ArrowUpRight size={14} />
                      </Link>
                      {!!u.trashed_meeting_count && (
                        <small>
                          <Link
                            to={
                              "/admin/meetings?owner_id=" +
                              u.id +
                              "&trashed=trashed"
                            }
                          >
                            {u.trashed_meeting_count} trong thùng rác
                          </Link>
                        </small>
                      )}
                    </td>
                    <td>{formatDate(u.created_at)}</td>
                    <td>
                      <div className="row wrap">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setDetailUser(u)}
                        >
                          Chi tiết
                        </Button>
                        <Action
                          variant="ghost"
                          disabled={u.id === self.id}
                          run={() =>
                            patch("/admin/users/" + u.id, { active: !u.active })
                          }
                        >
                          {u.active ? "Khóa" : "Mở khóa"}
                        </Action>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={u.id === self.id}
                          onClick={() => {
                            setReset(u);
                            setPassword("");
                          }}
                        >
                          Cấp lại mật khẩu
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {data.data && (
          <p className="small muted">
            {data.data.total} tài khoản phù hợp · Tự cập nhật mỗi 5 giây
          </p>
        )}
        <Pagination
          page={page}
          limit={limit}
          total={data.data?.total || 0}
          onPageChange={(next) => filter("page", String(next))}
        />
      </Panel>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title="Tạo tài khoản"
        description="Mật khẩu tối thiểu 10 ký tự. Quản trị viên tự chuyển thông tin truy cập cho người dùng."
      >
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault();
            void work(async () => {
              await post("/admin/users", {
                username,
                display_name: name,
                password,
                role,
              });
              setOpen(false);
              setUsername("");
              setName("");
              setPassword("");
            }, "Đã tạo tài khoản");
          }}
        >
          <label>
            Họ tên
            <Input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
            />
          </label>
          <label>
            Tên đăng nhập
            <Input
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              minLength={3}
              maxLength={48}
              pattern="[A-Za-z0-9_.-]+"
            />
          </label>
          <label>
            Mật khẩu
            <Input
              required
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={10}
              maxLength={128}
              autoComplete="new-password"
            />
          </label>
          <label>
            Vai trò
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="user">Người dùng</option>
              <option value="admin">Quản trị viên</option>
            </select>
          </label>
          <Button type="submit" disabled={busy}>
            Tạo tài khoản
          </Button>
        </form>
      </Modal>
      <Modal
        open={!!reset}
        onOpenChange={(v) => !v && setReset(null)}
        title={"Cấp lại mật khẩu · " + reset?.display_name}
        description="Các phiên đăng nhập hiện tại của người dùng sẽ hết hiệu lực."
      >
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault();
            void work(async () => {
              await post("/users/" + reset!.id + "/password", { password });
              setReset(null);
              setPassword("");
            }, "Đã cấp lại mật khẩu");
          }}
        >
          <Input
            aria-label="Mật khẩu mới"
            required
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={10}
            maxLength={128}
            autoComplete="new-password"
          />
          <Button disabled={busy} type="submit">
            Lưu mật khẩu mới
          </Button>
        </form>
      </Modal>
      <Modal
        open={!!detailUser}
        onOpenChange={(v) => !v && setDetailUser(null)}
        title={"Chi tiết tài khoản · " + (detailUser?.display_name || "")}
        description="Thông tin định danh, quyền hạn và số lượng cuộc họp thuộc sở hữu của tài khoản."
      >
        {detailUser && (
          <div className="stack">
            <div className="detail-list">
              <div>
                <span>Tên hiển thị</span>
                <strong>{detailUser.display_name}</strong>
              </div>
              <div>
                <span>Tên đăng nhập</span>
                <code>@{detailUser.username}</code>
              </div>
              <div>
                <span>Mã định danh (ID)</span>
                <code>{detailUser.id}</code>
              </div>
              <div>
                <span>Vai trò</span>
                <strong>
                  {detailUser.role === "admin" ? "Quản trị viên" : "Người dùng"}
                </strong>
              </div>
              <div>
                <span>Trạng thái</span>
                <Status
                  value={
                    detailUser.active ? "account_active" : "account_locked"
                  }
                />
              </div>
              <div>
                <span>Cuộc họp đang hoạt động</span>
                <strong>{detailUser.meeting_count} cuộc họp</strong>
              </div>
              <div>
                <span>Cuộc họp trong thùng rác</span>
                <strong>{detailUser.trashed_meeting_count} cuộc họp</strong>
              </div>
              <div>
                <span>Ngày tạo</span>
                <span>{formatDate(detailUser.created_at)}</span>
              </div>
            </div>
            <div className="row between wrap" style={{ marginTop: 12 }}>
              <Button asChild variant="outline" size="sm">
                <Link
                  to={`/admin/meetings?owner_id=${detailUser.id}`}
                  onClick={() => setDetailUser(null)}
                >
                  Xem cuộc họp của tài khoản này
                </Link>
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setDetailUser(null)}
              >
                Đóng
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </>
  );
}

function JobsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const paging = useListPage();
  const data = useQuery({
    queryKey: ["admin-jobs", searchParams.toString()],
    queryFn: () =>
      api<PaginatedResponse<Job>>(
        "/admin/jobs?" +
          new URLSearchParams({
            ...Object.fromEntries(searchParams),
            page: String(paging.page),
            limit: String(paging.limit),
          }),
      ),
    placeholderData: keepPreviousData,
    refetchInterval: 3000,
  });
  const caps = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<Capabilities>("/capabilities"),
    refetchInterval: 10000,
  });
  const [state, setState] = useState(searchParams.get("state") || ""),
    [search, setSearch] = useState(searchParams.get("q") || ""),
    [log, setLog] = useState<string | null>(null);
  const { work } = useWork();
  useEffect(() => {
    setState(searchParams.get("state") || "");
    setSearch(searchParams.get("q") || "");
  }, [searchParams]);
  const filtered = data.data?.items || [];
  return (
    <>
      <PageHeader
        eyebrow="VẬN HÀNH"
        title="Tác vụ xử lý"
        description="Theo dõi, tìm kiếm và điều phối tác vụ của tất cả tài khoản theo từng trang."
      />
      {caps.data && !caps.data.worker.online && (
        <Notice tone="warning">
          <strong>Worker xử lý nền hiện chưa phản hồi heartbeat:</strong> Các
          tác vụ có trạng thái <code>running</code> trong cơ sở dữ liệu không
          đồng nghĩa tiến trình đang chạy. Hãy kiểm tra dịch vụ worker hoặc xem{" "}
          <Link to="/admin/system" className="green-text">
            Tình trạng hệ thống
          </Link>
          .
        </Notice>
      )}
      <Panel>
        <div className="list-toolbar">
          <div className="search-field" style={{ maxWidth: 340 }}>
            <Search size={17} />
            <input
              aria-label="Tìm kiếm tác vụ hệ thống"
              placeholder="Lọc theo người dùng, loại tác vụ, mã ID…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                const next = new URLSearchParams(searchParams);
                if (e.target.value.trim()) next.set("q", e.target.value.trim());
                else next.delete("q");
                next.delete("page");
                setSearchParams(next);
              }}
            />
          </div>
          <select
            aria-label="Lọc tác vụ theo trạng thái"
            value={state}
            onChange={(e) => {
              setState(e.target.value);
              const next = new URLSearchParams(searchParams);
              if (e.target.value) next.set("state", e.target.value);
              else next.delete("state");
              next.delete("page");
              setSearchParams(next);
            }}
          >
            <option value="">Tất cả trạng thái</option>
            {[
              "queued",
              "running",
              "failed",
              "interrupted",
              "succeeded",
              "cancelled",
            ].map((s) => (
              <option key={s} value={s}>
                {labels[s]}
              </option>
            ))}
          </select>
          <span className="small muted">{data.data?.total || 0} tác vụ</span>
        </div>
        <ErrorBox error={data.error} />
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Tác vụ / Chủ sở hữu</th>
                <th>Trạng thái</th>
                <th>Công đoạn</th>
                <th>Thời gian</th>
                <th>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((j) => (
                <tr key={j.id}>
                  <td>
                    <strong>{labels[j.kind] || j.kind}</strong>
                    <small>
                      {j.owner_name} · {j.id.slice(0, 8)}
                    </small>
                  </td>
                  <td>
                    <Status value={j.state} />
                  </td>
                  <td>
                    <p className="task-detail-text">{j.stage}</p>
                    {j.error && (
                      <small className="warning-text">{j.error.message}</small>
                    )}
                    {j.state === "interrupted" && (
                      <small className="warning-text">
                        Worker bị gián đoạn giữa chừng. Không hỗ trợ tiếp tục từ
                        checkpoint; hãy chọn &ldquo;Thử lại&rdquo; để chạy lại
                        từ đầu.
                      </small>
                    )}
                  </td>
                  <td>
                    {formatDate(j.created_at)}
                    <small>
                      {j.completed_at
                        ? "Kết thúc: " + formatDate(j.completed_at)
                        : j.started_at
                          ? "Bắt đầu: " + formatDate(j.started_at)
                          : "Chưa chạy"}
                    </small>
                  </td>
                  <td>
                    <div className="column-actions">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          void work(
                            async () =>
                              setLog(
                                (
                                  await api<{ text: string }>(
                                    "/admin/jobs/" + j.id + "/log",
                                  )
                                ).text,
                              ),
                            "",
                          )
                        }
                      >
                        Xem log
                      </Button>
                      {["queued", "running"].includes(j.state) ? (
                        <Action
                          disabled={j.cancel_requested}
                          run={() => post("/admin/jobs/" + j.id + "/cancel")}
                        >
                          Hủy
                        </Action>
                      ) : ["failed", "interrupted", "cancelled"].includes(
                          j.state,
                        ) ? (
                        <Action
                          run={() => post("/admin/jobs/" + j.id + "/retry")}
                        >
                          Thử lại
                        </Action>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!data.data?.items.length && <Empty title="Chưa có tác vụ xử lý" />}
        <Pagination
          page={paging.page}
          limit={paging.limit}
          total={data.data?.total || 0}
          onPageChange={(next) => paging.update("page", String(next))}
        />
      </Panel>
      <Modal
        wide
        open={log !== null}
        onOpenChange={(v) => !v && setLog(null)}
        title="Nhật ký worker"
        description="100.000 ký tự cuối. Log có thể chứa nội dung tài liệu; chỉ quản trị viên được xem."
      >
        <pre className="log-view">{log}</pre>
      </Modal>
    </>
  );
}

function PresetForm({ preset }: { preset: Preset }) {
  const [value, setValue] = useState(preset);
  const { busy, work } = useWork();
  const isDirty = JSON.stringify(value) !== JSON.stringify(preset);
  const unsaved = useUnsavedForm(isDirty && !busy);
  return (
    <form
      className="form-stack"
      onSubmit={(e) => {
        e.preventDefault();
        void work(async () => {
          const next = await api<Preset>("/admin/preset", {
            method: "PUT",
            body: JSON.stringify(value),
          });
          setValue(next);
        }, "Đã lưu preset mới");
      }}
    >
      {unsaved.dialog}
      <h3>Tùy chọn thường dùng</h3>
      <div className="form-grid">
        <label>
          ASR Whisper
          <select
            value={value.asr_variant}
            onChange={(e) =>
              setValue({ ...value, asr_variant: e.target.value })
            }
          >
            <option value="small">Small</option>
            <option value="medium">Medium</option>
          </select>
        </label>
        <label>
          Thể thức mặc định
          <select
            value={value.default_format}
            onChange={(e) =>
              setValue({ ...value, default_format: e.target.value })
            }
          >
            <option value="nd30_2020">Nghị định 30/2020</option>
            <option value="hd05_2026">Hướng dẫn 05/2026</option>
          </select>
        </label>
      </div>
      <label className="check-label">
        <input
          type="checkbox"
          checked={value.use_model}
          onChange={(e) => setValue({ ...value, use_model: e.target.checked })}
        />
        Mặc định bật LLM khi tạo biên bản
      </label>

      <fieldset className="graph-settings">
        <legend>Đồ thị và văn phong biên bản</legend>
        <label className="check-label">
          <input
            type="checkbox"
            role="switch"
            checked={value.minutes_graph_enabled ?? true}
            onChange={(e) =>
              setValue({ ...value, minutes_graph_enabled: e.target.checked })
            }
          />
          Tạo biên bản bằng đồ thị cuộc họp
        </label>
        <p className="muted small">
          Áp dụng cho mọi cuộc họp mới, bất kể thời lượng. Đồ thị lưu chủ đề, sự
          kiện và căn cứ lời chép để biên tập và đối chiếu.
        </p>
        <label className="check-label">
          <input
            type="checkbox"
            role="switch"
            checked={value.minutes_style_learning_enabled ?? true}
            onChange={(e) =>
              setValue({
                ...value,
                minutes_style_learning_enabled: e.target.checked,
              })
            }
          />
          Học văn phong từ biên bản đã được xác nhận
        </label>
        <p className="muted small">
          Chỉ học từ chỉnh sửa đã được người dùng rà soát và xác nhận. Hồ sơ văn
          phong tách riêng khỏi dữ kiện cuộc họp.
        </p>
      </fieldset>

      <h3 style={{ marginTop: 12 }}>Cấu hình thuật toán nâng cao</h3>
      <div className="form-grid">
        <label>
          Nhận diện người nói
          <select
            value={value.identity_method}
            onChange={(e) =>
              setValue({ ...value, identity_method: e.target.value })
            }
          >
            <option value="prototype_cosine">
              WeSpeaker · prototype cosine
            </option>
            <option value="mfcc_knn">MFCC · KNN</option>
          </select>
        </label>
        <label>
          Luồng dung hợp cho ASR
          <select
            value={value.asr_fusion_mode ?? "transcript"}
            onChange={(e) =>
              setValue({
                ...value,
                asr_fusion_mode:
                  e.target.value === "audio" ? "audio" : "transcript",
              })
            }
          >
            <option value="transcript">Dung hợp văn bản sau ASR</option>
            <option value="audio">Gộp âm thanh trước ASR</option>
          </select>
          <small>Áp dụng cho các tác vụ tạo sau khi lưu.</small>
        </label>
        <label>
          Phương pháp dung hợp văn bản
          <select
            value={value.fusion_method}
            disabled={value.asr_fusion_mode === "audio"}
            onChange={(e) =>
              setValue({ ...value, fusion_method: e.target.value })
            }
          >
            {[
              "F1_BEST_SEGMENT",
              "F3_ROVER",
              "F4_ASR_WEIGHTED",
              "F5_RULE_WEIGHTED",
              "F5_RULE_WEIGHTED_CORRECTED",
              "F6_LEARNED",
            ].map((f) => (
              <option value={f} key={f}>
                {f}
              </option>
            ))}
          </select>
        </label>
      </div>

      <Notice tone="info">
        Mỗi tác vụ lưu một bản chụp (snapshot) preset tại thời điểm xếp hàng.
        Thay đổi ở đây chỉ áp dụng cho các tác vụ mới được tạo sau khi lưu.
      </Notice>
      <div className="row wrap">
        {isDirty && (
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => setValue(preset)}
          >
            Hoàn tác
          </Button>
        )}
        <Button disabled={busy} type="submit">
          Lưu cấu hình · revision {value.revision}
        </Button>
      </div>
    </form>
  );
}
function ModelsPage() {
  const caps = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<Capabilities>("/capabilities"),
    refetchInterval: 10000,
  });
  const preset = useQuery({
    queryKey: ["admin-preset"],
    queryFn: () => api<Preset>("/admin/preset"),
  });
  return (
    <>
      <PageHeader
        eyebrow="CẤU HÌNH"
        title="Mô hình & công cụ"
        description="Kiểm tra trọng số đã lưu đệm, runtime và preset cho các tác vụ mới."
      />
      <div className="two-columns">
        <Panel title="Preset xử lý">
          <ErrorBox error={preset.error} />
          {preset.data ? (
            <PresetForm key={preset.data.revision} preset={preset.data} />
          ) : (
            <Loading />
          )}
        </Panel>
        <Panel title="Khả năng xử lý">
          <ErrorBox error={caps.error} />
          {caps.data ? (
            <>
              <div className="capability-list">
                {Object.entries(caps.data.documents)
                  .filter(([, v]) => typeof v === "boolean")
                  .map(([name, ready]) => (
                    <div key={name}>
                      <span>
                        {
                          (
                            {
                              word: "Đọc Word",
                              pdf_text: "Đọc PDF văn bản",
                              ocr: "OCR tiếng Việt",
                              preview: "Render DOCX",
                            } as Record<string, string>
                          )[name]
                        }
                      </span>
                      <Status value={ready ? "ready" : "interrupted"} />
                    </div>
                  ))}
                <div>
                  <span>Worker</span>
                  <Status
                    value={caps.data.worker.online ? "ready" : "interrupted"}
                  />
                </div>
              </div>
              <Notice tone="info">
                Có trọng số trong cache chưa đồng nghĩa model đang ở RAM. Model
                được nạp khi worker chạy tác vụ cần đến nó.
              </Notice>
              <JsonDetails
                value={caps.data.models}
                label="Trạng thái model & bộ nhớ đệm"
              />
              <JsonDetails value={caps.data.runtime} label="Runtime" />
            </>
          ) : (
            <Loading />
          )}
        </Panel>
      </div>
    </>
  );
}

function BackupsPage() {
  const paging = useListPage();
  const jobs = useQuery({
    queryKey: ["admin-jobs", "backups", paging.page, paging.limit],
    queryFn: () =>
      api<PaginatedResponse<Job>>(
        `/admin/jobs?kind=backup_system,restore_system&page=${paging.page}&limit=${paging.limit}`,
      ),
    placeholderData: keepPreviousData,
    refetchInterval: 3000,
  });
  const [selected, setSelected] = useState<Artifact | null>(null),
    [confirm, setConfirm] = useState(false);
  const { busy, work } = useWork();
  const own = useUser();
  const entries = jobs.data?.items || [];
  return (
    <>
      <PageHeader
        eyebrow="DỮ LIỆU"
        title="Sao lưu & khôi phục"
        description="Sao lưu metadata, tài liệu và bằng chứng; trọng số model và phiên đăng nhập không được đóng gói."
        action={
          <Action
            variant="default"
            run={() => post("/admin/backups")}
            message="Đã xếp hàng sao lưu"
          >
            <Database size={16} />
            Tạo bản sao lưu
          </Action>
        }
      />
      <Notice tone="info">
        Khôi phục luôn tạo database và thư mục mới. Hệ thống hiện tại tiếp tục
        dùng database đang có cho đến khi quản trị viên đổi cấu hình và khởi
        động lại.
      </Notice>
      <div className="two-columns">
        <Panel title="Khôi phục từ bản sao lưu">
          <label className="upload-zone compact">
            <UploadCloud size={26} />
            <strong>Chọn file ZIP sao lưu</strong>
            <span>{selected?.name || "File được tạo từ hệ thống này"}</span>
            <input
              type="file"
              accept=".zip"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file)
                  void work(async () => {
                    const form = new FormData();
                    form.append("file", file);
                    setSelected(
                      await post<Artifact>("/admin/backups/upload", form),
                    );
                  }, "Đã tải file sao lưu");
              }}
            />
          </label>
          {selected && (
            <div className="form-stack">
              <p>
                {selected.name} · {size(selected.size_bytes)}
              </p>
              <Button onClick={() => setConfirm(true)}>
                Kiểm tra & khôi phục sang database mới
              </Button>
            </div>
          )}
        </Panel>
        <Panel title="Phạm vi bản sao lưu">
          <div className="detail-list">
            <div>
              <span>Bao gồm</span>
              <p>
                Tài khoản, cuộc họp, mẫu, phiên bản transcript/biên bản, mẫu
                giọng và file bằng chứng.
              </p>
            </div>
            <div>
              <span>Kiểm tra</span>
              <p>Manifest và SHA-256 cho metadata và từng file.</p>
            </div>
            <div>
              <span>Khi khôi phục</span>
              <p>
                Không khôi phục phiên đăng nhập hoặc chạy lại các tác vụ cũ.
              </p>
            </div>
          </div>
        </Panel>
      </div>
      <Panel title="Lịch sử sao lưu & khôi phục">
        {entries.map((j) => (
          <div className="backup-entry" key={j.id}>
            <div className="row between">
              <h3>
                {labels[j.kind]} · {formatDate(j.created_at)}
              </h3>
              <Status value={j.state} />
            </div>
            <p className="muted">{j.error?.message || j.stage}</p>
            {j.result?.backup && (
              <div className="row wrap">
                <DownloadLink
                  artifact={j.result.backup}
                  label="Tải bản sao lưu"
                />
                {j.owner_id === own.id && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setSelected(j.result!.backup!);
                      setConfirm(true);
                    }}
                  >
                    Khôi phục bản này
                  </Button>
                )}
              </div>
            )}
            {j.result?.database && (
              <div className="restore-result">
                <h4>Kết quả khôi phục</h4>
                <code>MEETING_APP_MONGO_DATABASE={j.result.database}</code>
                <code>MEETING_APP_DATA_DIR={j.result.data_directory}</code>
                <p>{j.result.message}</p>
              </div>
            )}
          </div>
        ))}
        {!entries.length && <Empty title="Chưa có bản sao lưu" />}
        <Pagination
          page={paging.page}
          limit={paging.limit}
          total={jobs.data?.total || 0}
          onPageChange={(next) => paging.update("page", String(next))}
        />
      </Panel>
      <Modal
        open={confirm}
        onOpenChange={setConfirm}
        title="Khôi phục sang database mới"
        description="File ZIP được kiểm tra trước khi khôi phục. Sau khi hoàn tất, bạn nhận tên database và đường dẫn dữ liệu để chuyển cấu hình."
      >
        <p>{selected?.name}</p>
        <Action
          run={async () => {
            await post("/admin/restore", {
              confirmation: "RESTORE_TO_NEW_DATABASE",
              artifact_id: selected!.id,
            });
            setConfirm(false);
          }}
        >
          Khôi phục dữ liệu
        </Action>
      </Modal>
    </>
  );
}

function AuditPage() {
  const paging = useListPage();
  const data = useQuery({
    queryKey: ["audit", paging.params.toString()],
    queryFn: () =>
      api<PaginatedResponse<Audit>>(
        "/admin/audit?" +
          new URLSearchParams({
            ...Object.fromEntries(paging.params),
            page: String(paging.page),
            limit: String(paging.limit),
          }),
      ),
    placeholderData: keepPreviousData,
    refetchInterval: 5000,
  });
  const search = paging.params.get("q") || "";
  return (
    <>
      <PageHeader
        eyebrow="TRUY VẾT"
        title="Nhật ký hệ thống"
        description="Tra cứu lịch sử thay đổi tài khoản, tài nguyên, phiên bản và tác vụ theo từng trang."
      />
      <Panel>
        <Input
          placeholder="Lọc theo thao tác, mã tài nguyên…"
          aria-label="Lọc nhật ký"
          value={search}
          onChange={(e) => paging.update("q", e.target.value)}
        />
        <ErrorBox error={data.error} />
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Thời gian</th>
                <th>Thao tác</th>
                <th>Tài khoản</th>
                <th>Tài nguyên / Chi tiết</th>
              </tr>
            </thead>
            <tbody>
              {data.data?.items.map((e) => (
                <tr key={e.id}>
                  <td>{formatDate(e.created_at)}</td>
                  <td>{e.action}</td>
                  <td>
                    <code>{e.owner_id.slice(0, 8)}</code>
                  </td>
                  <td>
                    <code>{e.resource_id}</code>
                    <JsonDetails value={e.details} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination
          page={paging.page}
          limit={paging.limit}
          total={data.data?.total || 0}
          onPageChange={(next) => paging.update("page", String(next))}
        />
      </Panel>
    </>
  );
}

function ExperimentsPage() {
  const paging = useListPage();
  const data = useQuery({
    queryKey: ["experiments", paging.page, paging.limit],
    queryFn: () =>
      api<PaginatedResponse<Experiment>>(
        `/admin/experiments?page=${paging.page}&limit=${paging.limit}`,
      ),
    placeholderData: keepPreviousData,
  });
  const meetings = useQuery({
    queryKey: ["evaluation-meetings"],
    queryFn: () => api<{ items: Meeting[] }>("/meetings?limit=100"),
  });
  const [name, setName] = useState(""),
    [mid, setMid] = useState(""),
    [reference, setReference] = useState(""),
    [notes, setNotes] = useState("");
  const { busy, work } = useWork();
  return (
    <>
      <PageHeader
        eyebrow="NGHIÊN CỨU"
        title="Kiểm tra & đánh giá"
        description="Đo WER/CER từ transcript đang có và văn bản tham chiếu do bạn cung cấp."
      />
      <Notice tone="info">
        Chỉ số trên một mẫu không đại diện cho toàn hệ thống. Chưa có nhãn người
        nói chuẩn nên giao diện không hiển thị DER hoặc độ chính xác người nói.
      </Notice>
      <div className="two-columns">
        <Panel title="Tạo lần đánh giá">
          <form
            className="form-stack"
            onSubmit={(e) => {
              e.preventDefault();
              void work(
                () =>
                  post("/admin/experiments", {
                    name,
                    meeting_id: mid,
                    reference_text: reference,
                    hypothesis_notes: notes,
                  }),
                "Đã tính WER/CER và lưu kết quả",
              );
            }}
          >
            <label>
              Tên thử nghiệm
              <Input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={200}
              />
            </label>
            <label>
              Cuộc họp trong không gian cá nhân
              <select
                required
                value={mid}
                onChange={(e) => setMid(e.target.value)}
              >
                <option value="">Chọn cuộc họp có transcript</option>
                {meetings.data?.items
                  .filter((m) => m.active_transcript_id)
                  .map((m) => (
                    <option value={m.id} key={m.id}>
                      {m.title}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Văn bản tham chiếu đã kiểm tra
              <Textarea
                rows={8}
                required
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                maxLength={100000}
              />
            </label>
            <label>
              Ghi chú điều kiện thử nghiệm
              <Textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                maxLength={2000}
              />
            </label>
            <Button type="submit" disabled={busy}>
              Tính chỉ số & lưu
            </Button>
          </form>
        </Panel>
        <Panel title="Các lần đánh giá">
          <ErrorBox error={data.error} />
          {data.data?.items.length ? (
            data.data.items.map((e) => (
              <div className="experiment-card" key={e.id}>
                <h3>{e.name}</h3>
                <p className="muted small">
                  {formatDate(e.created_at)} ·{" "}
                  {e.transcript_version_id.slice(0, 8)}
                </p>
                <div className="metric-pair">
                  <div>
                    <span>WER</span>
                    <strong>{(e.metrics.wer * 100).toFixed(2)}%</strong>
                  </div>
                  <div>
                    <span>CER</span>
                    <strong>{(e.metrics.cer * 100).toFixed(2)}%</strong>
                  </div>
                </div>
                <p className="small muted">
                  {e.metrics.reference_words} từ tham chiếu · S{" "}
                  {e.metrics.substitutions} / D {e.metrics.deletions} / I{" "}
                  {e.metrics.insertions}
                </p>
                <JsonDetails value={e} label="Dữ liệu và phiên bản mã nguồn" />
              </div>
            ))
          ) : (
            <Empty
              title="Chưa có lần đánh giá"
              description="Cần văn bản tham chiếu thực để tính các chỉ số."
            />
          )}
          <Pagination
            page={paging.page}
            limit={paging.limit}
            total={data.data?.total || 0}
            onPageChange={(next) => paging.update("page", String(next))}
          />
        </Panel>
      </div>
    </>
  );
}

function SystemStatusPage() {
  const overview = useQuery({
    queryKey: ["admin-overview"],
    queryFn: () =>
      api<{
        users: number;
        meetings: number;
        jobs: Record<string, number>;
        disk: { free_bytes: number; total_bytes: number };
        capabilities: Capabilities;
        database: string;
      }>("/admin/overview"),
    refetchInterval: 5000,
  });
  const health = useQuery({
    queryKey: ["system-health"],
    queryFn: () =>
      api<{ status: string; database: string; api_version: string }>("/health"),
    refetchInterval: 10000,
  });

  if (overview.isPending) {
    return <Loading label="Đang kiểm tra tình trạng hệ thống…" />;
  }
  if (overview.error) {
    return (
      <ErrorBox
        error={overview.error as Error}
        onRetry={() => void overview.refetch()}
      />
    );
  }

  const d = overview.data!;
  const caps = d.capabilities;
  const usedBytes = Math.max(0, d.disk.total_bytes - d.disk.free_bytes);
  const usedPct =
    d.disk.total_bytes > 0
      ? Math.round((usedBytes / d.disk.total_bytes) * 100)
      : 0;

  return (
    <div className="page-container--list">
      <PageHeader
        eyebrow="VẬN HÀNH"
        title="Tình trạng hệ thống"
        description="Kiểm tra tiến trình worker heartbeat, hàng đợi xử lý, công cụ OCR/xem trước tài liệu, bộ nhớ đệm model và dung lượng lưu trữ."
        action={
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              void overview.refetch();
              void health.refetch();
            }}
          >
            <RefreshCw size={15} />
            Làm mới trạng thái
          </Button>
        }
      />

      {!caps.worker.online && (
        <Notice tone="warning">
          <strong>Cảnh báo Worker (E06):</strong> Tiến trình worker hiện chưa
          gửi heartbeat định kỳ. Trạng thái <code>running</code> lưu trong cơ sở
          dữ liệu không đồng nghĩa tác vụ đang thực sự chạy. Khi worker khởi
          động lại, các tác vụ hết hạn lease sẽ được chuyển sang trạng thái{" "}
          <em>Gián đoạn (interrupted)</em> để quản trị viên hoặc người dùng bấm{" "}
          <em>Thử lại</em>.
        </Notice>
      )}

      <div className="two-columns">
        <Panel
          title="Dịch vụ lõi & Tiến trình Worker"
          description="Trạng thái phản hồi của API, cơ sở dữ liệu MongoDB và worker xử lý nền."
        >
          <div className="detail-list">
            <div>
              <span>API & Kết nối MongoDB</span>
              <Status
                value={health.data?.status === "ok" ? "ready" : "failed"}
              />
            </div>
            <div>
              <span>Database đang gắn kết</span>
              <code>{d.database}</code>
            </div>
            <div>
              <span>Trạng thái Worker</span>
              <Status value={caps.worker.online ? "ready" : "interrupted"} />
            </div>
            <div>
              <span>Heartbeat gần nhất</span>
              <strong>
                {caps.worker.last_seen
                  ? formatDate(caps.worker.last_seen)
                  : "Chưa ghi nhận"}
              </strong>
            </div>
            <div>
              <span>Tác vụ đang giữ lease</span>
              <strong>{caps.worker.active_job || "Không có"}</strong>
            </div>
            <div>
              <span>Môi trường Runtime</span>
              <span>
                Python {caps.runtime.python} · {caps.runtime.platform}
              </span>
            </div>
          </div>
        </Panel>

        <Panel
          title="Lưu trữ & Công cụ tài liệu"
          description="Dung lượng ổ đĩa máy chủ và các công cụ chuyển đổi DOCX / PDF / OCR."
        >
          <div className="detail-list">
            <div>
              <span>Dung lượng trống</span>
              <strong>
                {size(d.disk.free_bytes)} / {size(d.disk.total_bytes)} (Đã dùng{" "}
                {usedPct}%)
              </strong>
            </div>
            <div>
              <span>Đọc tài liệu Word (.doc / .docx)</span>
              <Status value={caps.documents.word ? "ready" : "interrupted"} />
            </div>
            <div>
              <span>Đọc PDF văn bản</span>
              <Status
                value={caps.documents.pdf_text ? "ready" : "interrupted"}
              />
            </div>
            <div>
              <span>OCR tài liệu scan</span>
              <Status value={caps.documents.ocr ? "ready" : "interrupted"} />
            </div>
            <div>
              <span>Ngôn ngữ OCR khả dụng</span>
              <strong>
                {caps.documents.ocr_languages?.length
                  ? caps.documents.ocr_languages.join(", ")
                  : "Chưa có"}
              </strong>
            </div>
            <div>
              <span>Kết xuất ảnh xem trước DOCX</span>
              <Status
                value={caps.documents.preview ? "ready" : "interrupted"}
              />
            </div>
          </div>
        </Panel>
      </div>

      <div className="two-columns">
        <Panel
          title="Tóm tắt hàng đợi tác vụ"
          description="Số lượng tác vụ theo trạng thái trên toàn hệ thống."
          action={
            <Button asChild variant="outline" size="sm">
              <Link to="/admin/jobs">Mở danh sách tác vụ</Link>
            </Button>
          }
        >
          <div className="detail-list">
            {Object.entries(d.jobs).map(([state, count]) => (
              <div key={state}>
                <span>{labels[state] || state}</span>
                <strong>{count}</strong>
              </div>
            ))}
          </div>
        </Panel>

        <Panel
          title="Giới hạn vận hành & Trọng số Model"
          description="Các ngưỡng cấu hình hiện tại và trạng thái bộ nhớ đệm model."
          action={
            <Button asChild variant="outline" size="sm">
              <Link to="/admin/models">Cấu hình Model & Preset</Link>
            </Button>
          }
        >
          <div className="detail-list">
            <div>
              <span>Số nguồn âm thanh tối đa</span>
              <strong>
                {caps.max_sources} track ({caps.max_source_files} file)
              </strong>
            </div>
            <div>
              <span>Thời lượng âm thanh tối đa</span>
              <strong>
                {Math.round(caps.max_audio_duration_sec / 60)} phút
              </strong>
            </div>
            <div>
              <span>Dung lượng tải lên tối đa</span>
              <strong>{size(caps.max_upload_bytes)}</strong>
            </div>
          </div>
          <JsonDetails
            value={caps.models}
            label="Chi tiết bộ nhớ đệm trọng số model"
          />
        </Panel>
      </div>
    </div>
  );
}

export function Admin() {
  return (
    <Routes>
      <Route index element={<Overview />} />
      <Route path="users" element={<UsersPage />} />
      <Route path="meetings" element={<AdminMeetings />} />
      <Route path="jobs" element={<JobsPage />} />
      <Route path="models" element={<ModelsPage />} />
      <Route path="templates" element={<Templates sharedOnly />} />
      <Route path="templates/new" element={<TemplateNewPage sharedOnly />} />
      <Route path="templates/:id" element={<TemplateDetail />} />
      <Route path="backups" element={<BackupsPage />} />
      <Route path="audit" element={<AuditPage />} />
      <Route path="experiments" element={<ExperimentsPage />} />
      <Route path="system" element={<SystemStatusPage />} />
      <Route
        path="*"
        element={
          <NotFoundState
            title="Không tìm thấy trang quản trị"
            description="Đường dẫn quản trị bạn yêu cầu không tồn tại."
            backTo="/admin"
            backLabel="Về tổng quan quản trị"
          />
        }
      />
    </Routes>
  );
}
