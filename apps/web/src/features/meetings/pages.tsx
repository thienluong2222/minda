import { useUser } from "@/app";
import {
  Action,
  Empty,
  ErrorBox,
  Loading,
  Notice,
  PageHeader,
  Panel,
  Status,
  useWork,
} from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, formatDate, post, size } from "@/lib/api";
import type { Capabilities, Job, Meeting, Template, Voice } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  Check,
  ChevronLeft,
  ChevronRight,
  FileCheck2,
  FileText,
  FolderOpen,
  Plus,
  Search,
  UploadCloud,
  Users,
} from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

export function MeetingTable({
  items,
  trashed = false,
}: {
  items: Meeting[];
  trashed?: boolean;
}) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>Cuộc họp</th>
            <th>Ngày họp</th>
            <th>Trạng thái</th>
            <th>Cập nhật</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((m) => (
            <tr key={m.id}>
              <td>
                <Link to={"/meetings/" + m.id} className="meeting-name">
                  <span className="file-icon">
                    <AudioLines size={19} />
                  </span>
                  <div>
                    <strong>{m.title}</strong>
                    <small>
                      {m.location || "Chưa có địa điểm"} · {m.source_ids.length}{" "}
                      nguồn
                    </small>
                  </div>
                </Link>
              </td>
              <td>
                {m.date
                  ? new Date(m.date).toLocaleDateString("vi-VN")
                  : "Chưa đặt"}
              </td>
              <td>
                <Status value={m.active_job ? "running" : m.state} />
                {m.minutes_stale && (
                  <small className="warning-text">Biên bản cần cập nhật</small>
                )}
              </td>
              <td className="muted">{formatDate(m.updated_at)}</td>
              <td>
                {trashed ? (
                  <Action
                    run={() =>
                      post("/meetings/" + m.id + "/restore", {
                        revision: m.revision,
                      })
                    }
                  >
                    Khôi phục
                  </Action>
                ) : (
                  <Link
                    className="arrow-link"
                    aria-label={"Mở " + m.title}
                    to={"/meetings/" + m.id}
                  >
                    <ArrowUpRight size={18} />
                  </Link>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Dashboard() {
  const user = useUser();
  const data = useQuery({
    queryKey: ["dashboard"],
    queryFn: () =>
      api<{
        counts: Record<string, number>;
        recent_meetings: Meeting[];
        jobs: Job[];
      }>("/dashboard"),
    refetchInterval: 5000,
  });
  const caps = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<Capabilities>("/capabilities"),
    refetchInterval: 15000,
  });
  if (data.isPending) return <Loading />;
  if (data.error) return <ErrorBox error={data.error} />;
  const d = data.data!;
  const cards = [
    ["Cuộc họp", d.counts.meetings, FolderOpen],
    ["Biên bản đã tạo", d.counts.minutes, FileCheck2],
    ["Cần rà soát", d.counts.needs_review, FileText],
  ] as const;
  return (
    <>
      <PageHeader
        eyebrow="TỔNG QUAN"
        title={`Chào ${user.display_name.split(" ").slice(-1)[0]}, một ngày làm việc rõ ràng.`}
        description="Tiếp nối cuộc họp. Hoàn thiện từng biên bản."
        action={
          <Button asChild>
            <Link to="/meetings/new">
              <Plus size={17} />
              Tạo cuộc họp
            </Link>
          </Button>
        }
      />
      <div className="dashboard-grid">
        <div className="dashboard-main">
          <div className="stat-grid">
            {cards.map(([label, value, Icon], i) => (
              <div
                className={`stat-card ${i === 0 ? "stat-dark" : ""}`}
                key={label}
              >
                <div>
                  <span>{label}</span>
                  <Icon size={20} />
                </div>
                <strong>{value.toString().padStart(2, "0")}</strong>
                <small>
                  {i === 0
                    ? "Trong không gian cá nhân"
                    : i === 1
                      ? "File Word có thể chỉnh sửa"
                      : "Đối chiếu trước khi hoàn tất"}
                </small>
              </div>
            ))}
          </div>
          <Panel
            title="Cuộc họp gần đây"
            description="Các cuộc họp được cập nhật gần nhất."
          >
            {d.recent_meetings.length ? (
              <MeetingTable items={d.recent_meetings} />
            ) : (
              <Empty
                title="Bắt đầu với cuộc họp đầu tiên"
                description="Tải bản ghi âm và chọn mẫu. Hệ thống sẽ giúp bạn chuẩn bị biên bản để rà soát."
                action={
                  <Button asChild>
                    <Link to="/meetings/new">
                      <Plus size={16} />
                      Tạo cuộc họp
                    </Link>
                  </Button>
                }
              />
            )}
            <Link className="panel-link" to="/meetings">
              Xem tất cả cuộc họp
              <ArrowRight size={16} />
            </Link>
          </Panel>
        </div>
        <aside className="context-column">
          <div className="workflow-card">
            <span className="eyebrow">QUY TRÌNH LÀM VIỆC</span>
            <h2>
              Từ bản ghi
              <br />
              đến biên bản.
            </h2>
            <div className="workflow-list">
              {[
                [UploadCloud, "Tải nguồn ghi âm", "Một hoặc nhiều thiết bị"],
                [AudioLines, "Chép lời & đối chiếu", "Giữ liên kết bằng chứng"],
                [
                  FileText,
                  "Hoàn thiện nội dung",
                  "Rà soát từng trường dữ liệu",
                ],
                [FileCheck2, "Xuất file Word", "Chọn thể thức phù hợp"],
              ].map(([, title, text], i) => (
                <div key={i}>
                  <span className="workflow-number">0{i + 1}</span>
                  <div>
                    <strong>{String(title)}</strong>
                    <small>{String(text)}</small>
                  </div>
                </div>
              ))}
            </div>
            <Button asChild variant="outline">
              <Link to="/templates">
                Khám phá thư viện mẫu
                <ArrowUpRight size={16} />
              </Link>
            </Button>
          </div>
          <Panel title="Đang diễn ra">
            <div className="worker-indicator">
              <i className={caps.data?.worker.online ? "online" : "offline"} />
              <span>
                {caps.data?.worker.online
                  ? "Worker đang kết nối"
                  : "Worker chưa kết nối"}
              </span>
            </div>
            {d.jobs.length ? (
              d.jobs.slice(0, 4).map((j) => (
                <Link
                  className="activity-item"
                  key={j.id}
                  to={
                    j.resource_type === "meeting"
                      ? "/meetings/" + j.resource_id
                      : "/settings"
                  }
                >
                  <Status value={j.state} />
                  <p>{j.stage}</p>
                  <small>{formatDate(j.created_at)}</small>
                </Link>
              ))
            ) : (
              <p className="muted small">Hiện không có tác vụ cần chú ý.</p>
            )}
          </Panel>
        </aside>
      </div>
    </>
  );
}

export function Meetings({ trashed = false }: { trashed?: boolean }) {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") || "");
  const page = Number(params.get("page") || 1);
  const [filter, setFilter] = useState("all");
  const data = useQuery({
    queryKey: ["meetings", trashed, params.toString()],
    queryFn: () =>
      api<{ items: Meeting[]; total: number }>(
        "/meetings?trashed=" +
          trashed +
          "&page=" +
          page +
          "&q=" +
          encodeURIComponent(params.get("q") || ""),
      ),
    refetchInterval: 5000,
  });
  const items =
    data.data?.items.filter(
      (m) =>
        filter === "all" ||
        (filter === "processing" && m.active_job) ||
        m.state === filter,
    ) || [];
  return (
    <>
      <PageHeader
        eyebrow="THƯ VIỆN CÁ NHÂN"
        title={trashed ? "Thùng rác" : "Cuộc họp của bạn"}
        description={
          trashed
            ? "Khôi phục cuộc họp đã chuyển vào thùng rác."
            : "Quản lý bản ghi, transcript và tài liệu trong cùng một nơi."
        }
        action={
          !trashed && (
            <Button asChild>
              <Link to="/meetings/new">
                <Plus size={16} />
                Tạo cuộc họp
              </Link>
            </Button>
          )
        }
      />
      <Panel>
        <div className="list-toolbar">
          <form
            className="search-field"
            onSubmit={(e) => {
              e.preventDefault();
              setParams({ q: search, page: "1" });
            }}
          >
            <Search size={17} />
            <input
              aria-label="Lọc cuộc họp"
              placeholder="Tìm theo tên cuộc họp…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Button variant="ghost" type="submit">
              Tìm
            </Button>
          </form>
          <select
            aria-label="Trạng thái cuộc họp"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">Tất cả trạng thái</option>
            <option value="draft">Bản nháp</option>
            <option value="processing">Đang xử lý</option>
            <option value="transcript_ready">Có transcript</option>
            <option value="minutes_ready">Có biên bản</option>
          </select>
        </div>
        <ErrorBox error={data.error} />
        {data.isPending ? (
          <Loading />
        ) : items.length ? (
          <MeetingTable items={items} trashed={trashed} />
        ) : (
          <Empty
            title={trashed ? "Thùng rác trống" : "Chưa tìm thấy cuộc họp"}
            description="Thử thay đổi từ khóa hoặc tạo một cuộc họp mới."
          />
        )}
        <div className="pagination">
          <span>
            {data.data?.total || 0} cuộc họp · Bộ lọc trạng thái áp dụng trên
            trang hiện tại
          </span>
          <div className="row">
            <Button
              variant="outline"
              size="icon"
              aria-label="Trang trước"
              disabled={page === 1}
              onClick={() => setParams({ q: search, page: String(page - 1) })}
            >
              <ChevronLeft size={16} />
            </Button>
            <span>Trang {page}</span>
            <Button
              variant="outline"
              size="icon"
              aria-label="Trang sau"
              disabled={page * 30 >= (data.data?.total || 0)}
              onClick={() => setParams({ q: search, page: String(page + 1) })}
            >
              <ChevronRight size={16} />
            </Button>
          </div>
        </div>
      </Panel>
    </>
  );
}

export function NewMeeting() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0),
    [title, setTitle] = useState(""),
    [date, setDate] = useState(""),
    [location, setLocation] = useState(""),
    [notes, setNotes] = useState(""),
    [files, setFiles] = useState<File[]>([]),
    [people, setPeople] = useState<string[]>([]),
    [template, setTemplate] = useState(""),
    [format, setFormat] = useState(""),
    [mode, setMode] = useState("detailed");
  const { busy, work } = useWork();
  const voices = useQuery({
    queryKey: ["voices"],
    queryFn: () => api<Voice[]>("/speakers"),
  });
  const templates = useQuery({
    queryKey: ["templates"],
    queryFn: () => api<Template[]>("/templates"),
  });
  const caps = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<Capabilities>("/capabilities"),
  });
  async function create(process: boolean) {
    await work(
      async () => {
        let m = await post<Meeting>("/meetings", {
          title,
          date,
          location,
          notes,
          participant_ids: people,
          preferred_template_id: template || null,
          preferred_format:
            format || caps.data?.preset.default_format || "nd30_2020",
          preferred_mode: mode,
        });
        try {
          if (files.length) {
            const form = new FormData();
            files.forEach((f) => form.append("files", f));
            m = await post<Meeting>(
              "/meetings/" + m.id + "/sources?revision=" + m.revision,
              form,
            );
          }
          if (process)
            await post("/meetings/" + m.id + "/process", {
              revision: m.revision,
            });
          navigate("/meetings/" + m.id);
        } catch (error) {
          navigate("/meetings/" + m.id);
          throw error;
        }
      },
      process ? "Đã xếp hàng xử lý âm thanh" : "Đã lưu bản nháp",
    );
  }
  const steps = [
    "Thông tin cuộc họp",
    "Nguồn ghi âm",
    "Người tham gia",
    "Mẫu & xác nhận",
  ];
  return (
    <>
      <PageHeader
        eyebrow="CUỘC HỌP MỚI"
        title="Chuẩn bị một cuộc họp"
        description="Thêm thông tin và nguồn ghi âm. Bạn có thể bổ sung nội dung sau."
      />
      <div className="wizard-layout">
        <ol className="wizard-steps">
          {steps.map((label, i) => (
            <li
              className={i === step ? "current" : i < step ? "complete" : ""}
              key={label}
            >
              <span>
                {i < step ? (
                  <Check size={16} />
                ) : (
                  String(i + 1).padStart(2, "0")
                )}
              </span>
              <div>
                <small>BƯỚC {i + 1}</small>
                <strong>{label}</strong>
              </div>
            </li>
          ))}
        </ol>
        <Panel className="wizard-body">
          <div className="wizard-title">
            <span className="eyebrow">BƯỚC {step + 1} / 4</span>
            <h2>{steps[step]}</h2>
          </div>
          {step === 0 && (
            <div className="form-stack">
              <label>
                Tên cuộc họp <span className="required">*</span>
                <Input
                  autoFocus
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  maxLength={200}
                  placeholder="Ví dụ: Họp triển khai kế hoạch tháng 10"
                />
              </label>
              <div className="form-grid">
                <label>
                  Ngày họp
                  <Input
                    type="date"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                  />
                </label>
                <label>
                  Địa điểm
                  <Input
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                    maxLength={300}
                    placeholder="Phòng họp / Trực tuyến"
                  />
                </label>
              </div>
              <label>
                Ghi chú
                <Textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  maxLength={4000}
                  placeholder="Thông tin bổ sung cho người rà soát…"
                />
              </label>
            </div>
          )}
          {step === 1 && (
            <>
              <label className="upload-zone">
                <UploadCloud size={32} />
                <strong>Chọn bản ghi âm từ thiết bị</strong>
                <span>WAV, MP3, M4A, AAC, FLAC, OGG, WEBM, MP4</span>
                <small>
                  Tối đa {caps.data?.max_sources || 8} nguồn ·{" "}
                  {size(caps.data?.max_upload_bytes || 1e9)}/file
                </small>
                <input
                  type="file"
                  multiple
                  accept=".wav,.mp3,.m4a,.aac,.flac,.ogg,.webm,.mp4"
                  onChange={(e) => setFiles(Array.from(e.target.files || []))}
                />
              </label>
              {files.map((f, i) => (
                <div className="file-row" key={i}>
                  <AudioLines size={18} />
                  <span>
                    {f.name}
                    <small>{size(f.size)}</small>
                  </span>
                  <Button
                    variant="ghost"
                    onClick={() =>
                      setFiles(files.filter((_, index) => index !== i))
                    }
                  >
                    Bỏ
                  </Button>
                </div>
              ))}
              {files.length > 8 && <Notice>Hãy chọn tối đa 8 file.</Notice>}
              <Notice tone="info">
                Các nguồn phải ghi lại cùng một cuộc họp. Hệ thống sẽ đồng bộ và
                dung hợp âm thanh.
              </Notice>
            </>
          )}
          {step === 2 && (
            <>
              <p className="muted">
                Chọn hồ sơ giọng đã có để hỗ trợ nhận diện. Đoạn chưa xác định
                và đoạn nói chồng được hiển thị riêng.
              </p>
              <div className="person-grid">
                {voices.data
                  ?.filter((v) => v.state === "ready")
                  .map((v) => (
                    <label
                      className={
                        "person-choice " +
                        (people.includes(v.id) ? "selected" : "")
                      }
                      key={v.id}
                    >
                      <input
                        type="checkbox"
                        checked={people.includes(v.id)}
                        onChange={(e) =>
                          setPeople(
                            e.target.checked
                              ? [...people, v.id]
                              : people.filter((id) => id !== v.id),
                          )
                        }
                      />
                      <span className="avatar">{v.name[0]}</span>
                      <span>
                        {v.name}
                        <small>{v.samples.length} mẫu giọng</small>
                      </span>
                    </label>
                  ))}
              </div>
              {!voices.data?.some((v) => v.state === "ready") && (
                <Empty
                  title="Chưa có hồ sơ giọng sẵn sàng"
                  description="Bạn có thể tiếp tục. Người nói sẽ được rà soát theo cụm trong transcript."
                  action={
                    <Link className="text-link" to="/voices">
                      Quản lý hồ sơ giọng ↗
                    </Link>
                  }
                />
              )}
            </>
          )}
          {step === 3 && (
            <div className="form-stack">
              <label>
                Mẫu biên bản
                <select
                  value={template}
                  onChange={(e) => setTemplate(e.target.value)}
                >
                  <option value="">Chọn sau khi chép lời</option>
                  {templates.data
                    ?.filter((t) => t.state === "ready" && !t.needs_review)
                    .map((t) => (
                      <option value={t.id} key={t.id}>
                        {t.name}
                      </option>
                    ))}
                </select>
              </label>
              <div className="form-grid">
                <label>
                  Loại biên bản
                  <select
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                  >
                    <option value="detailed">Chi tiết · giữ đề mục mẫu</option>
                    <option value="general">
                      Tổng quát · chia mục theo nội dung
                    </option>
                  </select>
                </label>
                <label>
                  Thể thức đầu ra
                  <select
                    value={
                      format || caps.data?.preset.default_format || "nd30_2020"
                    }
                    onChange={(e) => setFormat(e.target.value)}
                  >
                    <option value="nd30_2020">Hành chính · Nghị định 30</option>
                    <option value="hd05_2026">
                      Tài liệu Đảng · Hướng dẫn 05
                    </option>
                  </select>
                </label>
              </div>
              <div className="summary-box">
                <h3>{title}</h3>
                <p>
                  {date || "Chưa đặt ngày"} · {location || "Chưa có địa điểm"}
                </p>
                <div className="row">
                  <span>
                    <AudioLines size={16} /> {files.length} nguồn ghi âm
                  </span>
                  <span>
                    <Users size={16} /> {people.length} hồ sơ giọng
                  </span>
                </div>
              </div>
              <Notice tone="info">
                Sau khi chép lời, bạn rà soát transcript và chọn “Tạo biên bản”.
                Lựa chọn mẫu và thể thức ở đây được lưu cùng cuộc họp.
              </Notice>
              {!caps.data?.worker.online && (
                <Notice>
                  Worker chưa kết nối. Tác vụ sẽ chờ đến khi worker được khởi
                  động.
                </Notice>
              )}
            </div>
          )}
          <div className="wizard-footer">
            <Button
              variant="ghost"
              disabled={step === 0 || busy}
              onClick={() => setStep(step - 1)}
            >
              <ChevronLeft size={16} />
              Quay lại
            </Button>
            {step < 3 ? (
              <Button
                disabled={
                  !title.trim() || files.length > 8 || people.length > 8
                }
                onClick={() => setStep(step + 1)}
              >
                Tiếp tục
                <ArrowRight size={16} />
              </Button>
            ) : (
              <div className="row">
                <Button
                  variant="outline"
                  disabled={busy || !title.trim()}
                  onClick={() => void create(false)}
                >
                  Lưu bản nháp
                </Button>
                <Button
                  disabled={busy || !files.length || files.length > 8}
                  onClick={() => void create(true)}
                >
                  {busy ? "Đang tải lên…" : "Tải lên & xử lý"}
                  <ArrowUpRight size={16} />
                </Button>
              </div>
            )}
          </div>
        </Panel>
      </div>
    </>
  );
}

export function Settings() {
  const user = useUser();
  const [old, setOld] = useState(""),
    [next, setNext] = useState("");
  const { busy, work } = useWork();
  const caps = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<Capabilities>("/capabilities"),
  });
  return (
    <>
      <PageHeader
        eyebrow="TÀI KHOẢN"
        title="Thiết lập cá nhân"
        description="Thông tin đăng nhập và tình trạng các công cụ đang sử dụng."
      />
      <div className="two-columns">
        <Panel title="Bảo mật tài khoản">
          <div className="account-summary">
            <span className="avatar large">{user.display_name[0]}</span>
            <div>
              <h3>{user.display_name}</h3>
              <p className="muted">
                @{user.username} ·{" "}
                {user.role === "admin" ? "Quản trị viên" : "Người dùng"}
              </p>
            </div>
          </div>
          <form
            className="form-stack"
            onSubmit={(e) => {
              e.preventDefault();
              void work(async () => {
                await post("/users/" + user.id + "/password", {
                  current_password: old,
                  password: next,
                });
                window.location.assign("/");
              }, "Đã đổi mật khẩu, hãy đăng nhập lại");
            }}
          >
            <label>
              Mật khẩu hiện tại
              <Input
                type="password"
                value={old}
                onChange={(e) => setOld(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <label>
              Mật khẩu mới
              <Input
                type="password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                minLength={10}
                maxLength={128}
                autoComplete="new-password"
                required
              />
            </label>
            <Button type="submit" disabled={busy}>
              Đổi mật khẩu
            </Button>
          </form>
        </Panel>
        <Panel title="Khả năng hệ thống">
          <ErrorBox error={caps.error} />
          {caps.data ? (
            <div className="capability-list">
              {[
                ["Worker", caps.data.worker.online],
                ["Đọc Word", caps.data.documents.word],
                ["Đọc PDF văn bản", caps.data.documents.pdf_text],
                ["OCR tiếng Việt", caps.data.documents.ocr],
                ["Xem trước DOCX", caps.data.documents.preview],
              ].map(([name, ready]) => (
                <div key={String(name)}>
                  <span>{String(name)}</span>
                  <Status value={ready ? "ready" : "interrupted"} />
                </div>
              ))}
              <p className="muted small">
                Tối đa {caps.data.max_sources} nguồn âm thanh. Khả năng chạy
                model được kiểm tra riêng trong trang quản trị.
              </p>
            </div>
          ) : (
            <Loading />
          )}
        </Panel>
      </div>
    </>
  );
}
