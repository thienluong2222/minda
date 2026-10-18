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
  LoaderCircle,
} from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";

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
      if (message) toast.success(message);
      return result;
    } catch (error) {
      const e = error as Error;
      toast.error(e.message, {
        description:
          error instanceof ApiError
            ? `${error.code}${error.requestId ? " · " + error.requestId : ""}`
            : undefined,
      });
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
    <span className={`status status-${value}`}>
      <i />
      {labels[value] || value}
    </span>
  );
}
export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {description && <p className="muted">{description}</p>}
      </div>
      {action}
    </div>
  );
}
export function Panel({
  title,
  description,
  children,
  className = "",
}: {
  title?: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {title && (
        <header className="panel-header">
          <h2>{title}</h2>
          {description && <p className="muted">{description}</p>}
        </header>
      )}
      {children}
    </section>
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
    <div className="empty">
      <FileText size={28} />
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading">
      <LoaderCircle className="animate-spin" />
      Đang tải dữ liệu…
    </div>
  );
}
export function ErrorBox({ error }: { error: Error | null }) {
  return error ? (
    <div className="notice danger" role="alert">
      <AlertCircle size={18} />
      <span>{error.message}</span>
    </div>
  ) : null;
}
export function Notice({
  children,
  tone = "warning",
}: {
  children: ReactNode;
  tone?: "warning" | "info" | "success";
}) {
  return (
    <div className={`notice ${tone}`}>
      {tone === "success" ? (
        <Check className="confirmation-check" size={17} />
      ) : (
        <AlertCircle size={17} />
      )}
      <div>{children}</div>
    </div>
  );
}
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
          <DialogDescription>
            {description || "Kiểm tra thông tin trước khi lưu."}
          </DialogDescription>
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
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
function PreviewPage({
  page,
  source,
  number,
  ratio,
  onRatio,
  onRetry,
}: {
  page: Artifact;
  source: string;
  number: number;
  ratio: number;
  onRatio: (ratio: number) => void;
  onRetry: () => void;
}) {
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  return (
    <div
      className="document-page-frame"
      style={{ aspectRatio: ratio }}
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
  const current = Math.min(index, Math.max(0, pages.length - 1));
  const page = pages[current];
  const imageSource = page
    ? page.url +
      (retry
        ? `${page.url.includes("?") ? "&" : "?"}preview_retry=${retry}`
        : "")
    : "";
  return (
    <div className="document-preview">
      <div className="preview-toolbar">
        <span>
          <FileText size={16} /> Xem trước tài liệu
        </span>
        <div className="row">
          <Button
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
        <PreviewPage
          key={imageSource}
          page={page}
          source={imageSource}
          number={current + 1}
          ratio={ratio}
          onRatio={setRatio}
          onRetry={() => setRetry((value) => value + 1)}
        />
      ) : (
        <Empty
          title="Chưa có bản xem trước"
          description="Kiểm tra LibreOffice và Poppler trong trang hệ thống."
        />
      )}
      {download && (
        <div className="preview-footer">
          <DownloadLink
            artifact={download}
            label="Tải file Word có thể chỉnh sửa"
          />
        </div>
      )}
    </div>
  );
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
