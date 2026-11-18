import { pageSize } from "@/lib/pagination";
import { moveItem, useDragSort } from "@/lib/drag-sort";
import { useUser } from "@/app";
import {
  Action,
  Empty,
  ErrorBox,
  Loading,
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
import {
  api,
  formatDate,
  formatMeetingDate,
  post,
  size,
  time,
} from "@/lib/api";
import type {
  Capabilities,
  Job,
  Meeting,
  Template,
  Voice,
  TimelineOperation,
} from "@/lib/types";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  Check,
  ChevronLeft,
  FileText,
  FolderOpen,
  GripVertical,
  Plus,
  Search,
  UploadCloud,
  Users,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useUnsavedForm } from "@/lib/unsaved";
import {
  getTimeline,
  updateTimeline,
  uploadTimelineFiles,
} from "@/lib/timeline";

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
                <Link
                  to={"/meetings/" + m.id}
                  className="meeting-name"
                  title={m.title}
                >
                  <span className="file-icon">
                    <AudioLines size={19} />
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <strong
                      style={{
                        display: "-webkit-box",
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: "vertical",
                        overflow: "hidden",
                      }}
                    >
                      {m.title}
                    </strong>
                    <small>
                      {m.location || "Chưa có địa điểm"} ·{" "}
                      {m.source_ids?.length || 0} nguồn
                    </small>
                  </div>
                </Link>
              </td>
              <td>{formatMeetingDate(m.date)}</td>
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
  if (data.isPending) return <Loading />;
  if (data.error) return <ErrorBox error={data.error} />;
  const d = data.data!;
  const continuing = d.recent_meetings
    .filter(
      (m) =>
        m.minutes_stale ||
        m.state !== "minutes_ready" ||
        (m.active_minutes_id && m.reviewed_version !== m.active_minutes_id),
    )
    .slice(0, 3);
  return (
    <>
      <PageHeader
        title="Tổng quan"
        action={
          <Button asChild>
            <Link to="/meetings/new">
              <Plus size={17} />
              Tạo cuộc họp
            </Link>
          </Button>
        }
      />
      <div className="summary-links">
        <Link to="/meetings">
          <FolderOpen size={19} />
          <span>
            Cuộc họp<strong>{d.counts.meetings}</strong>
          </span>
          <ArrowUpRight size={16} />
        </Link>
        <Link to="/meetings?status=needs_review">
          <FileText size={19} />
          <span>
            Cần rà biên bản<strong>{d.counts.needs_review}</strong>
          </span>
          <ArrowUpRight size={16} />
        </Link>
        <Link to="/meetings?status=processing">
          <AudioLines size={19} />
          <span>
            Đang xử lý<strong>{d.counts.processing}</strong>
          </span>
          <ArrowUpRight size={16} />
        </Link>
      </div>
      {!!continuing.length && (
        <section className="continue-section">
          <h2>Tiếp tục công việc</h2>
          <div className="continue-grid">
            {continuing.map((m) => (
              <Link
                className="continue-card"
                key={m.id}
                to={
                  "/meetings/" +
                  m.id +
                  "?tab=" +
                  (m.active_job ||
                  m.state === "draft" ||
                  !m.active_transcript_id
                    ? "sources"
                    : "minutes")
                }
              >
                <Status value={m.active_job ? "running" : m.state} />
                <h3>{m.title}</h3>
                <span>
                  {m.minutes_stale
                    ? "Cập nhật biên bản"
                    : m.active_job
                      ? "Xem tiến độ"
                      : !m.active_transcript_id
                        ? "Chuẩn bị nguồn âm thanh"
                        : "Hoàn thiện biên bản"}
                  <ArrowRight size={16} />
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}
      <Panel title="Cuộc họp gần đây">
        {d.recent_meetings.length ? (
          <MeetingTable items={d.recent_meetings} />
        ) : (
          <Empty
            title="Tạo cuộc họp đầu tiên"
            description="Thêm bản ghi âm để bắt đầu chuẩn bị biên bản."
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
        {!!d.recent_meetings.length && (
          <Link className="panel-link" to="/meetings">
            Xem tất cả cuộc họp
            <ArrowRight size={16} />
          </Link>
        )}
      </Panel>
      {!!d.jobs.length && (
        <details className="activity-details">
          <summary>Tác vụ cần chú ý ({d.jobs.length})</summary>
          {d.jobs.slice(0, 4).map((j) => (
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
              <span>{j.stage}</span>
            </Link>
          ))}
        </details>
      )}
    </>
  );
}

export function Meetings({ trashed = false }: { trashed?: boolean }) {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") || "");
  const limit = pageSize(params.get("limit"));
  const requestedPage = Number(params.get("page") || 1);
  const page =
    Number.isSafeInteger(requestedPage) && requestedPage > 0
      ? requestedPage
      : 1;
  const requestedFilter = params.get("status") || "all";
  const filter = [
    "all",
    "draft",
    "processing",
    "transcript_ready",
    "minutes_ready",
    "needs_review",
  ].includes(requestedFilter)
    ? requestedFilter
    : "all";
  const data = useQuery({
    queryKey: ["meetings", trashed, params.toString()],
    placeholderData: keepPreviousData,
    queryFn: () =>
      api<{ items: Meeting[]; total: number }>(
        "/meetings?trashed=" +
          trashed +
          "&page=" +
          page +
          "&limit=" +
          limit +
          "&q=" +
          encodeURIComponent(params.get("q") || "") +
          "&status=" +
          encodeURIComponent(filter === "all" ? "" : filter),
      ),
    refetchInterval: 5000,
  });
  const items = data.data?.items || [];
  useEffect(() => setSearch(params.get("q") || ""), [params]);
  function pageTo(next: number) {
    setParams({
      q: params.get("q") || "",
      status: filter,
      limit: String(limit),
      page: String(next),
    });
  }
  return (
    <>
      <PageHeader
        eyebrow="THƯ VIỆN CÁ NHÂN"
        title={trashed ? "Thùng rác" : "Cuộc họp của bạn"}
        description={
          trashed ? "Khôi phục cuộc họp đã chuyển vào thùng rác." : undefined
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
              setParams({
                q: search,
                status: filter,
                limit: String(limit),
                page: "1",
              });
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
            onChange={(e) =>
              setParams({
                q: params.get("q") || "",
                limit: String(limit),
                status: e.target.value,
                page: "1",
              })
            }
          >
            <option value="all">Tất cả trạng thái</option>
            <option value="draft">Bản nháp</option>
            <option value="processing">Đang xử lý</option>
            <option value="transcript_ready">Có lời chép</option>
            <option value="needs_review">Cần rà biên bản</option>
            <option value="minutes_ready">Có biên bản</option>
          </select>
        </div>
        <ErrorBox error={data.error} />
        {data.isPending ? (
          <Loading />
        ) : items.length ? (
          <MeetingTable items={items} trashed={trashed} />
        ) : Boolean((params.get("q") || "").trim()) || filter !== "all" ? (
          <Empty
            title="Không có kết quả khớp bộ lọc"
            description="Không tìm thấy cuộc họp nào phù hợp với từ khóa hoặc trạng thái đang chọn."
            action={
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setSearch("");
                  setParams({ q: "", status: "all", page: "1" });
                }}
              >
                Xóa bộ lọc
              </Button>
            }
          />
        ) : trashed ? (
          <Empty
            title="Thùng rác trống"
            description="Các cuộc họp đã xóa mềm sẽ xuất hiện tại đây để bạn có thể khôi phục khi cần."
          />
        ) : (
          <Empty
            title="Chưa có cuộc họp nào"
            description="Tạo cuộc họp đầu tiên và tải lên bản ghi âm để bắt đầu chuẩn bị biên bản."
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
        <Pagination
          page={page}
          limit={limit}
          total={data.data?.total || 0}
          onPageChange={pageTo}
        />
      </Panel>
    </>
  );
}

export function NewMeeting() {
  const navigate = useNavigate();
  const user = useUser();
  const draftKey = "minda:meeting-draft:" + user.id;
  const [draft] = useState(() => {
    try {
      const value = JSON.parse(sessionStorage.getItem(draftKey) || "{}");
      return {
        title: typeof value.title === "string" ? value.title : "",
        date: typeof value.date === "string" ? value.date : "",
        location: typeof value.location === "string" ? value.location : "",
        notes: typeof value.notes === "string" ? value.notes : "",
        template: typeof value.template === "string" ? value.template : "",
        format: typeof value.format === "string" ? value.format : "",
        mode: value.mode === "general" ? "general" : "detailed",
        people: Array.isArray(value.people)
          ? (value.people.filter(
              (id: unknown) => typeof id === "string",
            ) as string[])
          : [],
        fileCount: Number(value.fileCount) || 0,
      };
    } catch {
      return {
        title: "",
        date: "",
        location: "",
        notes: "",
        template: "",
        format: "",
        mode: "detailed",
        people: [] as string[],
        fileCount: 0,
      };
    }
  });
  const [step, setStep] = useState(0),
    [title, setTitle] = useState(draft.title),
    [date, setDate] = useState(draft.date),
    [location, setLocation] = useState(draft.location),
    [notes, setNotes] = useState(draft.notes),
    [files, setFiles] = useState<File[]>([]),
    [people, setPeople] = useState<string[]>(draft.people),
    [template, setTemplate] = useState(draft.template),
    [format, setFormat] = useState(draft.format),
    [mode, setMode] = useState(draft.mode);
  const [fileLayout, setFileLayout] = useState("devices");
  const dirty = !!(
    title ||
    date ||
    location ||
    notes ||
    files.length ||
    people.length ||
    template ||
    format
  );
  const guard = useUnsavedForm(dirty);
  useEffect(() => {
    try {
      if (dirty)
        sessionStorage.setItem(
          draftKey,
          JSON.stringify({
            title,
            date,
            location,
            notes,
            template,
            format,
            mode,
            people,
            fileCount: files.length,
          }),
        );
      else sessionStorage.removeItem(draftKey);
    } catch {
      /* Draft recovery is optional. */
    }
  }, [
    draftKey,
    title,
    date,
    location,
    notes,
    template,
    format,
    mode,
    people,
    files,
    dirty,
  ]);
  const [direction, setDirection] = useState<"forward" | "backward">("forward");
  const stepHeading = useRef<HTMLHeadingElement>(null);
  const previousStep = useRef(step);
  useEffect(() => {
    if (previousStep.current !== step) {
      stepHeading.current?.focus({ preventScroll: true });
      previousStep.current = step;
    }
  }, [step]);
  function goToStep(next: number) {
    setDirection(next > step ? "forward" : "backward");
    setStep(next);
  }
  const { busy, work } = useWork();
  const fileKey = (file: File, index: number) =>
    `${file.name}:${file.size}:${file.lastModified}:${index}`;
  const fileSortScope = "new-meeting-files";
  const fileSort = useDragSort(fileSortScope, busy, (item, destination) => {
    const from = files.findIndex(
      (file, index) => fileKey(file, index) === item.id,
    );
    const to = files.findIndex(
      (file, index) =>
        fileKey(file, index) === destination.target.dataset.sortItem,
    );
    setFiles((current) => moveItem(current, from, to, destination.after));
  });
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
  const fileLimit =
    fileLayout === "parts"
      ? caps.data?.max_source_files || 128
      : caps.data?.max_sources || 8;
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
        guard.allowNavigation();
        try {
          sessionStorage.removeItem(draftKey);
        } catch {
          /* Server draft is authoritative. */
        }
        try {
          if (files.length) {
            m = await uploadTimelineFiles(m.id, m.revision, files);
            const view = await getTimeline(m.id);
            const operations: TimelineOperation[] = [];
            if (fileLayout === "parts") {
              const track = "source-" + crypto.randomUUID();
              operations.push({
                op: "create_track",
                id: track,
                name: "Nguồn ghi 1",
              });
              m.source_ids
                .filter((asset) =>
                  view.timeline.unassigned_asset_ids.includes(asset),
                )
                .forEach((asset) =>
                  operations.push({
                    op: "add_clip",
                    id: "part-" + crypto.randomUUID(),
                    track_id: track,
                    asset_id: asset,
                  }),
                );
            } else
              m.source_ids
                .filter((asset) =>
                  view.timeline.unassigned_asset_ids.includes(asset),
                )
                .forEach((asset, index) => {
                  const track = "source-" + crypto.randomUUID();
                  operations.push(
                    {
                      op: "create_track",
                      id: track,
                      name: "Nguồn ghi " + (index + 1),
                    },
                    {
                      op: "add_clip",
                      id: "part-" + crypto.randomUUID(),
                      track_id: track,
                      asset_id: asset,
                    },
                  );
                });
            for (let start = 0; start < operations.length; start += 200) {
              const saved = await updateTimeline(
                m.id,
                m.revision,
                operations.slice(start, start + 200),
              );
              m = { ...m, revision: saved.revision };
            }
          }
          if (process)
            await post("/meetings/" + m.id + "/process", {
              revision: m.revision,
            });
          navigate("/meetings/" + m.id + "?tab=sources");
        } catch (error) {
          navigate("/meetings/" + m.id + "?tab=sources");
          throw error;
        }
      },
      process ? "Đã xếp hàng xử lý âm thanh" : "Đã lưu bản nháp",
    );
  }
  const steps = [
    "Thông tin cuộc họp",
    "Nguồn âm thanh",
    "Người tham gia",
    "Mẫu & xác nhận",
  ];
  return (
    <>
      {fileSort.overlay}
      <PageHeader title="Tạo cuộc họp" />
      {draft.title && (
        <Notice tone="info">
          Đã khôi phục bản nháp trong phiên này.
          {draft.fileCount > 0
            ? " Hãy chọn lại file âm thanh trước khi tải lên."
            : ""}
        </Notice>
      )}
      {guard.dialog}
      <div className="wizard-layout">
        <ol className="wizard-steps">
          {steps.map((label, i) => (
            <li
              className={i === step ? "current" : i < step ? "complete" : ""}
              key={label}
            >
              <span>
                {i < step ? (
                  <Check className="confirmation-check" size={16} />
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
          <div
            key={step}
            className="wizard-step-motion"
            data-direction={direction}
          >
            <div className="wizard-title">
              <span className="eyebrow">BƯỚC {step + 1} / 4</span>
              <h2 ref={stepHeading} tabIndex={-1}>
                {steps[step]}
              </h2>
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
                    Tối đa {fileLimit} file ·{" "}
                    {time(caps.data?.max_audio_duration_sec || 7200)} mỗi file ·{" "}
                    {size(caps.data?.max_upload_bytes || 1e9)}/file
                  </small>
                  <input
                    type="file"
                    multiple
                    accept=".wav,.mp3,.m4a,.aac,.flac,.ogg,.webm,.mp4"
                    onChange={(e) => setFiles(Array.from(e.target.files || []))}
                  />
                </label>
                {files.length > 1 && (
                  <p className="context-hint">
                    Kéo tay nắm để đổi thứ tự file, hoặc dùng nút Lên / Xuống.
                  </p>
                )}
                <div data-sort-list="file" data-sort-scope={fileSortScope}>
                  {files.map((f, i) => (
                    <div
                      className="file-row"
                      key={fileKey(f, i)}
                      data-sort-scope={fileSortScope}
                      data-sort-file
                      data-sort-item={fileKey(f, i)}
                      data-sort-axis="y"
                      onPointerDown={(event) =>
                        fileSort.start(event, {
                          kind: "file",
                          id: fileKey(f, i),
                          label: f.name,
                        })
                      }
                    >
                      <button
                        type="button"
                        className="drag-handle"
                        data-drag-handle
                        disabled={busy}
                        aria-label={"Kéo " + f.name + " để đổi thứ tự"}
                        onPointerDown={(event) =>
                          fileSort.start(event, {
                            kind: "file",
                            id: fileKey(f, i),
                            label: f.name,
                          })
                        }
                      >
                        <GripVertical size={16} />
                      </button>
                      <AudioLines size={18} />
                      <span>
                        {f.name}
                        <small>{size(f.size)}</small>
                      </span>
                      <div className="row" style={{ gap: 4 }}>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          disabled={i === 0}
                          aria-label={`Đưa ${f.name} lên trước`}
                          onClick={() => {
                            const next = [...files];
                            [next[i - 1], next[i]] = [next[i], next[i - 1]];
                            setFiles(next);
                          }}
                        >
                          Lên
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          disabled={i === files.length - 1}
                          aria-label={`Đưa ${f.name} xuống sau`}
                          onClick={() => {
                            const next = [...files];
                            [next[i], next[i + 1]] = [next[i + 1], next[i]];
                            setFiles(next);
                          }}
                        >
                          Xuống
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            setFiles(files.filter((_, index) => index !== i))
                          }
                        >
                          Bỏ
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
                {files.length > fileLimit && (
                  <Notice>
                    Hãy chọn tối đa {fileLimit} file cho cách xếp này.
                  </Notice>
                )}
                <label className="form-stack">
                  Các file thuộc nguồn nào?
                  <select
                    value={fileLayout}
                    onChange={(e) => setFileLayout(e.target.value)}
                  >
                    <option value="devices">
                      Mỗi file từ một nguồn ghi khác nhau
                    </option>
                    <option value="parts">
                      Các phần nối tiếp của cùng một nguồn
                    </option>
                  </select>
                </label>
                <Notice tone="info">
                  Bạn có thể đổi nguồn và thứ tự sau khi tải lên. Khoảng nghỉ
                  giữa các phần chưa biết sẽ được giữ là chưa xác định.
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
                    description="Bạn có thể đặt tên người nói sau khi có lời chép."
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
                      <option value="detailed">
                        Chi tiết · giữ đề mục mẫu
                      </option>
                      <option value="general">
                        Tổng quát · chia mục theo nội dung
                      </option>
                    </select>
                  </label>
                  <label>
                    Thể thức đầu ra
                    <select
                      value={
                        format ||
                        caps.data?.preset.default_format ||
                        "nd30_2020"
                      }
                      onChange={(e) => setFormat(e.target.value)}
                    >
                      <option value="nd30_2020">
                        Hành chính · Nghị định 30
                      </option>
                      <option value="hd05_2026">
                        Tài liệu Đảng · Hướng dẫn 05
                      </option>
                    </select>
                  </label>
                </div>
                <div className="summary-box">
                  <h3>{title}</h3>
                  <p>
                    {formatMeetingDate(date)} · {location || "Chưa có địa điểm"}
                  </p>
                  <div className="row">
                    <span>
                      <AudioLines size={16} /> {files.length} file âm thanh
                    </span>
                    <span>
                      <Users size={16} /> {people.length} hồ sơ giọng
                    </span>
                  </div>
                </div>
                <Notice tone="info">
                  Sau khi chép lời, bạn rà lời chép và chọn “Tạo biên bản”. Lựa
                  chọn mẫu và thể thức ở đây được lưu cùng cuộc họp.
                </Notice>
                {!caps.data?.worker.online && (
                  <Notice>
                    Hệ thống chưa sẵn sàng xử lý. Bạn vẫn có thể lưu cuộc họp;
                    tác vụ sẽ chờ đến khi hệ thống sẵn sàng.
                  </Notice>
                )}
              </div>
            )}
          </div>
          <div className="wizard-footer">
            <Button
              variant="ghost"
              disabled={step === 0 || busy}
              onClick={() => goToStep(step - 1)}
            >
              <ChevronLeft size={16} />
              Quay lại
            </Button>
            {step < 3 ? (
              <Button
                disabled={
                  !title.trim() || files.length > fileLimit || people.length > 8
                }
                onClick={() => goToStep(step + 1)}
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
                  disabled={busy || !files.length || files.length > fileLimit}
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
          <p className="muted">Minda · Không gian làm việc cục bộ</p>
          <ErrorBox error={caps.error} />
          {caps.data ? (
            <div className="capability-list">
              {[
                ["Xử lý âm thanh", caps.data.worker.online],
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
                Tối đa {caps.data.max_sources} nguồn âm thanh. Cấu hình model &
                preset AI hiện hành ({caps.data.preset.asr_variant} /{" "}
                {caps.data.preset.default_format}) do quản trị viên thiết lập
                {user.role === "admin" ? (
                  <>
                    {" "}
                    tại{" "}
                    <Link to="/admin/models" className="green-text">
                      Model & preset
                    </Link>
                    .
                  </>
                ) : (
                  "."
                )}
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
