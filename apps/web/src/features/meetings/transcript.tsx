import {
  Empty,
  ErrorBox,
  Loading,
  Modal,
  Notice,
  Panel,
  useWork,
} from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, patch, post, time } from "@/lib/api";
import type { Meeting, Segment, Transcript } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import {
  Check,
  Edit3,
  Search,
  Headphones,
  ChevronLeft,
  ChevronRight,
  Users,
  FileText,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useReviewAudio, useStopReviewAudio } from "@/components/review-audio";
import { useUnsavedForm } from "@/lib/unsaved";

function segmentTime(row: Segment, seconds: number) {
  if (row.end_sec - row.start_sec >= 1) return time(seconds);
  const milliseconds = Math.round(Math.max(0, seconds) * 1000);
  return `${time(milliseconds / 1000)}.${String(milliseconds % 1000).padStart(3, "0")}`;
}

export function TranscriptView({
  meeting,
  people = false,
}: {
  meeting: Meeting;
  people?: boolean;
}) {
  const [searchParams] = useSearchParams();
  const data = useQuery({
    queryKey: ["transcript", meeting.id, meeting.active_transcript_id],
    queryFn: () => api<Transcript>("/meetings/" + meeting.id + "/transcript"),
  });
  const [search, setSearch] = useState(searchParams.get("q") || ""),
    [speaker, setSpeaker] = useState(searchParams.get("speaker") || ""),
    [review, setReview] = useState(searchParams.get("filter") === "review"),
    [editing, setEditing] = useState<Segment | null>(null),
    [editingRevision, setEditingRevision] = useState(meeting.revision),
    [text, setText] = useState(""),
    [rename, setRename] = useState<{
      key: string;
      label: string;
      original: string;
      revision: number;
    } | null>(null);
  const { busy, work } = useWork();
  const listen = useReviewAudio();
  const stopAudio = useStopReviewAudio();
  const [peopleView, setPeopleView] = useState(people),
    [page, setPage] = useState(1),
    [listening, setListening] = useState<string | null>(null);
  const guard = useUnsavedForm(
    (!!editing && text !== editing.text) ||
      (!!rename && rename.label !== rename.original),
  );
  useEffect(
    () => setPage(1),
    [search, speaker, review, meeting.active_transcript_id],
  );
  if (data.isPending) return <Loading />;
  if (data.error) return <ErrorBox error={data.error} />;
  const rows = data.data?.segments || [];
  const groups = Array.from(
    new Set(rows.filter((r) => r.speaker_key).map((r) => r.speaker_key!)),
  ).map((key) => ({
    key,
    label: rows.find((r) => r.speaker_key === key)!.speaker_label,
    segments: rows.filter((r) => r.speaker_key === key),
  }));
  const unknown = rows.filter((r) => !r.speaker_key && r.speaker_count === 1),
    overlap = rows.filter((r) => r.speaker_count > 1);
  const filtered = rows.filter(
    (r) =>
      (!search ||
        r.text
          .toLocaleLowerCase("vi")
          .includes(search.toLocaleLowerCase("vi"))) &&
      (!speaker ||
        (speaker === "unknown"
          ? !r.speaker_key && r.speaker_count === 1
          : speaker === "overlap"
            ? r.speaker_count > 1
            : r.speaker_key === speaker)) &&
      (!review || r.needs_review),
  );
  return (
    <>
      {!!rows.length && (
        <div className="transcript-view-tools">
          <h2>Lời chép</h2>
          <div
            className="segmented-control"
            role="group"
            aria-label="Cách xem lời chép"
          >
            <button
              className={!peopleView ? "active" : ""}
              aria-pressed={!peopleView}
              onClick={() => setPeopleView(false)}
            >
              <FileText size={15} />
              Nội dung
            </button>
            <button
              className={peopleView ? "active" : ""}
              aria-pressed={peopleView}
              onClick={() => setPeopleView(true)}
            >
              <Users size={15} />
              Người nói
            </button>
          </div>
        </div>
      )}
      {data.data?.version?.timing_complete === false && (
        <Notice tone="info">
          Còn phần chưa căn được vào đồng hồ chung hoặc mốc đang mâu thuẫn. Thời
          gian ở các phần đó là cục bộ; hãy rà timeline trước khi tạo biên bản.
        </Notice>
      )}
      {!rows.length ? (
        <Panel>
          <Empty
            title="Chưa có lời chép"
            description="Thêm file ở mục Nguồn âm thanh và bắt đầu xử lý."
          />
        </Panel>
      ) : peopleView ? (
        <>
          <div className="stat-grid">
            <Panel>
              <span className="muted">Cụm người nói</span>
              <h2 className="big-number">{groups.length}</h2>
            </Panel>
            <Panel>
              <span className="muted">Đoạn chưa xác định</span>
              <h2 className="big-number">{unknown.length}</h2>
            </Panel>
            <Panel>
              <span className="muted">Đoạn nói chồng</span>
              <h2 className="big-number">{overlap.length}</h2>
            </Panel>
          </div>
          <Notice tone="info">
            Nhãn “Chưa xác định” và “Nói chồng” mô tả trạng thái đoạn âm thanh,
            không được tính là người tham gia. Đổi tên một cụm giữ nguyên mã
            định danh của cụm.
          </Notice>
          <div className="cards-grid">
            {groups.map((g) => (
              <Panel key={g.key}>
                <div className="row between">
                  <span className="avatar large">{g.label[0]}</span>
                  <Button
                    variant="ghost"
                    disabled={!!meeting.active_job || meeting.trashed}
                    onClick={() =>
                      setRename({
                        revision: meeting.revision,
                        key: g.key,
                        label: g.label,
                        original: g.label,
                      })
                    }
                  >
                    <Edit3 size={16} />
                    Đổi nhãn
                  </Button>
                </div>
                <h3>{g.label}</h3>
                <p className="muted">
                  {g.segments.length} đoạn ·{" "}
                  {time(
                    g.segments.reduce((n, r) => n + r.end_sec - r.start_sec, 0),
                  )}
                </p>
                <p className="quote">
                  {g.segments.find((s) => s.text)?.text.slice(0, 180) ||
                    "Không có lời chép"}
                </p>
                {g.segments.find((s) => s.clip)?.clip && (
                  <Button
                    variant="outline"
                    onClick={() =>
                      listen({
                        url: g.segments.find((s) => s.clip)!.clip!.url,
                        title: g.label,
                        range: "Đoạn đối chiếu giọng",
                      })
                    }
                  >
                    <Headphones size={16} />
                    Nghe đoạn mẫu
                  </Button>
                )}
              </Panel>
            ))}
          </div>
        </>
      ) : (
        <Panel>
          <div className="list-toolbar">
            <div className="search-field">
              <Search size={17} />
              <input
                aria-label="Tìm trong lời chép"
                placeholder="Tìm trong toàn bộ lời chép…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <select
              aria-label="Lọc người nói"
              value={speaker}
              onChange={(e) => setSpeaker(e.target.value)}
            >
              <option value="">Tất cả người nói</option>
              {groups.map((g) => (
                <option key={g.key} value={g.key}>
                  {g.label}
                </option>
              ))}
              <option value="unknown">Chưa xác định ({unknown.length})</option>
              <option value="overlap">Nói chồng ({overlap.length})</option>
            </select>
            <label className="check-label">
              <input
                type="checkbox"
                checked={review}
                onChange={(e) => setReview(e.target.checked)}
              />
              Chỉ đoạn cần rà soát
            </label>
          </div>
          <p className="small muted">
            {filtered.length}/{rows.length} đoạn
          </p>
          <div className="transcript-list">
            {filtered.slice((page - 1) * 50, page * 50).map((row) => (
              <article
                id={"turn-" + row.turn_id}
                className={
                  "transcript-row " +
                  (row.needs_review ? "needs-review " : "") +
                  (listening === row.id ? "is-listening" : "")
                }
                key={row.id}
              >
                <span className="transcript-time">
                  {row.time_status === "unresolved" && (
                    <small>{row.clock_label} · Giờ cục bộ</small>
                  )}
                  {segmentTime(row, row.start_sec)}
                  <small>{segmentTime(row, row.end_sec)}</small>
                </span>
                <div className="transcript-text">
                  <div className="row">
                    <strong>{row.speaker_label}</strong>
                    {row.time_status === "estimated" && (
                      <span className="mini-label">Giờ ước lượng</span>
                    )}
                    {row.speaker_count > 1 ? (
                      <span className="mini-label">Nói chồng</span>
                    ) : !row.speaker_key ? (
                      <span className="mini-label">Chưa xác định</span>
                    ) : null}
                    {row.user_edited && (
                      <span className="mini-label green">
                        <Check size={12} />
                        Đã sửa
                      </span>
                    )}
                    {row.excluded_from_minutes && (
                      <span className="mini-label">Ngoài biên bản</span>
                    )}
                  </div>
                  <p>
                    {row.text || (
                      <em className="muted">
                        Chưa có lời chép hợp lệ. Cần nghe lại âm thanh.
                      </em>
                    )}
                  </p>
                  {row.needs_review &&
                    !row.user_edited &&
                    !!row.review_reasons?.length && (
                      <div>
                        <small className="muted">
                          {row.review_reasons.join(" ")}
                        </small>
                      </div>
                    )}
                  {!!row.source_candidates?.length && row.needs_review && (
                    <details>
                      <summary>Đối chiếu nguồn ghi</summary>
                      {row.source_candidates.map((candidate, index) => (
                        <div key={index}>
                          <small className="muted">{candidate.label}</small>
                          <p>{candidate.text}</p>
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={!!meeting.active_job || meeting.trashed}
                            onClick={() => {
                              stopAudio();
                              setEditing(row);
                              setEditingRevision(meeting.revision);
                              setText(candidate.text);
                            }}
                          >
                            Chọn để rà soát
                          </Button>
                        </div>
                      ))}
                    </details>
                  )}
                  {row.clip ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setListening(row.id);
                        listen({
                          url: row.clip!.url,
                          title: row.speaker_label,
                          range:
                            (row.time_status === "unresolved"
                              ? (row.clock_label || "Giờ cục bộ") + " · "
                              : "") +
                            segmentTime(row, row.start_sec) +
                            " – " +
                            segmentTime(row, row.end_sec),
                        });
                      }}
                    >
                      <Headphones size={15} />
                      Nghe đoạn
                    </Button>
                  ) : (
                    <small className="muted">
                      Chưa có đoạn cắt âm thanh riêng (mốc giờ chưa xác định
                      hoặc ngoài vùng nguồn).
                    </small>
                  )}
                  {row.context_audio && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setListening(row.id);
                        listen({
                          url: row.context_audio!.audio.url,
                          title: "Nghe kèm ngữ cảnh · " + row.speaker_label,
                          range:
                            segmentTime(row, row.start_sec) +
                            " – " +
                            segmentTime(row, row.end_sec) +
                            " · Kèm âm thanh trước/sau",
                          start: row.context_audio!.start_sec,
                          end: row.context_audio!.end_sec,
                        });
                      }}
                    >
                      <Headphones size={15} />
                      Nghe kèm ngữ cảnh
                    </Button>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={"Sửa đoạn " + row.turn_id}
                  disabled={!!meeting.active_job || meeting.trashed}
                  onClick={() => {
                    stopAudio();
                    setEditing(row);
                    setEditingRevision(meeting.revision);
                    setText(row.text);
                  }}
                >
                  <Edit3 size={16} />
                </Button>
              </article>
            ))}
          </div>
          {!filtered.length && (
            <Empty
              title="Không có đoạn phù hợp"
              action={
                <Button
                  variant="outline"
                  onClick={() => {
                    setSearch("");
                    setSpeaker("");
                    setReview(false);
                  }}
                >
                  Bỏ bộ lọc
                </Button>
              }
            />
          )}
          {filtered.length > 50 && (
            <div className="pagination">
              <span>
                Trang {page}/{Math.ceil(filtered.length / 50)}
              </span>
              <div className="row">
                <Button
                  variant="outline"
                  disabled={page <= 1}
                  onClick={() => setPage(page - 1)}
                >
                  <ChevronLeft size={16} />
                  Trước
                </Button>
                <Button
                  variant="outline"
                  disabled={page * 50 >= filtered.length}
                  onClick={() => setPage(page + 1)}
                >
                  Sau
                  <ChevronRight size={16} />
                </Button>
              </div>
            </div>
          )}
        </Panel>
      )}
      <Modal
        open={!!editing}
        onOpenChange={(v) => !v && guard.requestClose(() => setEditing(null))}
        title="Rà soát lời chép"
        description="Đối chiếu audio trước khi sửa. Lưu thay đổi sẽ tạo một phiên bản lời chép mới."
      >
        {editing?.clip && (
          <Button
            variant="outline"
            onClick={() =>
              listen({
                url: editing.clip!.url,
                title: editing.speaker_label,
                range:
                  segmentTime(editing, editing.start_sec) +
                  " – " +
                  segmentTime(editing, editing.end_sec),
              })
            }
          >
            <Headphones size={16} />
            Nghe đoạn gốc
          </Button>
        )}
        {editingRevision !== meeting.revision && (
          <Notice>
            Dữ liệu cuộc họp đã đổi. Nội dung đang nhập vẫn được giữ; hãy mở lại
            đoạn từ phiên bản mới trước khi lưu.
          </Notice>
        )}
        <Textarea
          aria-label="Nội dung lời chép"
          rows={7}
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={12000}
        />
        <Button
          disabled={
            busy ||
            text === editing?.text ||
            editingRevision !== meeting.revision
          }
          onClick={() =>
            void work(async () => {
              await patch("/meetings/" + meeting.id + "/transcript", {
                revision: editingRevision,
                segment_id: editing!.id,
                text,
              });
              setEditing(null);
            }, "Đã lưu phiên bản lời chép mới")
          }
        >
          Lưu thay đổi
        </Button>
      </Modal>
      <Modal
        open={!!rename}
        onOpenChange={(v) => !v && guard.requestClose(() => setRename(null))}
        title="Đổi nhãn người nói"
      >
        {rename && rename.revision !== meeting.revision && (
          <Notice>
            Dữ liệu cuộc họp đã đổi. Hãy mở lại người nói từ phiên bản mới trước
            khi lưu nhãn.
          </Notice>
        )}
        <Input
          aria-label="Tên người nói"
          value={rename?.label || ""}
          onChange={(e) =>
            setRename(rename ? { ...rename, label: e.target.value } : null)
          }
          maxLength={100}
        />
        <Button
          disabled={
            busy ||
            !rename?.label.trim() ||
            rename?.label === rename?.original ||
            rename?.revision !== meeting.revision
          }
          onClick={() =>
            void work(async () => {
              await post("/meetings/" + meeting.id + "/speakers/rename", {
                revision: rename!.revision,
                speaker_key: rename!.key,
                label: rename!.label,
              });
              setRename(null);
            }, "Đã cập nhật nhãn người nói")
          }
        >
          Lưu nhãn
        </Button>
      </Modal>
      {guard.dialog}
    </>
  );
}
