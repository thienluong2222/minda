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
import { Check, Edit3, Search } from "lucide-react";
import { useState } from "react";

export function TranscriptView({
  meeting,
  people = false,
}: {
  meeting: Meeting;
  people?: boolean;
}) {
  const data = useQuery({
    queryKey: ["transcript", meeting.id, meeting.active_transcript_id],
    queryFn: () => api<Transcript>("/meetings/" + meeting.id + "/transcript"),
  });
  const [search, setSearch] = useState(""),
    [speaker, setSpeaker] = useState(""),
    [review, setReview] = useState(false),
    [editing, setEditing] = useState<Segment | null>(null),
    [text, setText] = useState(""),
    [rename, setRename] = useState<{ key: string; label: string } | null>(null);
  const { busy, work } = useWork();
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
      {!rows.length ? (
        <Panel>
          <Empty
            title="Chưa có transcript"
            description="Tải bản ghi âm ở mục Tổng quan và bắt đầu xử lý."
          />
        </Panel>
      ) : people ? (
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
                    onClick={() => setRename({ key: g.key, label: g.label })}
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
                  <audio
                    controls
                    preload="none"
                    src={g.segments.find((s) => s.clip)!.clip!.url}
                  />
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
                aria-label="Tìm trong transcript"
                placeholder="Tìm nội dung transcript…"
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
            {filtered.length}/{rows.length} đoạn · Chỉnh sửa luôn tạo phiên bản
            mới.
          </p>
          <div className="transcript-list">
            {filtered.map((row) => (
              <article
                id={"turn-" + row.turn_id}
                className={
                  "transcript-row " + (row.needs_review ? "needs-review" : "")
                }
                key={row.id}
              >
                <span className="transcript-time">
                  {time(row.start_sec)}
                  <small>{time(row.end_sec)}</small>
                </span>
                <div className="transcript-text">
                  <div className="row">
                    <strong>{row.speaker_label}</strong>
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
                  </div>
                  <p>
                    {row.text || (
                      <em className="muted">
                        Chưa có lời chép hợp lệ. Cần nghe lại âm thanh.
                      </em>
                    )}
                  </p>
                  {row.clip && (
                    <audio controls preload="none" src={row.clip.url} />
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={"Sửa đoạn " + row.turn_id}
                  disabled={!!meeting.active_job || meeting.trashed}
                  onClick={() => {
                    setEditing(row);
                    setText(row.text);
                  }}
                >
                  <Edit3 size={16} />
                </Button>
              </article>
            ))}
          </div>
        </Panel>
      )}
      <Modal
        open={!!editing}
        onOpenChange={(v) => !v && setEditing(null)}
        title="Rà soát lời chép"
        description="Sửa lỗi ASR theo âm thanh. Thời gian, người nói và bằng chứng được giữ lại."
      >
        {editing?.clip && <audio controls src={editing.clip.url} />}
        <Textarea
          aria-label="Nội dung lời chép"
          rows={7}
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={12000}
        />
        <Button
          disabled={busy || text === editing?.text}
          onClick={() =>
            void work(async () => {
              await patch("/meetings/" + meeting.id + "/transcript", {
                revision: meeting.revision,
                segment_id: editing!.id,
                text,
              });
              setEditing(null);
            }, "Đã lưu phiên bản transcript mới")
          }
        >
          Lưu thay đổi
        </Button>
      </Modal>
      <Modal
        open={!!rename}
        onOpenChange={(v) => !v && setRename(null)}
        title="Đổi nhãn người nói"
      >
        <Input
          aria-label="Tên người nói"
          value={rename?.label || ""}
          onChange={(e) =>
            setRename(rename ? { ...rename, label: e.target.value } : null)
          }
          maxLength={100}
        />
        <Button
          disabled={busy || !rename?.label.trim()}
          onClick={() =>
            void work(async () => {
              await post("/meetings/" + meeting.id + "/speakers/rename", {
                revision: meeting.revision,
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
    </>
  );
}
