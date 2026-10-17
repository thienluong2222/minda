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
import { api, formatDate, patch, post, size, time } from "@/lib/api";
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
  Play,
  Plus,
  RefreshCw,
  Trash2,
  Users,
} from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { MinutesView } from "./minutes";
import { TranscriptView } from "./transcript";

function JobProgress({ jobId }: { jobId: string }) {
  const data = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api<Job>("/jobs/" + jobId),
    refetchInterval: 2000,
  });
  const j = data.data;
  return (
    <div className="job-progress">
      <span className="pulse-icon">
        <AudioLines size={20} />
      </span>
      <div>
        <strong>{j?.stage || "Đang tải trạng thái tác vụ…"}</strong>
        <small>
          {j?.state === "queued"
            ? "Tác vụ sẽ chạy khi worker sẵn sàng."
            : "Tiến độ được cập nhật theo công đoạn xử lý."}
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
                ? "Phiên bản transcript"
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
                        <DownloadLink artifact={v.docx} label="Tải DOCX" />
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
        title="Đối chiếu phiên bản transcript"
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
    [files, setFiles] = useState<File[]>([]),
    [confirmTrash, setConfirmTrash] = useState(false);
  const { busy, work } = useWork();
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
      <div className="two-columns">
        <Panel title="Thông tin cuộc họp">
          <div className="detail-list">
            <div>
              <span>Ngày họp</span>
              <strong>{meeting.date || "Chưa đặt"}</strong>
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
        <Panel
          title="Nguồn ghi âm"
          description={`${meeting.source_ids.length}/8 nguồn được chọn để xử lý.`}
        >
          {meeting.sources?.map((s) => (
            <div className="source-card" key={s.id}>
              <div className="row between">
                <strong>
                  <AudioLines size={17} />
                  {s.name}
                </strong>
                <Action
                  variant="ghost"
                  disabled={disabled}
                  run={() =>
                    api("/meetings/" + meeting.id + "/sources/" + s.id, {
                      method: "DELETE",
                      body: JSON.stringify({ revision: meeting.revision }),
                    })
                  }
                  message="Đã bỏ nguồn khỏi lần xử lý tiếp theo"
                >
                  <Trash2 size={15} />
                </Action>
              </div>
              <audio controls preload="none" src={s.artifact.url} />
              <div className="row between">
                <small className="muted">
                  {size(s.artifact.size_bytes)}
                  {s.duration_sec ? " · " + time(s.duration_sec) : ""}
                  {s.sample_rate ? " · " + s.sample_rate + " Hz" : ""}
                </small>
                <DownloadLink artifact={s.artifact} label="Tải nguồn" />
              </div>
            </div>
          ))}
          {!meeting.source_ids.length && (
            <Empty
              title="Chưa có bản ghi âm"
              description="Thêm các file ghi lại cùng một cuộc họp để bắt đầu."
            />
          )}
          <label className="compact-upload">
            <Plus size={17} />
            <span>Thêm nguồn âm thanh</span>
            <input
              disabled={disabled || meeting.source_ids.length >= 8}
              type="file"
              multiple
              accept=".wav,.mp3,.m4a,.aac,.flac,.ogg,.webm,.mp4"
              onChange={(e) => setFiles(Array.from(e.target.files || []))}
            />
          </label>
          {files.length > 0 && (
            <div className="upload-pending">
              <p>{files.map((f) => f.name).join(", ")}</p>
              <Button
                disabled={busy || files.length + meeting.source_ids.length > 8}
                onClick={() =>
                  void work(async () => {
                    const form = new FormData();
                    files.forEach((f) => form.append("files", f));
                    await post(
                      "/meetings/" +
                        meeting.id +
                        "/sources?revision=" +
                        meeting.revision,
                      form,
                    );
                    setFiles([]);
                  }, "Đã tải nguồn âm thanh")
                }
              >
                Tải lên {files.length} file
              </Button>
            </div>
          )}
          <Action
            variant="default"
            disabled={disabled || !meeting.source_ids.length}
            run={() =>
              post("/meetings/" + meeting.id + "/process", {
                revision: meeting.revision,
              })
            }
            message="Đã xếp hàng xử lý âm thanh"
          >
            {meeting.active_transcript_id ? (
              <RefreshCw size={16} />
            ) : (
              <Play size={16} />
            )}{" "}
            {meeting.active_transcript_id
              ? "Xử lý lại âm thanh"
              : "Bắt đầu xử lý"}
          </Action>
        </Panel>
      </div>
      {meeting.transcript_exports?.length ? (
        <Panel title="File đối chiếu transcript">
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
      <Modal open={edit} onOpenChange={setEdit} title="Thông tin cuộc họp" wide>
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
  const tab = params.get("tab") || "overview";
  const data = useQuery({
    queryKey: ["meeting", id],
    queryFn: () => api<Meeting>("/meetings/" + id),
    refetchInterval: 2000,
  });
  if (data.isPending) return <Loading />;
  if (data.error) return <ErrorBox error={data.error} />;
  const meeting = data.data!;
  return (
    <>
      <Link to="/meetings" className="breadcrumb">
        <ArrowLeft size={14} />
        Cuộc họp của bạn
      </Link>
      <PageHeader
        eyebrow="KHÔNG GIAN CUỘC HỌP"
        title={meeting.title}
        description={`${meeting.date || "Chưa đặt ngày"} · ${meeting.location || "Chưa có địa điểm"}`}
        action={
          <Status value={meeting.active_job ? "running" : meeting.state} />
        }
      />
      {meeting.trashed && (
        <Notice>
          Cuộc họp đang ở thùng rác. Hãy khôi phục để tiếp tục chỉnh sửa.
        </Notice>
      )}
      {meeting.active_job && <JobProgress jobId={meeting.active_job} />}
      <nav className="workspace-tabs">
        {[
          ["overview", "Tổng quan", CalendarDays],
          ["transcript", "Transcript", AudioLines],
          ["speakers", "Người nói", Users],
          ["minutes", "Biên bản", FileText],
          ["history", "Lịch sử", History],
        ].map(([key, label, Icon]) => {
          const TabIcon = Icon as typeof CalendarDays;
          return (
            <button
              className={tab === key ? "active" : ""}
              key={String(key)}
              onClick={() => setParams({ tab: String(key) })}
            >
              <TabIcon size={17} />
              {String(label)}
            </button>
          );
        })}
      </nav>
      {tab === "overview" ? (
        <Overview meeting={meeting} />
      ) : tab === "transcript" ? (
        <TranscriptView meeting={meeting} />
      ) : tab === "speakers" ? (
        <TranscriptView meeting={meeting} people />
      ) : tab === "minutes" ? (
        <MinutesView meeting={meeting} />
      ) : (
        <HistoryView meeting={meeting} />
      )}
    </>
  );
}
