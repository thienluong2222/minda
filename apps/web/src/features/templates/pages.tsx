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
  Preview,
  Status,
  useWork,
} from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, post, size } from "@/lib/api";
import type { Job, Template, TemplateField, Voice } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowUpRight,
  AudioLines,
  Check,
  FileText,
  Globe2,
  LockKeyhole,
  Plus,
  Save,
  UploadCloud,
} from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

export function Templates({ sharedOnly = false }: { sharedOnly?: boolean }) {
  const user = useUser(),
    navigate = useNavigate();
  const [open, setOpen] = useState(false),
    [name, setName] = useState(""),
    [visibility, setVisibility] = useState(sharedOnly ? "shared" : "private"),
    [file, setFile] = useState<File | null>(null);
  const { busy, work } = useWork();
  const data = useQuery({
    queryKey: ["templates"],
    queryFn: () => api<Template[]>("/templates"),
    refetchInterval: 4000,
  });
  const items =
    data.data?.filter((t) => !sharedOnly || t.visibility === "shared") || [];
  return (
    <>
      <PageHeader
        eyebrow={sharedOnly ? "QUẢN TRỊ" : "THƯ VIỆN TÀI LIỆU"}
        title={sharedOnly ? "Mẫu dùng chung" : "Thư viện mẫu biên bản"}
        description="Mẫu Word, PDF hoặc ảnh scan được chuẩn hóa thành tài liệu Word có thể chỉnh sửa."
        action={
          <Button onClick={() => setOpen(true)}>
            <Plus size={16} />
            Thêm mẫu tài liệu
          </Button>
        }
      />
      <ErrorBox error={data.error} />
      {data.isPending ? (
        <Loading />
      ) : items.length ? (
        <div className="cards-grid">
          {items.map((t) => (
            <Panel key={t.id} className="template-card">
              <div className="row between">
                <span className="template-icon">
                  <FileText size={28} />
                </span>
                <Status value={t.active_job ? "running" : t.state} />
              </div>
              <h2>
                <Link to={"/templates/" + t.id}>{t.name}</Link>
              </h2>
              <p className="muted">
                {t.visibility === "shared" ? (
                  <Globe2 size={14} />
                ) : (
                  <LockKeyhole size={14} />
                )}{" "}
                {t.visibility === "shared" ? "Dùng chung" : "Riêng tư"} ·{" "}
                {t.field_count || 0} trường dữ liệu
              </p>
              {t.needs_review ? (
                <Notice>Cần đối chiếu và duyệt trước khi sử dụng.</Notice>
              ) : (
                <span className="small green-text">
                  <Check size={14} />
                  Mẫu sẵn sàng sử dụng
                </span>
              )}
              <Link className="panel-link" to={"/templates/" + t.id}>
                Mở & rà soát mẫu
                <ArrowUpRight size={16} />
              </Link>
            </Panel>
          ))}
        </div>
      ) : (
        <Panel>
          <Empty
            title="Thêm mẫu biên bản đầu tiên"
            description="DOC/DOCX giữ cấu trúc sẵn có. PDF và ảnh scan được tái dựng, sau đó bạn duyệt lại trước khi dùng."
            action={
              <Button onClick={() => setOpen(true)}>
                <UploadCloud size={16} />
                Tải mẫu lên
              </Button>
            }
          />
        </Panel>
      )}
      <Modal
        open={open}
        onOpenChange={setOpen}
        title="Thêm mẫu tài liệu"
        description="Hỗ trợ DOC, DOCX, PDF, PNG, JPG và TIFF. Bản gốc luôn được giữ lại."
      >
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault();
            void work(async () => {
              const form = new FormData();
              form.append("name", name);
              form.append("visibility", visibility);
              form.append("file", file!);
              const result = await post<{ template_id: string }>(
                "/templates",
                form,
              );
              setOpen(false);
              navigate("/templates/" + result.template_id);
            }, "Đã xếp hàng đọc mẫu");
          }}
        >
          <label>
            Tên mẫu
            <Input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
            />
          </label>
          {user.role === "admin" && (
            <label>
              Phạm vi sử dụng
              <select
                value={visibility}
                onChange={(e) => setVisibility(e.target.value)}
              >
                <option value="private">Riêng tư</option>
                <option value="shared">Dùng chung cho mọi tài khoản</option>
              </select>
            </label>
          )}
          <label className="upload-zone compact">
            <UploadCloud size={26} />
            <strong>{file?.name || "Chọn file mẫu"}</strong>
            <input
              type="file"
              required
              accept=".doc,.docx,.pdf,.png,.jpg,.jpeg,.tif,.tiff"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </label>
          <Button type="submit" disabled={busy || !file || !name.trim()}>
            {busy ? "Đang tải…" : "Tải lên & phân tích"}
          </Button>
        </form>
      </Modal>
    </>
  );
}

const semanticLabels: Record<string, string> = {
  organization: "Cơ quan, đơn vị",
  document_number: "Số văn bản",
  document_date_place: "Ngày tháng, địa danh",
  meeting_topic: "Chủ đề cuộc họp",
  meeting_month_year: "Tháng, năm họp",
  meeting_start_time: "Giờ bắt đầu",
  meeting_end_time: "Giờ kết thúc",
  meeting_location: "Địa điểm",
  meeting_agenda_summary: "Nội dung tổng quát",
  meeting_agenda: "Chương trình họp",
  person_name: "Họ tên",
  person_role: "Vai trò",
  attendee_list: "Danh sách tham dự",
  discussion_summary: "Nội dung thảo luận",
  decision_list: "Kết luận, quyết định",
  action_item: "Phân công công việc",
  voting_total: "Tổng số biểu quyết",
  voting_approved_count: "Số tán thành",
  voting_approved_percent: "Tỷ lệ tán thành",
  voting_rejected_count: "Số không tán thành",
  voting_rejected_percent: "Tỷ lệ không tán thành",
  signature: "Chữ ký",
  party_dues: "Đảng phí",
  party_member_status: "Tình hình đảng viên",
  news_info: "Thông tin thời sự",
  resolution_evaluation: "Đánh giá nghị quyết",
  moral_study: "Học tập đạo đức",
  leadership_feedback: "Ý kiến cấp trên",
  custom: "Trường khác",
};

export function TemplateDetail() {
  const { id } = useParams(),
    user = useUser();
  const [tab, setTab] = useState("fields"),
    [fields, setFields] = useState<TemplateField[]>([]),
    [texts, setTexts] = useState<Record<number, string>>({}),
    [approved, setApproved] = useState(false);
  const { busy, work } = useWork();
  const data = useQuery({
    queryKey: ["template", id],
    queryFn: () => api<Template>("/templates/" + id),
    refetchInterval: 3000,
  });
  const jobs = useQuery({
    queryKey: ["template-jobs", id],
    queryFn: () => api<Job[]>("/jobs"),
    refetchInterval: 4000,
  });
  const t = data.data,
    v = t?.version;
  const own = t?.owner_id === user.id;
  const job = jobs.data?.find((j) => j.resource_id === id);
  useEffect(() => {
    if (v) {
      setFields(v.schema.fields);
      setTexts({});
      setApproved(false);
    }
  }, [v?.id]);
  if (data.isPending) return <Loading />;
  if (data.error) return <ErrorBox error={data.error} />;
  const patches =
    v?.paragraphs
      .filter((p) => texts[p.index] !== undefined && texts[p.index] !== p.text)
      .map((p) => ({ index: p.index, text: texts[p.index] })) || [];
  return (
    <>
      <Link className="breadcrumb" to="/templates">
        <ArrowLeft size={14} />
        Thư viện mẫu
      </Link>
      <PageHeader
        eyebrow="RÀ SOÁT MẪU"
        title={t!.name}
        description={`${t!.visibility === "shared" ? "Mẫu dùng chung" : "Mẫu riêng tư"} · Phiên bản ${t!.revision}`}
        action={<Status value={t!.active_job ? "running" : t!.state} />}
      />
      {t!.active_job && (
        <Notice tone="info">{job?.stage || "Mẫu đang được xử lý…"}</Notice>
      )}
      {job?.state === "failed" && !t!.active_job && (
        <Notice>
          {job.error?.message}
          <Action run={() => post("/jobs/" + job.id + "/retry")}>
            Thử lại
          </Action>
        </Notice>
      )}
      {v ? (
        <>
          {v.report.warnings?.map((warning, i) => (
            <Notice key={i}>{warning}</Notice>
          ))}
          {v.report.preview_error && <Notice>{v.report.preview_error}</Notice>}
          <div className="minutes-layout">
            <Panel title="Đề mục & trường điền">
              <div className="segmented-control">
                <button
                  className={tab === "fields" ? "active" : ""}
                  onClick={() => setTab("fields")}
                >
                  Trường dữ liệu ({fields.length})
                </button>
                <button
                  className={tab === "text" ? "active" : ""}
                  onClick={() => setTab("text")}
                >
                  Đối chiếu chữ / OCR
                </button>
              </div>
              {tab === "fields" ? (
                <div className="template-fields">
                  {fields.length ? (
                    fields.map((f, index) => (
                      <div className="template-field" key={f.field_id}>
                        <span className="field-section">
                          {f.section} · {f.field_id}
                        </span>
                        <strong>{f.raw_label}</strong>
                        <label>
                          Ý nghĩa trường
                          <select
                            aria-label={"Ý nghĩa " + f.field_id}
                            value={f.semantic_type}
                            disabled={!own || !!t!.active_job}
                            onChange={(e) =>
                              setFields(
                                fields.map((item, i) =>
                                  i === index
                                    ? { ...item, semantic_type: e.target.value }
                                    : item,
                                ),
                              )
                            }
                          >
                            {Object.entries(semanticLabels).map(
                              ([key, label]) => (
                                <option value={key} key={key}>
                                  {label}
                                </option>
                              ),
                            )}
                          </select>
                        </label>
                        <div className="row between">
                          <small className="muted">Vị trí: {f.anchor_id}</small>
                          {own && (
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={!!t!.active_job}
                              onClick={() =>
                                setFields(fields.filter((_, i) => i !== index))
                              }
                            >
                              Bỏ trường nhận nhầm
                            </Button>
                          )}
                        </div>
                      </div>
                    ))
                  ) : (
                    <Empty
                      title="Chưa nhận diện trường điền"
                      description="Trong mục Đối chiếu chữ/OCR, thêm dấu chấm (…) hoặc chỗ trống (____) tại vị trí cần điền rồi lưu để phân tích lại."
                    />
                  )}
                </div>
              ) : (
                <div className="ocr-text-list">
                  <Notice tone="info">
                    Đối chiếu với bản gốc. Chỉ sửa chữ nhận dạng sai hoặc bổ
                    sung dấu chấm/chỗ trống; giữ nguyên đề mục của mẫu. Nếu sửa
                    làm thay đổi vị trí trường, hãy lưu chữ trước rồi rà soát
                    trường ở phiên bản mới.
                  </Notice>
                  {v.paragraphs.map((p) => (
                    <label key={p.index}>
                      <small>Đoạn {p.index + 1}</small>
                      <Textarea
                        rows={Math.max(
                          2,
                          Math.min(
                            5,
                            Math.ceil((texts[p.index] ?? p.text).length / 70),
                          ),
                        )}
                        value={texts[p.index] ?? p.text}
                        disabled={!own || !!t!.active_job}
                        onChange={(e) =>
                          setTexts({ ...texts, [p.index]: e.target.value })
                        }
                        maxLength={12000}
                      />
                    </label>
                  ))}
                </div>
              )}
              {own && (
                <div className="review-footer">
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={approved}
                      disabled={!!t!.active_job || !!patches.length}
                      onChange={(e) => setApproved(e.target.checked)}
                    />
                    Tôi đã đối chiếu nội dung và các trường với bản gốc
                  </label>
                  <Button
                    disabled={
                      busy ||
                      !!t!.active_job ||
                      (!patches.length && !fields.length)
                    }
                    onClick={() =>
                      void work(
                        async () => {
                          await post("/templates/" + id + "/review", {
                            revision: t!.revision,
                            paragraphs: patches,
                            fields: patches.length ? [] : fields,
                            approved: approved && !patches.length,
                          });
                        },
                        patches.length
                          ? "Đã xếp hàng lưu chữ và nhận diện lại trường"
                          : "Đã xếp hàng cập nhật mẫu",
                      )
                    }
                  >
                    <Save size={16} />
                    {patches.length
                      ? "Lưu chữ & phân tích lại"
                      : approved
                        ? "Duyệt & lưu mẫu"
                        : "Lưu cấu hình trường"}
                  </Button>
                </div>
              )}
              <JsonDetails
                value={v.report}
                label="Báo cáo đọc tài liệu và OCR"
              />
              <div className="row wrap">
                <DownloadLink artifact={v.original} label="Tải bản gốc" />
                <DownloadLink
                  artifact={v.normalized}
                  label="Tải Word chuẩn hóa"
                />
              </div>
            </Panel>
            <div className="preview-column">
              <Preview pages={v.previews} download={v.normalized} />
              {v.original.media_type === "application/pdf" ? (
                <div className="panel">
                  <h3>PDF gốc để đối chiếu</h3>
                  <iframe
                    title="PDF mẫu gốc"
                    src={v.original.url}
                    className="pdf-original"
                  />
                </div>
              ) : v.original.media_type.startsWith("image/") ? (
                <div className="panel">
                  <h3>Ảnh scan gốc</h3>
                  <a href={v.original.url} target="_blank" rel="noreferrer">
                    <img
                      className="scan-original"
                      src={v.original.url}
                      alt="Ảnh scan mẫu gốc"
                    />
                  </a>
                </div>
              ) : null}
            </div>
          </div>
          {own && (
            <Action
              disabled={!!t!.active_job}
              run={() =>
                post("/templates/" + id + "/archive", {
                  revision: t!.revision,
                }).then(() => window.location.assign("/templates"))
              }
            >
              Lưu trữ mẫu
            </Action>
          )}
        </>
      ) : (
        <Panel>
          <Empty
            title="Đang chuẩn bị tài liệu"
            description="Worker sẽ chuẩn hóa, nhận diện trường và tạo bản xem trước."
          />
        </Panel>
      )}
    </>
  );
}

export function Voices() {
  const data = useQuery({
    queryKey: ["voices"],
    queryFn: () => api<Voice[]>("/speakers"),
    refetchInterval: 4000,
  });
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api<Job[]>("/jobs"),
    refetchInterval: 5000,
  });
  const [open, setOpen] = useState(false),
    [name, setName] = useState(""),
    [files, setFiles] = useState<File[]>([]),
    [adding, setAdding] = useState<Voice | null>(null);
  const { busy, work } = useWork();
  async function submit(e: FormEvent) {
    e.preventDefault();
    await work(async () => {
      const form = new FormData();
      files.forEach((f) => form.append("samples", f));
      if (adding) {
        form.append("revision", String(adding.revision));
        await post("/speakers/" + adding.id + "/samples", form);
      } else {
        form.append("name", name);
        await post("/speakers", form);
      }
      setOpen(false);
      setFiles([]);
      setAdding(null);
    }, "Đã xếp hàng tạo hồ sơ giọng");
  }
  return (
    <>
      <PageHeader
        eyebrow="NGƯỜI THAM GIA"
        title="Hồ sơ giọng nói"
        description="Mẫu giọng hỗ trợ nhận diện người tham gia. Kết quả vẫn cần được đối chiếu trong từng cuộc họp."
        action={
          <Button
            onClick={() => {
              setAdding(null);
              setFiles([]);
              setName("");
              setOpen(true);
            }}
          >
            <Plus size={16} />
            Tạo hồ sơ giọng
          </Button>
        }
      />
      <Notice tone="info">
        Chọn mẫu chỉ có một người nói, âm lượng rõ, ít nhiễu. Dùng nhiều mẫu ở
        các thời điểm khác nhau để cải thiện độ ổn định.
      </Notice>
      <ErrorBox error={data.error} />
      {data.isPending ? (
        <Loading />
      ) : data.data?.length ? (
        <div className="cards-grid">
          {data.data.map((v) => {
            const job = jobs.data?.find((j) => j.resource_id === v.id);
            return (
              <Panel key={v.id}>
                <div className="row between">
                  <span className="avatar large">{v.name[0]}</span>
                  <Status value={v.active_job ? "running" : v.state} />
                </div>
                <h2>{v.name}</h2>
                <p className="muted">
                  {v.samples.length} mẫu ·{" "}
                  {v.metadata?.total_speech_seconds?.toFixed(1) || "—"} giây
                  tiếng nói
                </p>
                {v.metadata?.warnings?.map((w, i) => (
                  <Notice key={i}>{w}</Notice>
                ))}
                {job?.state === "failed" && !v.active_job && (
                  <Notice>
                    {job.error?.message}
                    <Action run={() => post("/jobs/" + job.id + "/retry")}>
                      Thử lại
                    </Action>
                  </Notice>
                )}
                {v.samples.map((a) => (
                  <div className="voice-sample" key={a.id}>
                    <span>{a.name}</span>
                    <audio controls preload="none" src={a.url} />
                  </div>
                ))}
                <div className="row wrap">
                  <Button
                    variant="outline"
                    disabled={!!v.active_job || v.samples.length >= 8}
                    onClick={() => {
                      setAdding(v);
                      setFiles([]);
                      setOpen(true);
                    }}
                  >
                    <Plus size={15} />
                    Thêm mẫu
                  </Button>
                  <Action
                    variant="ghost"
                    disabled={!!v.active_job}
                    run={() =>
                      post("/speakers/" + v.id + "/archive", {
                        revision: v.revision,
                      })
                    }
                  >
                    Lưu trữ
                  </Action>
                </div>
              </Panel>
            );
          })}
        </div>
      ) : (
        <Panel>
          <Empty
            title="Chưa có hồ sơ giọng"
            description="Tạo hồ sơ cho người thường tham gia cuộc họp để hỗ trợ nhận diện."
            action={
              <Button onClick={() => setOpen(true)}>Tạo hồ sơ đầu tiên</Button>
            }
          />
        </Panel>
      )}
      <Modal
        open={open}
        onOpenChange={setOpen}
        title={adding ? "Thêm mẫu cho " + adding.name : "Hồ sơ giọng mới"}
      >
        <form onSubmit={submit} className="form-stack">
          {!adding && (
            <label>
              Tên người tham gia
              <Input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={200}
              />
            </label>
          )}
          <label className="upload-zone compact">
            <AudioLines size={28} />
            <strong>Chọn mẫu giọng</strong>
            <small>Tổng cộng tối đa 8 mẫu cho mỗi người</small>
            <input
              type="file"
              required
              multiple
              accept=".wav,.mp3,.m4a,.aac,.flac,.ogg,.webm,.mp4"
              onChange={(e) => setFiles(Array.from(e.target.files || []))}
            />
          </label>
          {files.map((f, i) => (
            <p key={i} className="small">
              {f.name} · {size(f.size)}
            </p>
          ))}
          <Button
            disabled={
              busy ||
              !files.length ||
              files.length + (adding?.samples.length || 0) > 8 ||
              (!adding && !name.trim())
            }
            type="submit"
          >
            {busy ? "Đang tải…" : "Tải lên & tạo embedding"}
          </Button>
        </form>
      </Modal>
    </>
  );
}
