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
  Preview,
  Status,
  useWork,
} from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiError,
  api,
  formatDate,
  formatMeetingDate,
  jobErrorMessage,
  labels,
  patch,
  post,
  time,
} from "@/lib/api";
import { NotFoundState } from "@/features/auth/pages";
import type {
  Audit,
  Job,
  Meeting,
  MinutesVersion,
  Transcript,
  Version,
  Voice,
} from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  AudioLines,
  CalendarDays,
  FileText,
  History,
  Network,
  Trash2,
} from "lucide-react";
import { lazy, Suspense, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { MinutesView } from "./minutes";
import { TranscriptView } from "./transcript";
import { SourcesTimeline } from "./sources";
import { ReviewAudioProvider } from "@/components/review-audio";
import { useUnsavedForm } from "@/lib/unsaved";

const MeetingGraphView = lazy(() => import("./graph"));

function JobProgress({
  jobId,
  meetingId,
}: {
  jobId: string;
  meetingId: string;
}) {
  const data = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api<Job>("/jobs/" + jobId),
    refetchInterval: (query) =>
      !query.state.data ||
      ["queued", "running"].includes(query.state.data.state)
        ? 2000
        : false,
  });
  const j = data.data;
  if (data.error) return <ErrorBox error={data.error} />;
  if (j && (j.resource_type !== "meeting" || j.resource_id !== meetingId))
    return null;
  const finished = !!j && !["queued", "running"].includes(j.state);
  if (finished)
    return (
      <Notice tone={j.state === "succeeded" ? "success" : "warning"}>
        <strong>
          {labels[j.kind] || j.kind} · {labels[j.state] || j.state}
        </strong>
        <p>{formatDate(j.created_at)} · Lần xử lý này đã kết thúc.</p>
        {j.error && <p>{jobErrorMessage(j.error)}</p>}
      </Notice>
    );
  return (
    <div className="job-progress">
      <span className="pulse-icon">
        <AudioLines size={20} />
      </span>
      <div>
        <strong>{j?.stage || "Đang tải trạng thái tác vụ…"}</strong>
        <small>
          {j?.state === "queued"
            ? "Đang chờ xử lý"
            : "Bạn có thể tiếp tục xem nội dung đã lưu."}
        </small>
      </div>
      <Action
        disabled={!j || j.cancel_requested}
        run={() => post("/jobs/" + jobId + "/cancel")}
        message="Đã gửi yêu cầu hủy"
      >
        {j?.cancel_requested ? "Đang chờ dừng" : "Hủy tác vụ"}
      </Action>
    </div>
  );
}

function HistoryView({ meeting }: { meeting: Meeting }) {
  const data = useQuery({
    queryKey: ["history", meeting.id, meeting.revision],
    queryFn: () =>
      api<{ transcripts: Version[]; minutes: Version[]; events: Audit[] }>(
        "/meetings/" + meeting.id + "/history",
      ),
  });
  const [inspect, setInspect] = useState<{
    previous: Transcript;
    current: Transcript;
  } | null>(null);
  const [oldMinutes, setOldMinutes] = useState<MinutesVersion | null>(null);
  const { work } = useWork();
  if (data.isPending) return <Loading />;
  return (
    <>
      <ErrorBox error={data.error} />
      <div className="two-columns">
        {(["transcripts", "minutes"] as const).map((type) => (
          <Panel
            title={
              type === "transcripts"
                ? "Phiên bản lời chép"
                : "Phiên bản biên bản"
            }
            key={type}
          >
            {data.data?.[type].length ? (
              data.data[type].map((v) => (
                <div className="version-row" key={v.id}>
                  <div>
                    <strong>{v.reason}</strong>
                    <p>{formatDate(v.created_at)}</p>
                    <small>
                      {v.id.slice(0, 8)}
                      {(type === "transcripts"
                        ? meeting.active_transcript_id
                        : meeting.active_minutes_id) === v.id
                        ? " · Đang sử dụng"
                        : ""}
                    </small>
                  </div>
                  <div className="column-actions">
                    {type === "minutes" && v.docx ? (
                      <>
                        <DownloadLink artifact={v.docx} label="Tải Word" />
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            void work(async () => {
                              setOldMinutes(
                                (
                                  await api<{ version: MinutesVersion }>(
                                    "/meetings/" +
                                      meeting.id +
                                      "/minutes?version_id=" +
                                      v.id,
                                  )
                                ).version,
                              );
                            }, "")
                          }
                        >
                          Xem bản đã lưu
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          void work(async () => {
                            const [previous, current] = await Promise.all([
                              api<Transcript>(
                                "/meetings/" +
                                  meeting.id +
                                  "/transcript?version_id=" +
                                  v.id,
                              ),
                              api<Transcript>(
                                "/meetings/" + meeting.id + "/transcript",
                              ),
                            ]);
                            setInspect({ previous, current });
                          }, "")
                        }
                      >
                        Đối chiếu nội dung
                      </Button>
                    )}
                    <Action
                      disabled={!!meeting.active_job || meeting.trashed}
                      run={() =>
                        post(
                          "/meetings/" +
                            meeting.id +
                            (type === "transcripts"
                              ? "/transcript/restore"
                              : "/minutes/restore"),
                          { revision: meeting.revision, version_id: v.id },
                        )
                      }
                      message="Đã yêu cầu khôi phục thành phiên bản mới"
                    >
                      <History size={14} />
                      Khôi phục
                    </Action>
                  </div>
                </div>
              ))
            ) : (
              <Empty title="Chưa có phiên bản" />
            )}
          </Panel>
        ))}
      </div>
      <Panel title="Nhật ký cuộc họp">
        <table className="data-table">
          <thead>
            <tr>
              <th>Thời gian</th>
              <th>Thao tác</th>
              <th>Chi tiết</th>
            </tr>
          </thead>
          <tbody>
            {data.data?.events.map((e) => (
              <tr key={e.id}>
                <td>{formatDate(e.created_at)}</td>
                <td>{e.action}</td>
                <td>
                  <JsonDetails value={e.details} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Modal
        wide
        open={!!inspect}
        onOpenChange={(v) => !v && setInspect(null)}
        title="Đối chiếu phiên bản lời chép"
        description="Bên trái là phiên bản đã chọn, bên phải là nội dung đang sử dụng. Đoạn có thay đổi được đánh dấu."
      >
        <div className="version-comparison">
          {inspect?.previous.segments.map((row) => {
            const current = inspect.current.segments.find(
              (s) => s.turn_id === row.turn_id,
            );
            const changed =
              current?.text !== row.text ||
              current?.speaker_label !== row.speaker_label;
            return (
              <div
                key={row.id}
                className={
                  changed ? "comparison-row changed" : "comparison-row"
                }
              >
                <div>
                  <small>
                    {time(row.start_sec)} · {row.speaker_label}
                  </small>
                  <p>{row.text || "Chưa có lời chép"}</p>
                </div>
                <div>
                  <small>
                    {current?.speaker_label || "Không có trong bản hiện tại"}
                    {changed ? " · Có thay đổi" : ""}
                  </small>
                  <p>{current?.text || "Chưa có lời chép"}</p>
                </div>
              </div>
            );
          })}
        </div>
      </Modal>
      <Modal
        wide
        open={!!oldMinutes}
        onOpenChange={(value) => !value && setOldMinutes(null)}
        title="Biên bản phiên bản đã lưu"
        description={oldMinutes ? formatDate(oldMinutes.created_at) : ""}
      >
        {oldMinutes && (
          <Preview pages={oldMinutes.previews} download={oldMinutes.docx} />
        )}
      </Modal>
    </>
  );
}

function Overview({ meeting }: { meeting: Meeting }) {
  const [edit, setEdit] = useState(false),
    [title, setTitle] = useState(meeting.title),
    [date, setDate] = useState(meeting.date),
    [location, setLocation] = useState(meeting.location),
    [notes, setNotes] = useState(meeting.notes),
    [people, setPeople] = useState(meeting.participant_ids),
    [confirmTrash, setConfirmTrash] = useState(false);
  const { busy, work } = useWork();
  const guard = useUnsavedForm(
    edit &&
      (title !== meeting.title ||
        date !== meeting.date ||
        location !== meeting.location ||
        notes !== meeting.notes ||
        JSON.stringify(people) !== JSON.stringify(meeting.participant_ids)),
  );
  const voices = useQuery({
    queryKey: ["voices"],
    queryFn: () => api<Voice[]>("/speakers"),
  });
  const jobs = useQuery({
    queryKey: ["meeting-jobs", meeting.id, meeting.revision],
    queryFn: () => api<Job[]>("/jobs"),
    refetchInterval: 5000,
  });
  const failed = jobs.data?.find(
    (j) =>
      j.resource_id === meeting.id &&
      ["failed", "interrupted", "cancelled"].includes(j.state),
  );
  const disabled = !!meeting.active_job || meeting.trashed;
  return (
    <>
      {failed && !meeting.active_job && (
        <Notice>
          Thao tác gần nhất cần kiểm tra:{" "}
          {failed.error?.message || failed.stage}.{" "}
          <Action
            run={() => post("/jobs/" + failed.id + "/retry")}
            message="Đã xếp hàng thử lại"
          >
            Thử lại tác vụ
          </Action>
        </Notice>
      )}
      <div className="overview-info">
        <Panel title="Thông tin cuộc họp">
          <div className="detail-list">
            <div>
              <span>Ngày họp</span>
              <strong>{formatMeetingDate(meeting.date)}</strong>
            </div>
            <div>
              <span>Địa điểm</span>
              <strong>{meeting.location || "Chưa bổ sung"}</strong>
            </div>
            <div>
              <span>Người tham gia đã chọn</span>
              <strong>
                {meeting.participant_ids
                  .map(
                    (id) =>
                      voices.data?.find((v) => v.id === id)?.name ||
                      id.slice(0, 8),
                  )
                  .join(", ") || "Chưa chọn hồ sơ giọng"}
              </strong>
            </div>
            <div>
              <span>Ghi chú</span>
              <p>{meeting.notes || "Không có ghi chú"}</p>
            </div>
          </div>
          <Button
            variant="outline"
            disabled={disabled}
            onClick={() => {
              setTitle(meeting.title);
              setDate(meeting.date);
              setLocation(meeting.location);
              setNotes(meeting.notes);
              setPeople(meeting.participant_ids);
              setEdit(true);
            }}
          >
            Chỉnh sửa thông tin
          </Button>
        </Panel>
      </div>
      {meeting.transcript_exports?.length ? (
        <Panel title="Tải lời chép">
          <div className="row wrap">
            {meeting.transcript_exports.map((a) => (
              <DownloadLink key={a.id} artifact={a} label={a.name} />
            ))}
          </div>
        </Panel>
      ) : null}
      <Panel title="Quản lý cuộc họp">
        {meeting.trashed ? (
          <Action
            run={() =>
              post("/meetings/" + meeting.id + "/restore", {
                revision: meeting.revision,
              })
            }
          >
            Khôi phục cuộc họp
          </Action>
        ) : (
          <Button
            variant="outline"
            disabled={disabled}
            onClick={() => setConfirmTrash(true)}
          >
            <Trash2 size={16} />
            Chuyển vào thùng rác
          </Button>
        )}
      </Panel>
      {guard.dialog}
      <Modal
        open={confirmTrash}
        onOpenChange={setConfirmTrash}
        title="Chuyển cuộc họp vào thùng rác"
        description="Bạn có thể khôi phục sau trong Thùng rác. Các phiên bản và tài liệu được giữ lại."
      >
        <Action
          variant="destructive"
          run={async () => {
            await post("/meetings/" + meeting.id + "/trash", {
              revision: meeting.revision,
            });
            setConfirmTrash(false);
          }}
          message="Đã chuyển vào thùng rác"
        >
          Chuyển vào thùng rác
        </Action>
      </Modal>
      <Modal
        open={edit}
        onOpenChange={(open) =>
          open ? setEdit(true) : guard.requestClose(() => setEdit(false))
        }
        title="Thông tin cuộc họp"
        wide
      >
        <div className="form-stack">
          <label>
            Tên cuộc họp
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={200}
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
              />
            </label>
          </div>
          <label>
            Ghi chú
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              maxLength={4000}
            />
          </label>
          <fieldset>
            <legend>Hồ sơ giọng tham gia</legend>
            {voices.data
              ?.filter((v) => v.state === "ready")
              .map((v) => (
                <label key={v.id} className="check-label">
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
                  {v.name}
                </label>
              ))}
          </fieldset>
          {meeting.active_transcript_id &&
            JSON.stringify(people) !==
              JSON.stringify(meeting.participant_ids) && (
              <Notice tone="warning">
                Thay đổi danh sách hồ sơ giọng tham gia sẽ chuyển cuộc họp về
                trạng thái cần xử lý lại âm thanh trước khi tạo biên bản mới.
              </Notice>
            )}
          <Button
            disabled={busy || !title.trim() || people.length > 8}
            onClick={() =>
              void work(async () => {
                await patch("/meetings/" + meeting.id, {
                  revision: meeting.revision,
                  title,
                  date,
                  location,
                  notes,
                  participant_ids: people,
                });
                setEdit(false);
              }, "Đã lưu thông tin cuộc họp")
            }
          >
            Lưu thông tin
          </Button>
        </div>
      </Modal>
    </>
  );
}

export function Workspace() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "sources";
  const data = useQuery({
    queryKey: ["meeting", id],
    queryFn: () => api<Meeting>("/meetings/" + id),
    refetchInterval: 2000,
  });
  if (data.isPending) return <Loading />;
  if (data.error) {
    if (data.error instanceof ApiError && data.error.status === 404) {
      return (
        <NotFoundState
          title="Không tìm thấy cuộc họp"
          description="Cuộc họp không tồn tại, đã xóa hoặc không thuộc quyền sở hữu của bạn."
          backTo="/meetings"
          backLabel="Về danh sách cuộc họp"
        />
      );
    }
    return <ErrorBox error={data.error} onRetry={() => void data.refetch()} />;
  }
  const meeting = data.data!;
  const tabs = [
    ["sources", "Nguồn âm thanh", AudioLines],
    ["transcript", "Lời chép", FileText],
    ["minutes", "Biên bản", FileText],
    ["graph", "Đồ thị cuộc họp", Network],
    ["history", "Lịch sử", History],
  ] as const;
  function buildTabQuery(nextTab: string) {
    const next = new URLSearchParams(params);
    next.set("tab", nextTab);
    return "?" + next.toString();
  }
  return (
    <ReviewAudioProvider key={meeting.id}>
      <div className="workspace-breadcrumb">
        <Link to="/meetings" className="breadcrumb">
          <ArrowLeft size={15} />
          Cuộc họp
        </Link>
        <Button
          variant="ghost"
          onClick={() => {
            const next = new URLSearchParams(params);
            next.set("tab", "overview");
            setParams(next);
          }}
        >
          <CalendarDays size={16} />
          Thông tin cuộc họp
        </Button>
      </div>
      <PageHeader
        title={meeting.title}
        description={[
          meeting.date ? formatMeetingDate(meeting.date) : "",
          meeting.location,
        ]
          .filter(Boolean)
          .join(" · ")}
        action={
          <Status value={meeting.active_job ? "running" : meeting.state} />
        }
      />
      {meeting.trashed && (
        <Notice>
          Cuộc họp đang ở thùng rác. Khôi phục tại phần thông tin để tiếp tục.
        </Notice>
      )}
      {meeting.active_job && (
        <JobProgress jobId={meeting.active_job} meetingId={meeting.id} />
      )}
      {params.get("job") && params.get("job") !== meeting.active_job && (
        <JobProgress jobId={params.get("job")!} meetingId={meeting.id} />
      )}
      <nav className="workspace-tabs" aria-label="Các phần của cuộc họp">
        {tabs.map(([key, label, Icon]) => (
          <Link
            key={key}
            to={buildTabQuery(key)}
            className={
              tab === key || (key === "transcript" && tab === "speakers")
                ? "active"
                : ""
            }
            aria-current={
              tab === key || (key === "transcript" && tab === "speakers")
                ? "page"
                : undefined
            }
          >
            <Icon size={17} aria-hidden="true" />
            {label}
          </Link>
        ))}
      </nav>
      <div key={tab} className="tab-motion workspace-body">
        {tab === "overview" ? (
          <Overview meeting={meeting} />
        ) : tab === "transcript" || tab === "speakers" ? (
          <TranscriptView meeting={meeting} people={tab === "speakers"} />
        ) : tab === "minutes" ? (
          <MinutesView meeting={meeting} />
        ) : tab === "graph" ? (
          <Suspense fallback={<Loading />}>
            <MeetingGraphView
              key={meeting.active_minutes_id || "empty"}
              meeting={meeting}
            />
          </Suspense>
        ) : tab === "history" ? (
          <HistoryView meeting={meeting} />
        ) : (
          <SourcesTimeline meeting={meeting} />
        )}
      </div>
    </ReviewAudioProvider>
  );
}
