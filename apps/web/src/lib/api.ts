import type { Job } from "./types";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public requestId?: string,
    public fields?: { field: string; message: string }[],
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  const csrf = document.cookie
    .split("; ")
    .find((v) => v.startsWith("meeting_csrf="))
    ?.split("=")[1];
  if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch("/api/v1" + path, {
      ...options,
      headers,
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(
      "NETWORK_ERROR",
      "Không thể kết nối tới máy chủ. Hãy kiểm tra mạng hoặc trạng thái dịch vụ rồi thử lại.",
      0,
    );
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/"))
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(
      body.error?.code || "HTTP_ERROR",
      body.error?.message || "Không thể kết nối hệ thống.",
      response.status,
      body.request_id,
      body.error?.fields,
    );
  }
  return body as T;
}
export const post = <T>(path: string, data?: unknown) =>
  api<T>(path, {
    method: "POST",
    body:
      data instanceof FormData
        ? data
        : data === undefined
          ? undefined
          : JSON.stringify(data),
  });
export const patch = <T>(path: string, data: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(data) });
export const formatDate = (value?: string) =>
  value
    ? new Date(value).toLocaleString("vi-VN", {
        dateStyle: "short",
        timeStyle: "short",
      })
    : "—";
export const formatMeetingDate = (value?: string) => {
  if (!value) return "Chưa đặt";
  const dateOnlyMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (dateOnlyMatch) {
    const [, year, month, day] = dateOnlyMatch;
    return `${day}/${month}/${year}`;
  }
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.valueOf())) return value;
  return parsed.toLocaleDateString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
};

export function sanitizeReturnTo(raw: string | null | undefined): string {
  if (!raw) return "/";
  const trimmed = raw.trim();
  if (!trimmed.startsWith("/") || trimmed.startsWith("//")) return "/";
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(trimmed)) return "/";
  const pathOnly = trimmed.split("?")[0].split("#")[0];
  if (
    pathOnly === "/login" ||
    pathOnly === "/setup" ||
    pathOnly === "/account-help"
  ) {
    return "/";
  }
  return trimmed;
}
export const time = (seconds: number) => {
  if (!Number.isFinite(seconds)) return "—";
  const value = Math.floor(Math.abs(seconds));
  const parts = [Math.floor(value / 60) % 60, value % 60];
  if (value >= 3600) parts.unshift(Math.floor(value / 3600));
  return (
    (seconds < 0 ? "−" : "") +
    parts.map((part) => String(part).padStart(2, "0")).join(":")
  );
};
export const size = (bytes: number) =>
  bytes > 1e9
    ? `${(bytes / 1e9).toFixed(1)} GB`
    : bytes > 1e6
      ? `${(bytes / 1e6).toFixed(1)} MB`
      : `${Math.round(bytes / 1000)} KB`;
export const jobErrorMessage = (error?: { message: string }) => {
  if (error?.message === "Selected clip range exceeds decoded audio")
    return "Điểm kết thúc đoạn vượt độ dài audio sau giải mã. Hãy kiểm tra vùng chọn hoặc cập nhật bộ xử lý rồi thử lại.";
  return error?.message || "";
};
export function attentionJobs(jobs: Job[]) {
  const seen = new Set<string>();
  return [...jobs]
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
    .filter((job) => {
      const key = JSON.stringify([
        job.resource_type,
        job.resource_id,
        job.kind,
      ]);
      if (seen.has(key)) return false;
      seen.add(key);
      return ["queued", "running", "failed", "interrupted"].includes(job.state);
    });
}
export const labels: Record<string, string> = {
  draft: "Bản nháp",
  transcript_ready: "Có lời chép",
  minutes_ready: "Có biên bản",
  queued: "Đang chờ",
  running: "Đang xử lý",
  succeeded: "Hoàn tất",
  failed: "Thất bại",
  interrupted: "Gián đoạn",
  cancelled: "Đã hủy",
  ready: "Sẵn sàng",
  account_active: "Đang hoạt động",
  account_locked: "Đã khóa",
  pending: "Đang chuẩn bị",
  supported: "Có căn cứ",
  unknown: "Thiếu thông tin",
  needs_review: "Cần rà soát",
  conflicting: "Mâu thuẫn",
  generate_minutes: "Tạo biên bản",
  transcribe: "Xử lý âm thanh",
  ingest_template: "Đọc mẫu",
  review_template: "Duyệt mẫu",
  edit_facts: "Lưu biên bản",
  revise_minutes_outline: "Viết lại theo dàn ý",
  format_minutes: "Đổi thể thức",
  restore_minutes: "Khôi phục biên bản",
  enroll_voice: "Tạo hồ sơ giọng",
  backup_system: "Sao lưu",
  restore_system: "Khôi phục dữ liệu",
  reviewed: "Đã rà soát",
  stale: "Cần cập nhật",
  private: "Cá nhân",
  shared: "Dùng chung",
  rejected: "Từ chối",
  canceling: "Đang hủy",
  canceled: "Đã hủy",
  minutes_stale: "Biên bản cần cập nhật",
  minutes_unreviewed: "Biên bản chưa xác nhận",
  transcript_needs_review: "Lời chép cần rà soát",
  template_needs_review: "Mẫu cần duyệt",
};
