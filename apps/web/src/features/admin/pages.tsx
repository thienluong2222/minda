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
  Status,
  useWork,
} from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Templates } from "@/features/templates/pages";
import { api, formatDate, labels, patch, post, size } from "@/lib/api";
import type {
  Artifact,
  Audit,
  Capabilities,
  Experiment,
  Job,
  Meeting,
  Preset,
  User,
} from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Database, Plus, UploadCloud } from "lucide-react";
import { useState } from "react";
import { Link, Route, Routes } from "react-router-dom";

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
            <div className="stat-card stat-dark">
              <span>Tài khoản</span>
              <strong>{d.users}</strong>
              <small>Được quản trị trong hệ thống</small>
            </div>
            <div className="stat-card">
              <span>Cuộc họp</span>
              <strong>{d.meetings}</strong>
              <small>Không bao gồm thùng rác</small>
            </div>
            <div className="stat-card">
              <span>Tác vụ đang chờ</span>
              <strong>{d.jobs.queued || 0}</strong>
              <small>{d.jobs.running || 0} tác vụ đang chạy</small>
            </div>
            <div className="stat-card">
              <span>Tác vụ cần kiểm tra</span>
              <strong>
                {(d.jobs.failed || 0) + (d.jobs.interrupted || 0)}
              </strong>
              <small>Tổng lịch sử lỗi & gián đoạn</small>
            </div>
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
              <Link className="panel-link" to="/admin/models">
                Kiểm tra cấu hình
                <ArrowUpRight size={16} />
              </Link>
            </Panel>
          </div>
        </>
      ) : (
        <Loading />
      )}
    </>
  );
}

function UsersPage() {
  const self = useUser();
  const data = useQuery({
    queryKey: ["users"],
    queryFn: () => api<User[]>("/admin/users"),
  });
  const [open, setOpen] = useState(false),
    [username, setUsername] = useState(""),
    [name, setName] = useState(""),
    [password, setPassword] = useState(""),
    [role, setRole] = useState("user"),
    [reset, setReset] = useState<User | null>(null);
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
        <ErrorBox error={data.error} />
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Người dùng</th>
                <th>Vai trò</th>
                <th>Trạng thái</th>
                <th>Ngày tạo</th>
                <th>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {data.data?.map((u) => (
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
                    <Status value={u.active ? "ready" : "cancelled"} />
                  </td>
                  <td>{formatDate(u.created_at)}</td>
                  <td>
                    <div className="row wrap">
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
    </>
  );
}

function JobsPage() {
  const data = useQuery({
    queryKey: ["admin-jobs"],
    queryFn: () => api<Job[]>("/admin/jobs"),
    refetchInterval: 3000,
  });
  const [state, setState] = useState(""),
    [log, setLog] = useState<string | null>(null);
  const { work } = useWork();
  return (
    <>
      <PageHeader
        eyebrow="VẬN HÀNH"
        title="Tác vụ xử lý"
        description="Theo dõi tối đa 200 tác vụ gần nhất của tất cả tài khoản."
      />
      <Panel>
        <div className="list-toolbar">
          <h2>Hàng đợi & lịch sử</h2>
          <select
            aria-label="Lọc tác vụ theo trạng thái"
            value={state}
            onChange={(e) => setState(e.target.value)}
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
              {data.data
                ?.filter((j) => !state || j.state === state)
                .map((j) => (
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
                      <p>{j.stage}</p>
                      {j.error && (
                        <small className="warning-text">
                          {j.error.message}
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
        {!data.data?.length && <Empty title="Chưa có tác vụ xử lý" />}
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
      <div className="form-grid">
        <label>
          Nhận diện người nói
          <select
            value={value.identity_method}
            onChange={(e) =>
              setValue({ ...value, identity_method: e.target.value })
            }
          >
            <option value="prototype_cosine">ECAPA · prototype cosine</option>
            <option value="mfcc_knn">MFCC · KNN</option>
          </select>
        </label>
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
      </div>
      <label>
        Phương pháp dung hợp
        <select
          value={value.fusion_method}
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
      <label>
        Thể thức mặc định
        <select
          value={value.default_format}
          onChange={(e) =>
            setValue({ ...value, default_format: e.target.value })
          }
        >
          <option value="nd30_2020">Nghị định 30</option>
          <option value="hd05_2026">Hướng dẫn 05</option>
        </select>
      </label>
      <label className="check-label">
        <input
          type="checkbox"
          checked={value.use_model}
          onChange={(e) => setValue({ ...value, use_model: e.target.checked })}
        />
        Mặc định bật LLM khi tạo biên bản
      </label>
      <Notice tone="info">
        Mỗi tác vụ lưu một bản preset tại lúc xếp hàng. Thay đổi ở đây áp dụng
        cho tác vụ mới.
      </Notice>
      <Button disabled={busy} type="submit">
        Lưu cấu hình · revision {value.revision}
      </Button>
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
  const jobs = useQuery({
    queryKey: ["admin-jobs"],
    queryFn: () => api<Job[]>("/admin/jobs"),
    refetchInterval: 3000,
  });
  const [selected, setSelected] = useState<Artifact | null>(null),
    [confirm, setConfirm] = useState(false);
  const { busy, work } = useWork();
  const own = useUser();
  const entries =
    jobs.data?.filter((j) =>
      ["backup_system", "restore_system"].includes(j.kind),
    ) || [];
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
  const data = useQuery({
    queryKey: ["audit"],
    queryFn: () => api<Audit[]>("/admin/audit"),
    refetchInterval: 5000,
  });
  const [search, setSearch] = useState("");
  return (
    <>
      <PageHeader
        eyebrow="TRUY VẾT"
        title="Nhật ký hệ thống"
        description="300 sự kiện gần nhất: thay đổi tài khoản, tài nguyên, phiên bản và tác vụ."
      />
      <Panel>
        <Input
          placeholder="Lọc theo thao tác, mã tài nguyên…"
          aria-label="Lọc nhật ký"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
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
              {data.data
                ?.filter((e) =>
                  JSON.stringify(e)
                    .toLowerCase()
                    .includes(search.toLowerCase()),
                )
                .map((e) => (
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
      </Panel>
    </>
  );
}

function ExperimentsPage() {
  const data = useQuery({
    queryKey: ["experiments"],
    queryFn: () => api<Experiment[]>("/admin/experiments"),
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
          {data.data?.length ? (
            data.data.map((e) => (
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
        </Panel>
      </div>
    </>
  );
}

export function Admin() {
  return (
    <Routes>
      <Route index element={<Overview />} />
      <Route path="users" element={<UsersPage />} />
      <Route path="jobs" element={<JobsPage />} />
      <Route path="models" element={<ModelsPage />} />
      <Route path="templates" element={<Templates sharedOnly />} />
      <Route path="backups" element={<BackupsPage />} />
      <Route path="audit" element={<AuditPage />} />
      <Route path="experiments" element={<ExperimentsPage />} />
      <Route
        path="*"
        element={<Empty title="Không tìm thấy trang quản trị" />}
      />
    </Routes>
  );
}
