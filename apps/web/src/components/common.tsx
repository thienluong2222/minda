import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ApiError, labels } from "@/lib/api";
import type { Artifact } from "@/lib/types";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  Info,
  LoaderCircle,
  Minus,
  Plus,
  RotateCcw,
  Search,
  X,
} from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useClampPage } from "@/lib/pagination";
import { toast } from "sonner";
import { showInformationalNotifications } from "@/config/presentation";

export function useWork() {
  const [busy, setBusy] = useState(false);
  const query = useQueryClient();
  async function work<T>(
    operation: () => Promise<T>,
    message = "Đã lưu thay đổi",
  ): Promise<T | undefined> {
    setBusy(true);
    try {
      const result = await operation();
      await query.invalidateQueries();
      if (message && showInformationalNotifications) toast.success(message);
      return result;
    } catch (error) {
      const e = error as Error;
      toast.error(e.message);
      return undefined;
    } finally {
      setBusy(false);
    }
  }
  return { busy, work };
}

export function Action({
  run,
  children,
  variant = "outline",
  disabled = false,
  className = "",
  message = "Đã gửi yêu cầu",
}: {
  run: () => Promise<unknown>;
  children: ReactNode;
  variant?: "default" | "outline" | "ghost" | "destructive" | "secondary";
  disabled?: boolean;
  className?: string;
  message?: string;
}) {
  const { busy, work } = useWork();
  return (
    <Button
      className={className}
      variant={variant}
      disabled={disabled || busy}
      onClick={() => void work(run, message)}
    >
      {busy ? <LoaderCircle className="animate-spin" size={16} /> : null}
      {children}
    </Button>
  );
}

export function Status({ value }: { value: string }) {
  return (
    <span className={`status status-${value} status-badge ${value}`}>
      <i aria-hidden="true" />
      {labels[value] || value}
    </span>
  );
}

export const StatusBadge = Status;

export function PageHeader({
  eyebrow,
  title,
  description,
  meta,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  meta?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading minda-page-header">
      <div className="minda-page-header-main">
        {eyebrow &&
          eyebrow.toLocaleLowerCase("vi") !== title.toLocaleLowerCase("vi") && (
            <p className="eyebrow">{eyebrow}</p>
          )}
        <h1>{title}</h1>
        {description && (
          <p className="muted minda-page-header-subtitle">{description}</p>
        )}
        {meta && <div className="minda-page-header-meta">{meta}</div>}
      </div>
      {action && <div className="minda-page-header-actions">{action}</div>}
    </div>
  );
}

export function SectionHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="minda-section-header">
      <div>
        <h2>{title}</h2>
        {description && <p className="muted small">{description}</p>}
      </div>
      {action && <div className="row wrap">{action}</div>}
    </div>
  );
}

export function Panel({
  id,
  title,
  description,
  action,
  children,
  className = "",
}: {
  id?: string;
  title?: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={`panel ${className}`}>
      {(title || action) && (
        <header className="panel-header minda-section-header">
          <div>
            {title && <h2>{title}</h2>}
            {description && <p className="muted">{description}</p>}
          </div>
          {action && <div className="row wrap">{action}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Toolbar({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`minda-toolbar ${className}`}>{children}</div>;
}

export function FilterBar({
  searchValue,
  onSearchChange,
  searchPlaceholder = "Tìm kiếm…",
  searchLabel = "Tìm kiếm",
  filters,
  onReset,
  hasActiveFilters = false,
  summary,
  actions,
}: {
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  searchPlaceholder?: string;
  searchLabel?: string;
  filters?: ReactNode;
  onReset?: () => void;
  hasActiveFilters?: boolean;
  summary?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="minda-toolbar">
      <div className="minda-filter-group">
        {onSearchChange !== undefined && (
          <label className="minda-search-box" aria-label={searchLabel}>
            <Search size={16} className="muted" aria-hidden="true" />
            <input
              type="search"
              value={searchValue || ""}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder={searchPlaceholder}
              aria-label={searchLabel}
            />
            {searchValue ? (
              <button
                type="button"
                className="icon-btn btn-compact"
                style={{
                  width: 24,
                  minWidth: 24,
                  height: 24,
                  minHeight: 24,
                  border: 0,
                }}
                aria-label="Xóa từ khóa tìm kiếm"
                onClick={() => onSearchChange("")}
              >
                <X size={14} />
              </button>
            ) : null}
          </label>
        )}
        {filters}
        {hasActiveFilters && onReset && (
          <Button type="button" variant="ghost" size="sm" onClick={onReset}>
            <RotateCcw size={14} />
            Xóa bộ lọc
          </Button>
        )}
      </div>
      {(summary || actions) && (
        <div className="row wrap">
          {summary && <span className="muted small">{summary}</span>}
          {actions}
        </div>
      )}
    </div>
  );
}

export function Pagination({
  page,
  limit,
  total,
  onPageChange,
  onLimitChange,
}: {
  page: number;
  limit: number;
  total: number;
  onPageChange: (nextPage: number) => void;
  onLimitChange?: (limit: number) => void;
}) {
  const [, setParams] = useSearchParams();
  useClampPage(total > 0 ? total : undefined, page, limit);
  const sizeSelect = (
    <label className="pagination-size">
      Mục / trang
      <select
        aria-label="Số mục mỗi trang"
        value={limit}
        onChange={(event) => {
          const nextLimit = Number(event.target.value);
          if (onLimitChange) onLimitChange(nextLimit);
          else
            setParams((previous) => {
              const next = new URLSearchParams(previous);
              next.set("limit", String(nextLimit));
              next.delete("page");
              return next;
            });
        }}
      >
        {[10, 20, 50].includes(limit) ? null : (
          <option value={limit}>{limit}</option>
        )}
        {[10, 20, 50].map((size) => (
          <option key={size} value={size}>
            {size}
          </option>
        ))}
      </select>
    </label>
  );
  const totalPages = Math.max(1, Math.ceil(total / Math.max(1, limit)));
  const start = total === 0 ? 0 : (page - 1) * limit + 1;
  const end = Math.min(total, page * limit);
  if (total <= limit && page <= 1) {
    return total > 0 ? (
      <div className="minda-pagination">
        <span>Hiển thị {total} mục</span>
        {sizeSelect}
      </div>
    ) : null;
  }
  return (
    <nav className="minda-pagination" aria-label="Phân trang danh sách">
      {sizeSelect}
      <span>
        Hiển thị {start}–{end} trong tổng số {total} mục (Trang {page}/
        {totalPages})
      </span>
      <div className="minda-pagination-controls">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <ChevronLeft size={16} />
          Trang trước
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          Trang sau
          <ChevronRight size={16} />
        </Button>
      </div>
    </nav>
  );
}

export function DataTable({
  label,
  headers,
  children,
  empty,
  isEmpty = false,
}: {
  label: string;
  headers: ReactNode[];
  children: ReactNode;
  empty?: ReactNode;
  isEmpty?: boolean;
}) {
  if (isEmpty && empty) return <>{empty}</>;
  return (
    <div className="minda-table-wrap" role="region" aria-label={label}>
      <table className="minda-table">
        <thead>
          <tr>
            {headers.map((header, i) => (
              <th key={i} scope="col">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function RowActions({ children }: { children: ReactNode }) {
  return <div className="minda-row-actions">{children}</div>;
}

export function FormField({
  label,
  required = false,
  hint,
  error,
  children,
}: {
  label: ReactNode;
  required?: boolean;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="minda-field">
      <label className="minda-field">
        <span
          className="minda-field-label"
          data-required={required ? "true" : undefined}
        >
          {label}
        </span>
        {children}
      </label>
      {hint && !error && <span className="minda-field-hint">{hint}</span>}
      {error && (
        <span className="minda-field-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export function Empty({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty empty-box">
      <FileText size={28} aria-hidden="true" />
      <h3>{title}</h3>
      {description && <p className="muted">{description}</p>}
      {action}
    </div>
  );
}

export const EmptyState = Empty;

export function Loading({ label = "Đang tải dữ liệu…" }: { label?: string }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <LoaderCircle className="animate-spin" aria-hidden="true" />
      {label}
    </div>
  );
}

export const Skeleton = Loading;

export function ErrorBox({
  error,
  onRetry,
}: {
  error: Error | null;
  onRetry?: () => void;
}) {
  if (!error) return null;
  const apiErr = error instanceof ApiError ? error : null;
  return (
    <div className="notice danger" role="alert">
      <div className="row" style={{ alignItems: "flex-start", gap: 10 }}>
        <AlertCircle size={18} style={{ flexShrink: 0, marginTop: 2 }} />
        <div>
          <strong>Không thể hoàn tất thao tác</strong>
          <p>{error.message}</p>
          {apiErr?.requestId && (
            <small className="muted">Mã yêu cầu: {apiErr.requestId}</small>
          )}
        </div>
      </div>
      {onRetry && (
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          <RotateCcw size={14} />
          Thử lại
        </Button>
      )}
    </div>
  );
}

export const ErrorState = ErrorBox;

export function Notice({
  children,
  tone = "warning",
  action,
}: {
  children: ReactNode;
  tone?: "warning" | "info" | "success" | "danger";
  action?: ReactNode;
}) {
  if (!showInformationalNotifications && tone !== "danger") {
    return action ? <div className="row wrap">{action}</div> : null;
  }
  const toneClass =
    tone === "warning"
      ? "warn"
      : tone === "success"
        ? "green"
        : tone === "danger"
          ? "danger"
          : "info";
  return (
    <div className={`notice ${tone} ${toneClass}`}>
      <div className="row" style={{ alignItems: "flex-start", gap: 10 }}>
        {tone === "success" ? (
          <Check className="confirmation-check" size={17} />
        ) : tone === "info" ? (
          <Info size={17} />
        ) : (
          <AlertCircle size={17} />
        )}
        <div>{children}</div>
      </div>
      {action && <div className="row wrap">{action}</div>}
    </div>
  );
}

export const InlineNotice = Notice;

export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  wide = false,
}: {
  open: boolean;
  onOpenChange: (value: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const opener = useRef<HTMLElement | null>(null);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={wide ? "modal-wide" : "modal-normal"}
        {...(!description ? { "aria-describedby": undefined } : {})}
        onOpenAutoFocus={() => {
          opener.current =
            document.activeElement instanceof HTMLElement
              ? document.activeElement
              : null;
        }}
        onCloseAutoFocus={(event) => {
          if (opener.current?.isConnected) {
            event.preventDefault();
            opener.current.focus({ preventScroll: true });
          }
        }}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  );
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Xác nhận",
  cancelLabel = "Hủy",
  destructive = false,
  busy = false,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void | Promise<void>;
}) {
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
    >
      <div className="row between" style={{ marginTop: 16 }}>
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={() => onOpenChange(false)}
        >
          {cancelLabel}
        </Button>
        <Button
          type="button"
          variant={destructive ? "destructive" : "default"}
          disabled={busy}
          onClick={() => void onConfirm()}
        >
          {busy ? <LoaderCircle className="animate-spin" size={16} /> : null}
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}

export function Drawer({
  open,
  onOpenChange,
  title,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
}) {
  if (!open) return null;
  return (
    <div
      className="mobile-drawer-backdrop"
      style={{ justifyContent: "flex-end" }}
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={(e) => {
        if (e.target === e.currentTarget) onOpenChange(false);
      }}
    >
      <aside
        className="mobile-drawer-panel"
        style={{
          width: "min(440px, calc(100vw - 24px))",
          maxWidth: "440px",
          background: "var(--minda-surface)",
          borderRight: 0,
          borderLeft: "1px solid var(--minda-border)",
          padding: 20,
        }}
      >
        <div className="row between" style={{ marginBottom: 16 }}>
          <h2>{title}</h2>
          <button
            type="button"
            className="icon-btn"
            aria-label="Đóng ngăn phụ"
            onClick={() => onOpenChange(false)}
          >
            <X size={18} />
          </button>
        </div>
        {children}
      </aside>
    </div>
  );
}

export function Tooltip({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <span title={label} data-tooltip={label}>
      {children}
    </span>
  );
}

export function DownloadLink({
  artifact,
  label = "Tải xuống",
}: {
  artifact: Artifact;
  label?: string;
}) {
  return (
    <a className="download-link" href={artifact.url + "?download=true"}>
      <Download size={15} />
      {label}
    </a>
  );
}

const ZOOM_STEPS = [
  50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 170, 180, 190, 200,
];

function PreviewPage({
  page,
  source,
  number,
  ratio,
  zoomMode,
  onRatio,
  onRetry,
}: {
  page: Artifact;
  source: string;
  number: number;
  ratio: number;
  zoomMode: string;
  onRatio: (ratio: number) => void;
  onRetry: () => void;
}) {
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const numericZoom = zoomMode === "fit" ? null : Number(zoomMode);
  const widthStyle =
    numericZoom && Number.isFinite(numericZoom) ? `${numericZoom}%` : "100%";

  return (
    <div
      className="document-page-frame"
      style={{
        aspectRatio: ratio,
        width: widthStyle,
        maxWidth: numericZoom && numericZoom > 100 ? "none" : "100%",
        margin: "0 auto",
      }}
      aria-busy={status === "loading"}
    >
      <a
        href={page.url}
        target="_blank"
        rel="noreferrer"
        aria-label={`Mở trang ${number} đầy đủ`}
      >
        <img
          className={"document-page" + (status === "ready" ? " is-ready" : "")}
          src={source}
          alt={`Bản xem trước DOCX, trang ${number}`}
          onLoad={(event) => {
            const image = event.currentTarget;
            if (image.naturalWidth && image.naturalHeight) {
              onRatio(image.naturalWidth / image.naturalHeight);
              setStatus("ready");
            }
          }}
          onError={() => setStatus("error")}
        />
      </a>
      {status !== "ready" && (
        <div
          className="document-page-placeholder"
          role="status"
          aria-live="polite"
        >
          {status === "error" ? (
            <>
              <AlertCircle size={20} />
              <span>Không tải được trang xem trước.</span>
              <Button variant="outline" size="sm" onClick={onRetry}>
                Thử tải lại
              </Button>
            </>
          ) : (
            <>
              <LoaderCircle className="animate-spin" size={20} />
              <span>Đang tải trang {number}…</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function Preview({
  pages,
  download,
}: {
  pages: Artifact[];
  download?: Artifact;
}) {
  const [index, setIndex] = useState(0);
  const [ratio, setRatio] = useState(210 / 297);
  const [retry, setRetry] = useState(0);
  const [zoom, setZoom] = useState("fit");
  const current = Math.min(index, Math.max(0, pages.length - 1));
  const page = pages[current];
  const imageSource = page
    ? page.url +
      (retry
        ? `${page.url.includes("?") ? "&" : "?"}preview_retry=${retry}`
        : "")
    : "";

  const currentNumericZoom = zoom === "fit" ? 100 : Number(zoom) || 100;
  function adjustZoom(delta: number) {
    const next = Math.max(50, Math.min(200, currentNumericZoom + delta));
    setZoom(String(next));
  }

  return (
    <div
      className={
        "document-preview" +
        (zoom !== "fit" && Number(zoom) > 100 ? " is-zoomed" : "")
      }
    >
      <div className="preview-toolbar minda-preview-toolbar">
        <span className="row" style={{ gap: 6 }}>
          <FileText size={16} /> Xem trước tài liệu
        </span>
        <div className="row wrap" style={{ gap: 6 }}>
          <div className="minda-preview-zoom-controls">
            <Button
              type="button"
              aria-label="Thu nhỏ tài liệu"
              variant="ghost"
              size="icon"
              disabled={zoom !== "fit" && Number(zoom) <= 50}
              onClick={() => adjustZoom(-10)}
            >
              <Minus size={14} />
            </Button>
            <select
              aria-label="Thu phóng tài liệu"
              value={zoom}
              onChange={(event) => setZoom(event.target.value)}
              style={{
                width: "auto",
                minHeight: 32,
                height: 32,
                padding: "0 8px",
              }}
            >
              <option value="fit">Vừa khung</option>
              {ZOOM_STEPS.map((step) => (
                <option key={step} value={String(step)}>
                  {step}%
                </option>
              ))}
            </select>
            <Button
              type="button"
              aria-label="Phóng to tài liệu"
              variant="ghost"
              size="icon"
              disabled={zoom !== "fit" && Number(zoom) >= 200}
              onClick={() => adjustZoom(10)}
            >
              <Plus size={14} />
            </Button>
          </div>
          <Button
            type="button"
            aria-label="Trang trước"
            variant="ghost"
            size="icon"
            disabled={current === 0}
            onClick={() => setIndex(current - 1)}
          >
            <ChevronLeft size={16} />
          </Button>
          <span>
            {pages.length ? current + 1 : 0}/{pages.length}
          </span>
          <Button
            type="button"
            aria-label="Trang sau"
            variant="ghost"
            size="icon"
            disabled={current >= pages.length - 1}
            onClick={() => setIndex(current + 1)}
          >
            <ChevronRight size={16} />
          </Button>
        </div>
      </div>
      {page ? (
        <div style={{ overflowX: "auto" }}>
          <PreviewPage
            key={imageSource}
            page={page}
            source={imageSource}
            number={current + 1}
            ratio={ratio}
            zoomMode={zoom}
            onRatio={setRatio}
            onRetry={() => setRetry((value) => value + 1)}
          />
        </div>
      ) : (
        <Empty
          title="Chưa có bản xem trước"
          description="Bạn vẫn có thể tải file Word. Nếu cần bản xem trước, hãy liên hệ quản trị viên."
        />
      )}
      {download && (
        <div className="preview-footer">
          <DownloadLink
            artifact={artifactOrDownload(download)}
            label="Tải file Word có thể chỉnh sửa"
          />
        </div>
      )}
    </div>
  );
}

function artifactOrDownload(artifact: Artifact): Artifact {
  return artifact;
}

export function JsonDetails({
  value,
  label = "Chi tiết kỹ thuật",
}: {
  value: unknown;
  label?: string;
}) {
  return (
    <details className="json-details">
      <summary>{label}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
