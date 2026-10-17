export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public requestId?: string,
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
  const response = await fetch("/api/v1" + path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/"))
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(
      body.error?.code || "HTTP_ERROR",
      body.error?.message || "Không thể kết nối hệ thống.",
      response.status,
      body.request_id,
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
export const time = (seconds: number) =>
  `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0")}`;
export const size = (bytes: number) =>
  bytes > 1e9
    ? `${(bytes / 1e9).toFixed(1)} GB`
    : bytes > 1e6
      ? `${(bytes / 1e6).toFixed(1)} MB`
      : `${Math.round(bytes / 1000)} KB`;
export const labels: Record<string, string> = {
  draft: "Bản nháp",
  transcript_ready: "Có transcript",
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
  format_minutes: "Đổi thể thức",
  restore_minutes: "Khôi phục biên bản",
  enroll_voice: "Tạo hồ sơ giọng",
  backup_system: "Sao lưu",
  restore_system: "Khôi phục dữ liệu",
};
