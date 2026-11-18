import { useListPage } from "@/lib/pagination";
import { useUser } from "@/app";
import {
  Action,
  DownloadLink,
  Empty,
  ErrorBox,
  FilterBar,
  FormField,
  JsonDetails,
  Loading,
  Modal,
  Notice,
  PageHeader,
  Panel,
  Pagination,
  Preview,
  Status,
  useWork,
} from "@/components/common";
import { NotFoundState } from "@/features/auth/pages";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiError,
  api,
  formatDate,
  formatMeetingDate,
  post,
  size,
} from "@/lib/api";
import { useUnsavedForm } from "@/lib/unsaved";
import type {
  PaginatedResponse,
  Capabilities,
  Job,
  Template,
  TemplateField,
  Voice,
  VoiceDetail,
} from "@/lib/types";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
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
import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Link,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

export function Templates({ sharedOnly = false }: { sharedOnly?: boolean }) {
  const user = useUser();
  const location = useLocation();
  const isAdminRoute =
    sharedOnly || location.pathname.startsWith("/admin/templates");
  const basePath = isAdminRoute ? "/admin/templates" : "/templates";

  const [searchParams, setSearchParams] = useSearchParams();
  const paging = useListPage();
  const qParam = searchParams.get("q") || "";
  const visParam =
    searchParams.get("visibility") || (sharedOnly ? "shared" : "all");
  const stateParam = searchParams.get("state") || "all";

  const [draftQuery, setDraftQuery] = useState(qParam);

  function updateParams(updates: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams);
    for (const [k, v] of Object.entries(updates)) {
      if (!v || v === "all") next.delete(k);
      else next.set(k, v);
    }
    next.delete("page");
    setSearchParams(next);
  }

  const data = useQuery({
    queryKey: ["templates", "list", searchParams.toString(), sharedOnly],
    queryFn: () =>
      api<PaginatedResponse<Template>>(
        "/templates?" +
          new URLSearchParams({
            ...Object.fromEntries(searchParams),
            visibility: visParam,
            page: String(paging.page),
            limit: String(paging.limit),
          }),
      ),
    placeholderData: keepPreviousData,
    refetchInterval: 4000,
  });

  const filtered = useMemo(() => {
    const all = (data.data?.items || []).filter(
      (t) => !sharedOnly || t.visibility === "shared",
    );
    const q = qParam.trim().toLocaleLowerCase("vi");
    return all.filter((t) => {
      if (visParam !== "all" && t.visibility !== visParam) return false;
      if (stateParam === "needs_review" && !t.needs_review) return false;
      if (
        stateParam === "ready" &&
        (t.state !== "ready" || t.needs_review || Boolean(t.active_job))
      )
        return false;
      if (stateParam === "processing" && !t.active_job && t.state !== "pending")
        return false;
      if (!q) return true;
      return t.name.toLocaleLowerCase("vi").includes(q);
    });
  }, [data.data, sharedOnly, qParam, visParam, stateParam]);

  const hasFilters =
    Boolean(qParam.trim()) ||
    (!sharedOnly && visParam !== "all") ||
    stateParam !== "all";

  return (
    <div className="page-container--list">
      <PageHeader
        eyebrow={isAdminRoute ? "QUẢN TRỊ" : "TÀI NGUYÊN"}
        title={isAdminRoute ? "Mẫu dùng chung" : "Thư viện mẫu biên bản"}
        description="Mẫu Word (.docx), PDF hoặc ảnh scan được chuẩn hóa thành tài liệu Word có cấu trúc trường thông tin."
        action={
          <Button asChild>
            <Link to={`${basePath}/new`}>
              <Plus size={16} />
              Nhập mẫu
            </Link>
          </Button>
        }
      />

      <FilterBar
        searchValue={draftQuery}
        onSearchChange={(val) => {
          setDraftQuery(val);
          updateParams({ q: val.trim() || null });
        }}
        searchPlaceholder="Tìm theo tên mẫu biên bản…"
        searchLabel="Tìm kiếm mẫu biên bản"
        hasActiveFilters={hasFilters}
        onReset={() => {
          setDraftQuery("");
          setSearchParams(new URLSearchParams());
        }}
        filters={
          <>
            {!sharedOnly && (
              <div
                className="minda-filter-pills"
                role="group"
                aria-label="Phạm vi mẫu"
              >
                {[
                  { id: "all", label: "Tất cả" },
                  { id: "private", label: "Cá nhân" },
                  { id: "shared", label: "Dùng chung" },
                ].map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    className={
                      "minda-filter-pill" +
                      (visParam === opt.id ? " active" : "")
                    }
                    onClick={() => updateParams({ visibility: opt.id })}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}
            <select
              aria-label="Trạng thái mẫu"
              value={stateParam}
              onChange={(e) => updateParams({ state: e.target.value })}
              style={{ width: "auto", minWidth: 160 }}
            >
              <option value="all">Mọi trạng thái</option>
              <option value="ready">Sẵn sàng sử dụng</option>
              <option value="needs_review">Cần duyệt</option>
              <option value="processing">Đang xử lý</option>
            </select>
          </>
        }
        summary={data.data ? `${filtered.length} mẫu` : undefined}
      />

      <ErrorBox
        error={data.error as Error | null}
        onRetry={() => void data.refetch()}
      />

      {data.isPending ? (
        <Loading label="Đang tải danh sách mẫu biên bản…" />
      ) : filtered.length ? (
        <div className="cards-grid">
          {filtered.map((t) => (
            <Panel key={t.id} className="template-card">
              <div className="row between">
                <span className="template-icon">
                  <FileText size={24} />
                </span>
                <Status
                  value={
                    t.active_job
                      ? "running"
                      : t.needs_review
                        ? "needs_review"
                        : t.state
                  }
                />
              </div>
              <h2>
                <Link to={`${basePath}/${t.id}`}>{t.name}</Link>
              </h2>
              <p className="muted">
                {t.visibility === "shared" ? (
                  <Globe2 size={14} />
                ) : (
                  <LockKeyhole size={14} />
                )}{" "}
                {t.visibility === "shared" ? "Dùng chung" : "Cá nhân"} ·{" "}
                {t.field_count ?? t.version?.schema?.fields?.length ?? 0} trường
                dữ liệu
              </p>
              {t.needs_review ? (
                <Notice>
                  {t.owner_id === user.id
                    ? "Cần đối chiếu và duyệt trước khi sử dụng."
                    : "Mẫu dùng chung đang chờ quản trị viên duyệt."}
                </Notice>
              ) : (
                <span className="small green-text">
                  <Check size={14} />
                  Mẫu sẵn sàng sử dụng
                </span>
              )}
              <Link className="panel-link" to={`${basePath}/${t.id}`}>
                Mở & rà soát mẫu
                <ArrowUpRight size={16} />
              </Link>
            </Panel>
          ))}
        </div>
      ) : hasFilters ? (
        <Panel>
          <Empty
            title="Không tìm thấy mẫu biên bản phù hợp"
            description="Thử xóa bộ lọc hoặc đổi từ khóa tìm kiếm."
            action={
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setDraftQuery("");
                  setSearchParams(new URLSearchParams());
                }}
              >
                Xóa bộ lọc
              </Button>
            }
          />
        </Panel>
      ) : (
        <Panel>
          <Empty
            title="Chưa có mẫu biên bản nào"
            description="DOC/DOCX giữ cấu trúc sẵn có. PDF và ảnh scan được nhận diện OCR, sau đó bạn duyệt lại trước khi dùng."
            action={
              <Button asChild>
                <Link to={`${basePath}/new`}>
                  <UploadCloud size={16} />
                  Nhập mẫu đầu tiên
                </Link>
              </Button>
            }
          />
        </Panel>
      )}
      <Pagination
        page={paging.page}
        limit={paging.limit}
        total={data.data?.total || 0}
        onPageChange={(next) => paging.update("page", String(next))}
      />
    </div>
  );
}

export function TemplateNewPage({
  sharedOnly = false,
}: {
  sharedOnly?: boolean;
}) {
  const user = useUser();
  const navigate = useNavigate();
  const location = useLocation();
  const isAdminRoute =
    sharedOnly || location.pathname.startsWith("/admin/templates");
  const basePath = isAdminRoute ? "/admin/templates" : "/templates";

  const [name, setName] = useState("");
  const [visibility, setVisibility] = useState(
    isAdminRoute && user.role === "admin" ? "shared" : "private",
  );
  const [file, setFile] = useState<File | null>(null);
  const { busy, work } = useWork();

  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<Capabilities>("/capabilities"),
  });

  const dirty = Boolean(name.trim() || file);
  const unsaved = useUnsavedForm(dirty && !busy);

  const maxUploadText = capabilities.data?.max_upload_bytes
    ? size(capabilities.data.max_upload_bytes)
    : "500 MB";

  return (
    <div className="page-container--form">
      {unsaved.dialog}
      <Link className="breadcrumb" to={basePath}>
        <ArrowLeft size={14} />
        {isAdminRoute ? "Mẫu dùng chung" : "Mẫu biên bản"}
      </Link>
      <PageHeader
        eyebrow={isAdminRoute ? "QUẢN TRỊ · NHẬP MẪU" : "TÀI NGUYÊN · NHẬP MẪU"}
        title="Nhập mẫu biên bản mới"
        description="Tải lên mẫu biên bản từ file Word, PDF hoặc ảnh scan. Hệ thống sẽ trích xuất đề mục, nhận diện các trường cần điền và tạo bản xem trước."
      />

      <Panel
        title="Thông tin mẫu & Tệp tải lên"
        description={`Định dạng hỗ trợ: .doc, .docx, .pdf, .png, .jpg, .jpeg, .tif, .tiff · Dung lượng tối đa: ${maxUploadText}.`}
      >
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault();
            if (!file || !name.trim()) return;
            void work(async () => {
              const form = new FormData();
              form.append("name", name.trim());
              form.append("visibility", visibility);
              form.append("file", file);
              const result = await post<{ template_id: string }>(
                "/templates",
                form,
              );
              unsaved.allowNavigation();
              navigate(`${basePath}/${result.template_id}`);
            }, "Đã xếp hàng đọc và chuẩn hóa mẫu");
          }}
        >
          <FormField
            label="Tên mẫu biên bản"
            required
            hint="Đặt tên rõ ràng theo loại cuộc họp hoặc thể thức của đơn vị."
          >
            <Input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
              placeholder="Ví dụ: Mẫu biên bản họp giao ban tuần (NĐ 30/2020)"
            />
          </FormField>

          {user.role === "admin" && (
            <FormField
              label="Phạm vi sử dụng"
              hint="Mẫu dùng chung sẽ hiển thị cho tất cả người dùng sau khi được duyệt."
            >
              <select
                value={visibility}
                onChange={(e) => setVisibility(e.target.value)}
              >
                <option value="private">Cá nhân (Chỉ mình tôi)</option>
                <option value="shared">Dùng chung cho toàn đơn vị</option>
              </select>
            </FormField>
          )}

          <FormField
            label="Tệp mẫu biên bản"
            required
            hint="Bản gốc luôn được lưu giữ để đối chiếu song song với bản Word chuẩn hóa."
          >
            <label className="upload-zone compact">
              <UploadCloud size={26} />
              <strong>
                {file
                  ? `${file.name} (${size(file.size)})`
                  : "Chọn file mẫu từ máy tính"}
              </strong>
              <small className="muted">
                Chấp nhận DOC, DOCX, PDF, PNG, JPG, TIFF
              </small>
              <input
                type="file"
                required
                accept=".doc,.docx,.pdf,.png,.jpg,.jpeg,.tif,.tiff"
                onChange={(e) => {
                  const chosen = e.target.files?.[0] || null;
                  setFile(chosen);
                  if (chosen && !name.trim()) {
                    setName(chosen.name.replace(/\.[^.]+$/, ""));
                  }
                }}
              />
            </label>
          </FormField>

          <div className="row between" style={{ marginTop: 8 }}>
            <Button asChild variant="outline" type="button">
              <Link to={basePath}>Hủy</Link>
            </Button>
            <Button type="submit" disabled={busy || !file || !name.trim()}>
              <UploadCloud size={16} />
              {busy ? "Đang tải lên…" : "Tải lên & Phân tích mẫu"}
            </Button>
          </div>
        </form>
      </Panel>
    </div>
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
  const { id } = useParams();
  const user = useUser();
  const location = useLocation();
  const navigate = useNavigate();
  const isAdminRoute = location.pathname.startsWith("/admin/templates");
  const basePath = isAdminRoute ? "/admin/templates" : "/templates";

  const [tab, setTab] = useState("fields");
  const [fields, setFields] = useState<TemplateField[]>([]);
  const [texts, setTexts] = useState<Record<number, string>>({});
  const [approved, setApproved] = useState(false);
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

  const t = data.data;
  const v = t?.version;
  const own = t?.owner_id === user.id;
  const job = jobs.data?.find((j) => j.resource_id === id);

  useEffect(() => {
    if (v) {
      setFields(v.schema.fields);
      setTexts({});
      setApproved(false);
    }
  }, [v?.id]);

  const patches = useMemo(
    () =>
      v?.paragraphs
        .filter(
          (p) => texts[p.index] !== undefined && texts[p.index] !== p.text,
        )
        .map((p) => ({ index: p.index, text: texts[p.index] })) || [],
    [v?.paragraphs, texts],
  );

  const fieldsDirty = useMemo(() => {
    if (!v) return false;
    return JSON.stringify(fields) !== JSON.stringify(v.schema.fields);
  }, [v, fields]);

  const isDirty = fieldsDirty || patches.length > 0;
  const unsaved = useUnsavedForm(isDirty && !busy);

  if (data.isPending)
    return <Loading label="Đang tải chi tiết mẫu biên bản…" />;
  if (data.error) {
    if (data.error instanceof ApiError && data.error.status === 404) {
      return (
        <NotFoundState
          title="Không tìm thấy mẫu biên bản"
          description="Mẫu biên bản này không tồn tại, đã được lưu trữ hoặc không thuộc quyền truy cập của bạn."
          backTo={basePath}
          backLabel={isAdminRoute ? "Về mẫu dùng chung" : "Về thư viện mẫu"}
        />
      );
    }
    return (
      <ErrorBox
        error={data.error as Error}
        onRetry={() => void data.refetch()}
      />
    );
  }

  return (
    <div className="page-container--list">
      {unsaved.dialog}
      <Link className="breadcrumb" to={basePath}>
        <ArrowLeft size={14} />
        {isAdminRoute ? "Mẫu dùng chung" : "Thư viện mẫu"}
      </Link>
      <PageHeader
        eyebrow="RÀ SOÁT MẪU"
        title={t!.name}
        description={`${t!.visibility === "shared" ? "Mẫu dùng chung" : "Mẫu cá nhân"} · Phiên bản ${t!.revision}`}
        action={
          <div className="row wrap">
            {isDirty && (
              <span className="status-badge warn">Có thay đổi chưa lưu</span>
            )}
            <Status
              value={
                t!.active_job
                  ? "running"
                  : t!.needs_review
                    ? "needs_review"
                    : t!.state
              }
            />
          </div>
        }
      />
      {t!.active_job && (
        <Notice tone="info">{job?.stage || "Mẫu đang được xử lý…"}</Notice>
      )}
      {job?.state === "failed" && !t!.active_job && (
        <Notice tone="danger">
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
                  type="button"
                  className={tab === "fields" ? "active" : ""}
                  onClick={() => setTab("fields")}
                >
                  Trường dữ liệu ({fields.length})
                </button>
                <button
                  type="button"
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
                              type="button"
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
                  <div className="row wrap">
                    {isDirty && (
                      <Button
                        type="button"
                        variant="outline"
                        disabled={busy || !!t!.active_job}
                        onClick={() => {
                          setFields(v.schema.fields);
                          setTexts({});
                          setApproved(false);
                        }}
                      >
                        Hoàn tác nháp
                      </Button>
                    )}
                    <Button
                      type="button"
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
                            setTexts({});
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
              run={async () => {
                await post("/templates/" + id + "/archive", {
                  revision: t!.revision,
                });
                unsaved.allowNavigation();
                navigate(basePath);
              }}
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
    </div>
  );
}

export function Voices() {
  const [searchParams, setSearchParams] = useSearchParams();
  const paging = useListPage();
  const qParam = searchParams.get("q") || "";
  const [draftQuery, setDraftQuery] = useState(qParam);

  const data = useQuery({
    queryKey: ["voices", "list", searchParams.toString()],
    queryFn: () =>
      api<PaginatedResponse<Voice>>(
        "/speakers?" +
          new URLSearchParams({
            ...Object.fromEntries(searchParams),
            page: String(paging.page),
            limit: String(paging.limit),
          }),
      ),
    placeholderData: keepPreviousData,
    refetchInterval: 4000,
  });
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api<Job[]>("/jobs"),
    refetchInterval: 5000,
  });
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [adding, setAdding] = useState<Voice | null>(null);
  const { busy, work } = useWork();

  const filtered = useMemo(() => {
    const all = data.data?.items || [];
    const q = qParam.trim().toLocaleLowerCase("vi");
    if (!q) return all;
    return all.filter((v) => v.name.toLocaleLowerCase("vi").includes(q));
  }, [data.data, qParam]);

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
    <div className="page-container--list">
      <PageHeader
        eyebrow="TÀI NGUYÊN"
        title="Hồ sơ giọng nói"
        description="Mẫu giọng hỗ trợ nhận diện người tham gia trong cuộc họp. Kết quả vẫn cần được đối chiếu trong từng cuộc họp."
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

      <FilterBar
        searchValue={draftQuery}
        onSearchChange={(val) => {
          setDraftQuery(val);
          const next = new URLSearchParams(searchParams);
          if (val.trim()) next.set("q", val.trim());
          else next.delete("q");
          next.delete("page");
          setSearchParams(next);
        }}
        searchPlaceholder="Tìm theo tên người tham gia…"
        searchLabel="Tìm kiếm hồ sơ giọng"
        hasActiveFilters={Boolean(qParam.trim())}
        onReset={() => {
          setDraftQuery("");
          setSearchParams(new URLSearchParams());
        }}
        summary={data.data ? `${filtered.length} hồ sơ giọng` : undefined}
      />

      <ErrorBox
        error={data.error as Error | null}
        onRetry={() => void data.refetch()}
      />
      {data.isPending ? (
        <Loading label="Đang tải danh sách hồ sơ giọng…" />
      ) : filtered.length ? (
        <div className="cards-grid">
          {filtered.map((v) => {
            const job = jobs.data?.find((j) => j.resource_id === v.id);
            return (
              <Panel key={v.id}>
                <div className="row between">
                  <span className="avatar large">{v.name[0]}</span>
                  <Status value={v.active_job ? "running" : v.state} />
                </div>
                <h2>
                  <Link to={`/voices/${v.id}`}>{v.name}</Link>
                </h2>
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
                {v.samples.slice(0, 2).map((a) => (
                  <div className="voice-sample" key={a.id}>
                    <span>{a.name}</span>
                    <audio controls preload="none" src={a.url} />
                  </div>
                ))}
                <div className="row wrap" style={{ marginTop: 8 }}>
                  <Button asChild variant="outline" size="sm">
                    <Link to={`/voices/${v.id}`}>
                      Chi tiết hồ sơ
                      <ArrowUpRight size={14} />
                    </Link>
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
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
            title={
              qParam.trim()
                ? "Không tìm thấy hồ sơ giọng phù hợp"
                : "Chưa có hồ sơ giọng"
            }
            description={
              qParam.trim()
                ? "Hãy thử từ khóa khác hoặc xóa bộ lọc tìm kiếm."
                : "Tạo hồ sơ cho người thường tham gia cuộc họp để hỗ trợ nhận diện."
            }
            action={
              qParam.trim() ? (
                <Button
                  variant="outline"
                  onClick={() => {
                    setDraftQuery("");
                    setSearchParams(new URLSearchParams());
                  }}
                >
                  Xóa bộ lọc
                </Button>
              ) : (
                <Button onClick={() => setOpen(true)}>
                  Tạo hồ sơ đầu tiên
                </Button>
              )
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
      <Pagination
        page={paging.page}
        limit={paging.limit}
        total={data.data?.total || 0}
        onPageChange={(next) => paging.update("page", String(next))}
      />
    </div>
  );
}

export function VoiceDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [openAdd, setOpenAdd] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const { busy, work } = useWork();

  const detail = useQuery({
    queryKey: ["voice", id],
    queryFn: () => api<VoiceDetail>(`/speakers/${id}`),
    refetchInterval: 4000,
  });

  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api<Job[]>("/jobs"),
    refetchInterval: 5000,
  });

  if (detail.isPending) {
    return <Loading label="Đang tải chi tiết hồ sơ giọng…" />;
  }
  if (detail.error) {
    if (detail.error instanceof ApiError && detail.error.status === 404) {
      return (
        <NotFoundState
          title="Không tìm thấy hồ sơ giọng"
          description="Hồ sơ giọng này không tồn tại, đã được lưu trữ hoặc không thuộc quyền sở hữu của bạn."
          backTo="/voices"
          backLabel="Về danh sách hồ sơ giọng"
        />
      );
    }
    return (
      <ErrorBox
        error={detail.error as Error}
        onRetry={() => void detail.refetch()}
      />
    );
  }

  const v = detail.data!;
  const job = jobs.data?.find((j) => j.resource_id === v.id);
  const activeMeetings = v.meetings || [];

  return (
    <div className="page-container--form">
      <Link className="breadcrumb" to="/voices">
        <ArrowLeft size={14} />
        Hồ sơ giọng nói
      </Link>
      <PageHeader
        eyebrow="CHI TIẾT HỒ SƠ GIỌNG"
        title={v.name}
        description={`Phiên bản ${v.revision} · ${v.samples.length}/8 mẫu âm thanh · Thời lượng tiếng nói: ${v.metadata?.total_speech_seconds?.toFixed(1) || "—"} giây`}
        action={
          <div className="row wrap">
            <Status value={v.active_job ? "running" : v.state} />
            <Button
              type="button"
              disabled={!!v.active_job || v.samples.length >= 8}
              onClick={() => {
                setFiles([]);
                setOpenAdd(true);
              }}
            >
              <Plus size={16} />
              Thêm mẫu giọng
            </Button>
          </div>
        }
      />

      {v.active_job && (
        <Notice tone="info">
          {job?.stage || "Hệ thống đang trích xuất đặc trưng giọng nói…"}
        </Notice>
      )}

      {job?.state === "failed" && !v.active_job && (
        <Notice tone="danger">
          {job.error?.message}
          <Action run={() => post(`/jobs/${job.id}/retry`)}>Thử lại</Action>
        </Notice>
      )}

      {v.metadata?.warnings?.map((w, i) => (
        <Notice key={i} tone="warning">
          {w}
        </Notice>
      ))}

      <Panel
        title={`Danh sách mẫu âm thanh (${v.samples.length}/8)`}
        description="Nghe lại từng mẫu giọng đã đăng ký cho hồ sơ này."
      >
        {v.samples.length ? (
          <div className="stack">
            {v.samples.map((sample, idx) => (
              <div
                key={sample.id}
                className="voice-sample"
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 16,
                  padding: "12px 16px",
                  borderRadius: "var(--minda-radius-surface)",
                  border: "1px solid var(--minda-border)",
                  background: "var(--minda-canvas)",
                  flexWrap: "wrap",
                }}
              >
                <div>
                  <strong>
                    Mẫu #{idx + 1}: {sample.name}
                  </strong>
                  <div>
                    <small className="muted">
                      Dung lượng: {size(sample.size_bytes)}
                    </small>
                  </div>
                </div>
                <div className="row wrap">
                  <audio controls preload="none" src={sample.url} />
                  <DownloadLink artifact={sample} label="Tải mẫu" />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty
            title="Chưa có mẫu âm thanh"
            description="Hãy thêm mẫu âm thanh cho hồ sơ này."
          />
        )}
      </Panel>

      <Panel
        title="Cuộc họp đang gắn hồ sơ này"
        description="Các cuộc họp có chọn hồ sơ giọng này trong danh sách người tham dự."
      >
        {activeMeetings.length ? (
          <div className="stack">
            {activeMeetings.map((m) => (
              <div
                key={m.id}
                className="row between wrap"
                style={{
                  padding: "10px 14px",
                  borderRadius: "var(--minda-radius-control)",
                  border: "1px solid var(--minda-border)",
                }}
              >
                <div>
                  <Link to={`/meetings/${m.id}`} style={{ fontWeight: 600 }}>
                    {m.title}
                  </Link>
                  <div>
                    <small className="muted">
                      Ngày họp: {formatMeetingDate(m.date)} · Cập nhật:{" "}
                      {formatDate(m.updated_at)}
                    </small>
                  </div>
                </div>
                <Status value={m.state} />
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">
            Hiện chưa có cuộc họp đang hoạt động nào sử dụng hồ sơ giọng này.
          </p>
        )}
      </Panel>

      <Panel
        title="Lưu trữ hồ sơ giọng"
        description="Ẩn hồ sơ khỏi danh sách lựa chọn khi tạo cuộc họp mới."
      >
        {activeMeetings.length > 0 && (
          <Notice tone="warning">
            Hồ sơ này đang được chọn trong {activeMeetings.length} cuộc họp.
            Theo quy tắc toàn vẹn dữ liệu, bạn cần bỏ chọn hồ sơ khỏi các cuộc
            họp đó trước khi lưu trữ.
          </Notice>
        )}
        <Action
          variant="destructive"
          disabled={!!v.active_job || activeMeetings.length > 0}
          message="Đã lưu trữ hồ sơ giọng"
          run={async () => {
            await post(`/speakers/${v.id}/archive`, { revision: v.revision });
            navigate("/voices");
          }}
        >
          Lưu trữ hồ sơ giọng
        </Action>
      </Panel>

      <Modal
        open={openAdd}
        onOpenChange={setOpenAdd}
        title={`Thêm mẫu giọng cho ${v.name}`}
      >
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault();
            void work(async () => {
              const form = new FormData();
              form.append("revision", String(v.revision));
              files.forEach((f) => form.append("samples", f));
              await post(`/speakers/${v.id}/samples`, form);
              setOpenAdd(false);
              setFiles([]);
            }, "Đã xếp hàng cập nhật mẫu giọng");
          }}
        >
          <label className="upload-zone compact">
            <AudioLines size={28} />
            <strong>Chọn thêm mẫu giọng</strong>
            <small>
              Còn có thể thêm tối đa {Math.max(0, 8 - v.samples.length)} mẫu
            </small>
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
            type="submit"
            disabled={
              busy || !files.length || files.length + v.samples.length > 8
            }
          >
            {busy ? "Đang tải…" : "Tải lên & cập nhật hồ sơ"}
          </Button>
        </form>
      </Modal>
    </div>
  );
}
