import {
  Action,
  DownloadLink,
  Empty,
  ErrorBox,
  JsonDetails,
  Loading,
  Modal,
  Notice,
  Panel,
  Preview,
  Status,
  useWork,
} from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, patch, post, time } from "@/lib/api";
import type {
  Capabilities,
  Fact,
  Meeting,
  MinutesOptions,
  MinutesVersion,
  Template,
  Transcript,
} from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import {
  Check,
  FileText,
  Link2,
  Save,
  Settings2,
  Sparkles,
  Headphones,
  X,
  Eye,
  AlignLeft,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { SplitPane } from "@/components/split-pane";
import { useReviewAudio, useStopReviewAudio } from "@/components/review-audio";
import { useUnsavedForm } from "@/lib/unsaved";
import { MeetingOutline } from "./outline";

export const defaultOptions: MinutesOptions = {
  mode: "detailed",
  use_model: true,
  correct_transcript: true,
  use_fcm: true,
  clusters: null,
  content_field_id: null,
  format_standard: "nd30_2020",
  two_sided: false,
  document_metadata: {},
};
const metadataLabels: Record<string, string> = {
  parent_organization: "Cơ quan chủ quản",
  organization: "Cơ quan, đơn vị",
  organization_abbreviation: "Ký hiệu đơn vị",
  document_number: "Số văn bản",
  issue_place: "Địa danh ban hành",
  issue_date: "Ngày ban hành",
  chairperson: "Chủ trì",
  secretary: "Thư ký",
  recipients: "Nơi nhận",
  confirmer_position: "Chức vụ người xác nhận",
  confirmer_name: "Họ tên người xác nhận",
};

export function OptionsForm({
  value,
  onChange,
  fields = [],
  graphEnabled = false,
}: {
  value: MinutesOptions;
  onChange: (value: MinutesOptions) => void;
  fields?: { field_id: string; raw_label: string }[];
  graphEnabled?: boolean;
}) {
  const update = (change: Partial<MinutesOptions>) =>
    onChange({ ...value, ...change });
  return (
    <div className="form-stack">
      <div className="form-grid">
        <label>
          Loại biên bản
          <select
            value={value.mode}
            onChange={(e) =>
              update({
                mode: e.target.value as MinutesOptions["mode"],
                use_model:
                  e.target.value === "general" ? true : value.use_model,
              })
            }
          >
            <option value="detailed">Chi tiết · giữ nguyên đề mục</option>
            <option value="general">Tổng quát · chia mục theo nội dung</option>
          </select>
        </label>
        <label>
          Thể thức trình bày
          <select
            value={value.format_standard}
            onChange={(e) =>
              update({
                format_standard: e.target
                  .value as MinutesOptions["format_standard"],
                two_sided: false,
              })
            }
          >
            <option value="nd30_2020">Hành chính · Nghị định 30/2020</option>
            <option value="hd05_2026">Tài liệu Đảng · Hướng dẫn 05/2026</option>
            <option value="minimal">
              Tối thiểu · Nội dung rõ ràng, tự nhiên
            </option>
          </select>
        </label>
      </div>
      <div className="checks-box">
        <label className="check-label">
          <input
            type="checkbox"
            checked={graphEnabled || value.use_model}
            disabled={graphEnabled || value.mode === "general"}
            onChange={(e) => update({ use_model: e.target.checked })}
          />
          Biên tập câu chữ tự động
        </label>
        <label className="check-label">
          <input
            type="checkbox"
            checked={value.correct_transcript}
            disabled={!graphEnabled && !value.use_model}
            onChange={(e) => update({ correct_transcript: e.target.checked })}
          />
          Rà lỗi chính tả theo ngữ cảnh
        </label>
        {value.mode === "general" && (
          <>
            <label className="check-label">
              <input
                type="checkbox"
                checked={value.use_fcm}
                onChange={(e) => update({ use_fcm: e.target.checked })}
              />
              Nhóm ý kiến theo chủ đề
            </label>
            <label>
              Số chủ đề (để trống: tự chọn)
              <Input
                type="number"
                min={1}
                max={12}
                value={value.clusters ?? ""}
                onChange={(e) =>
                  update({
                    clusters: e.target.value ? Number(e.target.value) : null,
                  })
                }
              />
            </label>
            <label>
              Trường nội dung cuộc họp
              <select
                value={value.content_field_id || ""}
                onChange={(e) =>
                  update({ content_field_id: e.target.value || null })
                }
              >
                <option value="">Tự xác định trường nội dung</option>
                {fields.map((f) => (
                  <option value={f.field_id} key={f.field_id}>
                    {f.raw_label} ({f.field_id})
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
        {value.format_standard === "hd05_2026" && (
          <label className="check-label">
            <input
              type="checkbox"
              checked={value.two_sided}
              onChange={(e) => update({ two_sided: e.target.checked })}
            />
            Bố cục in hai mặt
          </label>
        )}
      </div>
      <details>
        <summary>Thông tin trình bày và ký xác nhận</summary>
        <div className="form-grid metadata-grid">
          {Object.entries(metadataLabels).map(([key, label]) => (
            <label key={key}>
              {label}
              <Input
                type={key === "issue_date" ? "date" : "text"}
                value={value.document_metadata[key] || ""}
                onChange={(e) =>
                  update({
                    document_metadata: {
                      ...value.document_metadata,
                      [key]: e.target.value || null,
                    },
                  })
                }
              />
            </label>
          ))}
          {value.format_standard === "hd05_2026" && (
            <label>
              Thẩm quyền ký
              <select
                value={value.document_metadata.party_signature || "review"}
                onChange={(e) =>
                  update({
                    document_metadata: {
                      ...value.document_metadata,
                      party_signature: e.target.value,
                    },
                  })
                }
              >
                <option value="review">Để người dùng rà soát</option>
                <option value="direct">Ký trực tiếp</option>
                <option value="confirmation">Có xác nhận</option>
              </select>
            </label>
          )}
        </div>
      </details>
    </div>
  );
}

export function MinutesView({
  meeting,
}: {
  meeting: Meeting & {
    preferred_template_id?: string;
    preferred_mode?: MinutesOptions["mode"];
    preferred_format?: MinutesOptions["format_standard"];
  };
}) {
  const data = useQuery({
    queryKey: ["minutes", meeting.id, meeting.active_minutes_id],
    queryFn: () =>
      api<{
        version: MinutesVersion | null;
        stale: boolean;
        meeting_revision: number;
      }>("/meetings/" + meeting.id + "/minutes"),
  });
  const templates = useQuery({
    queryKey: ["templates"],
    queryFn: () => api<Template[]>("/templates"),
  });
  const caps = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<Capabilities>("/capabilities"),
  });
  const transcript = useQuery({
    queryKey: [
      "transcript",
      meeting.id,
      data.data?.version?.transcript_version_id || meeting.active_transcript_id,
    ],
    queryFn: () =>
      api<Transcript>(
        "/meetings/" +
          meeting.id +
          "/transcript" +
          (data.data?.version?.transcript_version_id
            ? "?version_id=" + data.data.version.transcript_version_id
            : ""),
      ),
  });
  const activeTranscript = useQuery({
    queryKey: ["transcript", meeting.id, meeting.active_transcript_id],
    queryFn: () => api<Transcript>("/meetings/" + meeting.id + "/transcript"),
    enabled: !!meeting.active_transcript_id,
  });
  const [template, setTemplate] = useState(meeting.preferred_template_id || ""),
    [options, setOptions] = useState<MinutesOptions>({
      ...defaultOptions,
      mode: meeting.preferred_mode || "detailed",
      format_standard: meeting.preferred_format || "nd30_2020",
    }),
    [configure, setConfigure] = useState(false),
    [configured, setConfigured] = useState(false),
    [configDirty, setConfigDirty] = useState(false),
    [editing, setEditing] = useState<Fact | null>(null),
    [value, setValue] = useState(""),
    [entries, setEntries] = useState<string[]>([]),
    [status, setStatus] = useState("needs_review"),
    [reason, setReason] = useState(""),
    [filter, setFilter] = useState("all"),
    [evidence, setEvidence] = useState<Fact | null>(null);
  const { busy, work } = useWork();
  const listen = useReviewAudio(),
    stopAudio = useStopReviewAudio();
  const [narrow, setNarrow] = useState(
    () => window.matchMedia("(max-width: 1100px)").matches,
  );
  useEffect(() => {
    const media = window.matchMedia("(max-width: 1100px)");
    const changed = () => setNarrow(media.matches);
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, []);
  const [viewMode, setViewMode] = useState("content"),
    [editingRevision, setEditingRevision] = useState(meeting.revision);
  const dirty =
    !!editing &&
    (JSON.stringify(Array.isArray(editing.value) ? entries : value || null) !==
      JSON.stringify(editing.value) ||
      status !== editing.status ||
      reason !== (editing.reason || ""));
  const guard = useUnsavedForm(dirty || configDirty);
  const version = data.data?.version;
  const chosenOptions =
    !version && !configured && caps.data
      ? {
          ...options,
          use_model:
            options.mode === "general" ? true : caps.data.preset.use_model,
          format_standard:
            meeting.preferred_format ||
            (caps.data.preset
              .default_format as MinutesOptions["format_standard"]),
        }
      : options;
  const blocked = !!meeting.active_job || meeting.trashed;
  const timingIncomplete =
    activeTranscript.data?.version?.timing_complete === false;
  useEffect(() => {
    setEvidence(null);
    if (version) {
      setOptions({ ...defaultOptions, ...version.options });
      setTemplate(version.template_id);
    }
  }, [version?.id]);
  if (data.isPending) return <Loading />;
  if (data.error) return <ErrorBox error={data.error} />;
  const readyTemplates =
    templates.data?.filter((t) => t.state === "ready" && !t.needs_review) || [];
  const renderConfig = () => (
    <>
      <label>
        Mẫu tài liệu
        <select
          aria-label="Mẫu biên bản"
          value={template}
          onChange={(e) => {
            setTemplate(e.target.value);
            setConfigDirty(true);
          }}
        >
          <option value="">Chọn một mẫu đã duyệt</option>
          {readyTemplates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} · {t.field_count || 0} trường
            </option>
          ))}
        </select>
      </label>
      <OptionsForm
        value={chosenOptions}
        graphEnabled={caps.data?.preset.minutes_graph_enabled ?? true}
        onChange={(value) => {
          setConfigured(true);
          setConfigDirty(true);
          setOptions(value);
        }}
        fields={version?.schema.fields}
      />
      {caps.data?.preset.minutes_graph_enabled && (
        <Notice tone="info">
          Đang bật biên bản bằng đồ thị: hệ thống tổ chức chủ đề, sự kiện và căn
          cứ trước khi biên tập. Sau khi tạo xong, mở tab Đồ thị cuộc họp để đối
          chiếu.
        </Notice>
      )}
      <Notice tone="info">
        Thông tin không có căn cứ sẽ được để trống hoặc đánh dấu cần rà soát.
        Chế độ tổng quát giữ lại các ý có trong lời chép.
      </Notice>
      {timingIncomplete && (
        <Notice>
          Còn đoạn chưa xác định được thời gian chung. Hãy rà nguồn ghi âm và xử
          lý lại trước khi tạo biên bản.
        </Notice>
      )}
      {activeTranscript.error && <ErrorBox error={activeTranscript.error} />}
      <Button
        disabled={
          busy ||
          blocked ||
          !template ||
          !meeting.active_transcript_id ||
          activeTranscript.isPending ||
          !!activeTranscript.error ||
          timingIncomplete ||
          meeting.state === "draft"
        }
        onClick={() =>
          void work(async () => {
            await post("/meetings/" + meeting.id + "/minutes/generate", {
              revision: meeting.revision,
              template_id: template,
              options: chosenOptions,
            });
            setConfigure(false);
            setConfigDirty(false);
          }, "Đã xếp hàng tạo biên bản")
        }
      >
        <Sparkles size={16} />
        Tạo biên bản từ lời chép
      </Button>
    </>
  );
  const selectedRows =
    evidence?.evidence_refs.map((ref) => ({
      ref,
      rows:
        transcript.data?.segments.filter(
          (s) =>
            s.turn_id === ref.turn_id ||
            (ref.turn_id?.startsWith("merged-") &&
              ref.turn_id?.match(/turn_\d+/g)?.includes(s.turn_id)),
        ) || [],
    })) || [];
  const editForm = (
    <div className="inline-fact-editor">
      <p className="save-status" role="status">
        {dirty ? "Thay đổi chưa lưu" : "Đang chỉnh sửa"}
      </p>
      {editingRevision !== meeting.revision && (
        <Notice>
          Dữ liệu cuộc họp đã đổi. Nội dung bạn nhập vẫn được giữ; hãy mở lại
          mục từ phiên bản mới trước khi lưu.
        </Notice>
      )}
      {Array.isArray(editing?.value) ? (
        <div className="form-stack">
          {entries.map((entry, index) => (
            <div className="list-entry-edit" key={index}>
              <Textarea
                autoFocus={index === 0}
                aria-label={"Mục " + (index + 1)}
                rows={3}
                value={entry}
                onChange={(e) => {
                  setEntries(
                    entries.map((item, i) =>
                      i === index ? e.target.value : item,
                    ),
                  );
                  setStatus("needs_review");
                }}
              />
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setEntries(entries.filter((_, i) => i !== index));
                  setStatus("needs_review");
                }}
              >
                Bỏ mục
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            onClick={() => setEntries([...entries, ""])}
          >
            Thêm mục
          </Button>
        </div>
      ) : (
        <Textarea
          autoFocus
          rows={8}
          aria-label="Giá trị trường dữ liệu"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setStatus("needs_review");
          }}
        />
      )}
      <label>
        Trạng thái
        <select
          aria-label="Trạng thái"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="supported">Có căn cứ · đã đối chiếu</option>
          <option value="needs_review">Cần rà soát</option>
          <option value="unknown">Thiếu thông tin</option>
          <option value="conflicting">Mâu thuẫn</option>
        </select>
      </label>
      <label>
        Ghi chú rà soát
        <Input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={2000}
        />
      </label>
      <Button
        disabled={
          busy || blocked || !dirty || editingRevision !== meeting.revision
        }
        onClick={() =>
          void work(async () => {
            const parsed = Array.isArray(editing!.value)
              ? entries.map((e) => e.trim()).filter(Boolean)
              : value || null;
            await patch("/meetings/" + meeting.id + "/minutes/facts", {
              revision: editingRevision,
              patches: [
                {
                  field_id: editing!.field_id,
                  value: parsed,
                  status,
                  reason,
                },
              ],
            });
            setEditing(null);
          }, "Đã xếp hàng lưu trường và cập nhật DOCX")
        }
      >
        <Save size={16} />
        Lưu & cập nhật tài liệu
      </Button>
      <Button
        variant="ghost"
        onClick={() => guard.requestClose(() => setEditing(null))}
      >
        Hủy chỉnh sửa
      </Button>
    </div>
  );
  const evidencePanel = evidence ? (
    <Panel className="evidence-panel">
      {!narrow && (
        <div className="evidence-panel-heading">
          <h2>Đối chiếu lời gốc</h2>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Đóng căn cứ"
            onClick={() => setEvidence(null)}
          >
            <X size={17} />
          </Button>
        </div>
      )}
      <h3>
        {version?.schema.fields.find(
          (field) => field.field_id === evidence.field_id,
        )?.raw_label || "Nội dung đang chọn"}
      </h3>
      {selectedRows.length ? (
        selectedRows.map(({ ref, rows }, i) => (
          <div className="evidence-card" key={i}>
            <span className="eyebrow">
              {Array.from(new Set(rows.map((r) => r.speaker_label))).join(
                ", ",
              ) ||
                ref.source_kind ||
                ref.source_type ||
                "Nguồn tham chiếu"}{" "}
              {(ref.start_sec ?? rows[0]?.start_sec) != null &&
                (ref.end_sec ?? rows.at(-1)?.end_sec) != null && (
                  <>
                    {" "}
                    · {time(ref.start_sec ?? rows[0].start_sec)} –{" "}
                    {time(ref.end_sec ?? rows.at(-1)!.end_sec)}
                  </>
                )}
            </span>
            <p>
              {ref.text_snippet ||
                rows.map((r) => r.text).join(" ") ||
                ref.text ||
                "Bằng chứng từ metadata hoặc rà soát của người dùng."}
            </p>
            {rows
              .filter((r) => r.clip)
              .map((row) => (
                <div key={row.id}>
                  {rows.length > 1 && (
                    <small>
                      {time(row.start_sec)} – {time(row.end_sec)}
                    </small>
                  )}
                  <Button
                    variant="outline"
                    onClick={() =>
                      listen({
                        url: row.clip!.url,
                        title: row.speaker_label,
                        range:
                          (row.clock_label || "Cuộc họp") +
                          " · " +
                          time(row.start_sec) +
                          " – " +
                          time(row.end_sec),
                      })
                    }
                  >
                    <Headphones size={15} />
                    Nghe đoạn gốc
                  </Button>
                </div>
              ))}
            {!rows.some((r) => r.clip) && ref.clip_artifact_id && (
              <Button
                variant="outline"
                onClick={() =>
                  listen({
                    url: "/api/v1/artifacts/" + ref.clip_artifact_id,
                    title: "Âm thanh căn cứ",
                    range:
                      time(ref.start_sec || 0) + " – " + time(ref.end_sec || 0),
                  })
                }
              >
                <Headphones size={15} />
                Nghe đoạn gốc
              </Button>
            )}
            {ref.source_kind === "transcript" &&
              !rows.some((r) => r.clip) &&
              !ref.clip_artifact_id && (
                <p className="small muted">
                  Bằng chứng văn bản đã được lưu. Phiên bản này chưa có clip âm
                  thanh đính kèm.
                </p>
              )}
            <JsonDetails value={ref} label="Thông tin nguồn" />
          </div>
        ))
      ) : (
        <Empty
          title="Chưa có bằng chứng đính kèm"
          description="Hãy kiểm tra thông tin đầu vào trước khi xác nhận giá trị."
        />
      )}
    </Panel>
  ) : null;
  return (
    <>
      {!version ? (
        <div className="two-columns">
          <Panel
            title="Tạo biên bản"
            description="Chọn mẫu và cấu hình để tạo tài liệu có thể chỉnh sửa."
          >
            <div className="form-stack">
              {meeting.active_transcript_id && meeting.state === "draft" && (
                <Notice>
                  Nguồn ghi âm hoặc hồ sơ người tham gia đã thay đổi. Hãy xử lý
                  lại âm thanh trước khi tạo biên bản mới.
                </Notice>
              )}
              {!meeting.active_transcript_id && (
                <Notice>
                  Hãy xử lý âm thanh và rà soát lời chép trước khi tạo biên bản.
                </Notice>
              )}
              {!readyTemplates.length && (
                <Notice>
                  Chưa có mẫu sẵn sàng. Hãy tải mẫu và hoàn tất bước duyệt trong
                  Thư viện mẫu.
                </Notice>
              )}
              {renderConfig()}
            </div>
          </Panel>
          <Panel className="document-placeholder">
            <FileText size={50} />
            <h2>Biên bản theo mẫu của bạn</h2>
            <p className="muted">
              Giữ đề mục đã có với biên bản chi tiết, hoặc chia nội dung thành
              các chủ đề với biên bản tổng quát.
            </p>
            <div className="paper-mock">
              <span />
              <span />
              <b />
              <span />
              <span />
              <span />
              <b />
              <span />
              <span />
            </div>
          </Panel>
        </div>
      ) : (
        <>
          {version.graph_id && (
            <Button asChild variant="outline">
              <Link
                to={`?tab=graph&graph_version=${encodeURIComponent(version.id)}`}
              >
                Khám phá đồ thị và căn cứ của biên bản
              </Link>
            </Button>
          )}
          {version.graph_id && (
            <MeetingOutline
              key={version.id}
              meetingId={meeting.id}
              versionId={version.id}
              editable={!blocked && !data.data?.stale}
            />
          )}
          {data.data?.stale && (
            <Notice>
              Lời chép hoặc thông tin cuộc họp đã thay đổi. Biên bản này dùng dữ
              liệu của phiên bản trước; hãy tạo lại rồi rà soát.
            </Notice>
          )}
          {version.facts.some(
            (fact) => fact.previous_edit || fact.status === "conflicting",
          ) && (
            <Notice>
              Xử lý các dữ kiện mâu thuẫn hoặc giá trị đã sửa ở bản trước để xác
              nhận biên bản.
            </Notice>
          )}
          <div className="minutes-toolbar">
            <div className="row">
              <Status
                value={
                  meeting.reviewed_version === version.id
                    ? "succeeded"
                    : "needs_review"
                }
              />
              <span className="muted small">
                {version.options?.mode === "general" ? "Tổng quát" : "Chi tiết"}{" "}
                ·{" "}
                {version.options?.format_standard === "hd05_2026"
                  ? "Hướng dẫn 05"
                  : "Nghị định 30"}
              </span>
            </div>
            <div className="row">
              <Button
                variant="outline"
                disabled={blocked}
                onClick={() => setConfigure(true)}
              >
                <Settings2 size={16} />
                Tạo lại biên bản
              </Button>
              <Action
                disabled={
                  blocked ||
                  data.data?.stale ||
                  version.facts.some(
                    (fact) =>
                      fact.previous_edit || fact.status === "conflicting",
                  ) ||
                  meeting.reviewed_version === version.id
                }
                run={() =>
                  post("/meetings/" + meeting.id + "/minutes/review", {
                    revision: meeting.revision,
                  })
                }
                message="Đã xác nhận phiên bản đã rà soát"
              >
                <Check size={16} />
                Đã rà soát
              </Action>
              <DownloadLink artifact={version.docx} label="Tải Word" />
              <details className="export-menu">
                <summary>Xuất thêm</summary>
                <DownloadLink artifact={version.zip} label="Gói căn cứ" />
              </details>
            </div>
          </div>
          <div className="document-view-toolbar">
            <div
              className="segmented-control"
              role="group"
              aria-label="Chế độ xem biên bản"
            >
              <button
                className={viewMode === "content" ? "active" : ""}
                aria-pressed={viewMode === "content"}
                onClick={() =>
                  guard.requestClose(() => {
                    setEditing(null);
                    setViewMode("content");
                  })
                }
              >
                <AlignLeft size={16} />
                Nội dung
              </button>
              <button
                className={viewMode === "preview" ? "active" : ""}
                aria-pressed={viewMode === "preview"}
                onClick={() =>
                  guard.requestClose(() => {
                    setEditing(null);
                    setViewMode("preview");
                  })
                }
              >
                <Eye size={16} />
                Xem trước Word
              </button>
            </div>
            <span className="muted small">
              {version.facts.filter((f) => f.status !== "supported").length} mục
              cần rà
            </span>
          </div>
          <SplitPane
            primary={
              viewMode === "content" ? (
                <>
                  <Panel className="facts-panel" title="Nội dung biên bản">
                    <div className="segmented-control">
                      {[
                        ["all", "Tất cả"],
                        ["review", "Cần rà soát"],
                        ["edited", "Đã sửa"],
                      ].map(([key, label]) => (
                        <button
                          className={filter === key ? "active" : ""}
                          aria-pressed={filter === key}
                          onClick={() =>
                            guard.requestClose(() => {
                              setEditing(null);
                              setFilter(key);
                            })
                          }
                          key={key}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    <div className="facts-list">
                      {version.facts
                        .filter(
                          (f) =>
                            filter === "all" ||
                            (filter === "review" && f.status !== "supported") ||
                            (filter === "edited" && f.user_edited),
                        )
                        .map((f) => {
                          const field = version.schema.fields.find(
                            (s) => s.field_id === f.field_id,
                          );
                          return (
                            <article
                              className={
                                "fact-item fact-" +
                                f.status +
                                (evidence?.field_id === f.field_id
                                  ? " is-selected"
                                  : "")
                              }
                              key={f.field_id}
                            >
                              <div className="row between">
                                <span className="field-section">
                                  {field?.section || "Thông tin"}
                                </span>
                                <Status value={f.status} />
                              </div>
                              <h3>{field?.raw_label || f.field_id}</h3>
                              {editing?.field_id === f.field_id ? (
                                editForm
                              ) : (
                                <div className="fact-value">
                                  {Array.isArray(f.value) ? (
                                    <ul>
                                      {f.value.map((v, i) => (
                                        <li key={i}>{v}</li>
                                      ))}
                                    </ul>
                                  ) : (
                                    f.value || (
                                      <span className="muted">
                                        Chưa có thông tin
                                      </span>
                                    )
                                  )}
                                </div>
                              )}
                              {f.previous_edit && (
                                <Notice>
                                  Giá trị đã sửa ở bản trước{" "}
                                  <strong>
                                    {Array.isArray(f.previous_edit.value)
                                      ? f.previous_edit.value.join("; ")
                                      : f.previous_edit.value || "(để trống)"}
                                  </strong>
                                  . Đối chiếu với dữ liệu hiện tại trước khi xác
                                  nhận.
                                </Notice>
                              )}
                              {f.reason && (
                                <details className="fact-reason">
                                  <summary>Ghi chú rà soát</summary>
                                  <p>{f.reason}</p>
                                </details>
                              )}
                              <div className="row between">
                                <button
                                  className="evidence-link"
                                  onClick={() => {
                                    if (narrow) stopAudio();
                                    setEvidence(f);
                                  }}
                                >
                                  <Link2 size={14} />
                                  {f.evidence_refs.length} căn cứ
                                </button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  disabled={
                                    blocked || editing?.field_id === f.field_id
                                  }
                                  onClick={() => {
                                    guard.requestClose(() => {
                                      setEditing(f);
                                      setEditingRevision(meeting.revision);
                                      if (!narrow) setEvidence(f);
                                      setValue(
                                        Array.isArray(f.value)
                                          ? ""
                                          : f.value || "",
                                      );
                                      setEntries(
                                        Array.isArray(f.value)
                                          ? [...f.value]
                                          : [],
                                      );
                                      setStatus(f.status);
                                      setReason(f.reason || "");
                                    });
                                  }}
                                >
                                  {f.user_edited ? (
                                    <>
                                      <Check size={13} />
                                      Đã sửa · chỉnh tiếp
                                    </>
                                  ) : (
                                    "Chỉnh sửa"
                                  )}
                                </Button>
                              </div>
                            </article>
                          );
                        })}
                    </div>
                  </Panel>
                </>
              ) : (
                <div className="preview-column">
                  <Preview pages={version.previews} download={version.docx} />
                  <details className="report-details">
                    <summary>Kết quả biên tập & kiểm tra</summary>
                    {version.report?.warnings?.map((warning, i) => (
                      <Notice key={i}>{warning}</Notice>
                    ))}
                    {version.topics?.sections && (
                      <div className="topic-list">
                        <h3>{version.topics.cluster_count} nhóm nội dung</h3>
                        {version.topics.sections.map((s, i) => (
                          <p key={i}>
                            {i + 1}. {s.title}{" "}
                            <small>({s.items.length} ý)</small>
                          </p>
                        ))}
                        <p className="muted small">
                          Độ thuộc cụm không phải xác suất chính xác. Các cụm mơ
                          hồ cần người dùng rà soát.
                        </p>
                      </div>
                    )}
                    <JsonDetails
                      value={version.formatting}
                      label="Báo cáo thể thức"
                    />
                    <JsonDetails
                      value={version.report}
                      label="Báo cáo mô hình"
                    />
                  </details>
                </div>
              )
            }
            secondary={narrow ? null : evidencePanel}
            storageKey="minda-minutes-panel"
          />
        </>
      )}
      <Modal
        open={configure}
        onOpenChange={(open) =>
          open
            ? setConfigure(true)
            : guard.requestClose(() => {
                setConfigure(false);
                setConfigured(false);
                setConfigDirty(false);
                if (version) {
                  setOptions({ ...defaultOptions, ...version.options });
                  setTemplate(version.template_id);
                }
              })
        }
        title="Cấu hình biên bản"
        wide
        description="Tạo lại dùng lời chép hiện tại; đổi thể thức dùng nội dung biên bản đang lưu."
      >
        <div className="form-stack">
          {renderConfig()}
          {version && (
            <Action
              disabled={blocked || busy}
              run={async () => {
                await post("/meetings/" + meeting.id + "/minutes/format", {
                  revision: meeting.revision,
                  options,
                });
                setConfigure(false);
                setConfigDirty(false);
              }}
              message="Đã xếp hàng đổi thể thức"
            >
              <FileText size={16} />
              Chỉ cập nhật thể thức
            </Action>
          )}
        </div>
      </Modal>

      <Modal
        wide
        open={narrow && !!evidence}
        onOpenChange={(open) => !open && setEvidence(null)}
        title="Đối chiếu lời gốc"
        description="Phát biểu gốc tương ứng với nội dung đang chọn."
      >
        {evidencePanel}
      </Modal>
      {guard.dialog}
    </>
  );
}
