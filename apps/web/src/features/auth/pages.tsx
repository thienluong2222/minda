import { useEffect, useState, type FormEvent } from "react";
import {
  Link,
  Navigate,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowLeft,
  KeyRound,
  LoaderCircle,
  RefreshCw,
  ShieldAlert,
  UserCheck,
  WifiOff,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  ErrorBox,
  FormField,
  Loading,
  Notice,
  Panel,
} from "@/components/common";
import { AuthLayout } from "@/components/layouts";
import { ApiError, api, post, sanitizeReturnTo } from "@/lib/api";
import type { User } from "@/lib/types";

export function LoginPage({ user }: { user?: User | null }) {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const rawReturnTo = searchParams.get("returnTo");
  const safeReturnTo = sanitizeReturnTo(rawReturnTo);
  const expired = searchParams.get("expired") === "1";

  const status = useQuery({
    queryKey: ["auth-status"],
    queryFn: () => api<{ requires_setup: boolean }>("/auth/status"),
    retry: false,
  });

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<{
    username?: string;
    password?: string;
  }>({});
  const [authError, setAuthError] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState<ApiError | null>(null);

  useEffect(() => {
    if (status.data?.requires_setup) {
      navigate("/setup", { replace: true });
    }
  }, [status.data?.requires_setup, navigate]);

  if (user) {
    return <Navigate to={safeReturnTo} replace />;
  }

  async function submitLogin(e?: FormEvent) {
    e?.preventDefault();
    setAuthError(null);
    setConnectionError(null);

    const nextFieldErrors: { username?: string; password?: string } = {};
    if (!username.trim()) {
      nextFieldErrors.username = "Vui lòng nhập tên đăng nhập.";
    }
    if (!password) {
      nextFieldErrors.password = "Vui lòng nhập mật khẩu.";
    }
    if (Object.keys(nextFieldErrors).length > 0) {
      setFieldErrors(nextFieldErrors);
      return;
    }
    setFieldErrors({});
    setBusy(true);
    try {
      const loggedIn = await post<User>("/auth/login", {
        username: username.trim(),
        password,
      });
      queryClient.clear();
      queryClient.setQueryData(["me"], loggedIn);
      navigate(safeReturnTo, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 0 || err.status >= 500) {
          setConnectionError(err);
        } else if (err.status === 422 && err.fields?.length) {
          const mapped: { username?: string; password?: string } = {};
          for (const f of err.fields) {
            if (f.field.includes("username")) mapped.username = f.message;
            if (f.field.includes("password")) mapped.password = f.message;
          }
          setFieldErrors(mapped);
          setAuthError(err.message);
        } else {
          setAuthError(err.message);
        }
      } else {
        setAuthError((err as Error).message || "Đăng nhập không thành công.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      title="Đăng nhập hệ thống"
      subtitle="Sử dụng tài khoản nội bộ do đơn vị cấp để truy cập không gian làm việc."
      footer={
        <>
          <Link to="/account-help">Quên mật khẩu / Cần cấp tài khoản?</Link>
          <Link to="/welcome">Giới thiệu Minda</Link>
        </>
      }
    >
      {expired && (
        <Notice tone="warning">
          Phiên làm việc đã hết hạn. Vui lòng đăng nhập lại để tiếp tục tại
          trang bạn đang mở.
        </Notice>
      )}

      {status.data?.requires_setup && (
        <Notice
          tone="info"
          action={
            <Button asChild size="sm">
              <Link to="/setup">Thiết lập quản trị viên</Link>
            </Button>
          }
        >
          Hệ thống chưa có tài khoản quản trị đầu tiên. Hãy chuyển tới trang
          khởi tạo.
        </Notice>
      )}

      {connectionError && (
        <div className="notice danger" role="alert">
          <div className="row" style={{ alignItems: "flex-start", gap: 10 }}>
            <WifiOff size={18} style={{ flexShrink: 0, marginTop: 2 }} />
            <div>
              <strong>Lỗi kết nối máy chủ</strong>
              <p>{connectionError.message}</p>
              {connectionError.requestId && (
                <small className="muted">
                  Mã yêu cầu: {connectionError.requestId}
                </small>
              )}
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => void submitLogin()}
          >
            <RefreshCw size={14} />
            Thử lại
          </Button>
        </div>
      )}

      {authError && !connectionError && (
        <div className="notice danger" role="alert">
          <div className="row" style={{ alignItems: "flex-start", gap: 10 }}>
            <AlertCircle size={18} style={{ flexShrink: 0, marginTop: 2 }} />
            <div>
              <strong>Không thể đăng nhập</strong>
              <p>{authError}</p>
            </div>
          </div>
        </div>
      )}

      <form className="stack" onSubmit={(e) => void submitLogin(e)} noValidate>
        <FormField label="Tên đăng nhập" required error={fieldErrors.username}>
          <input
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => {
              setUsername(e.target.value);
              if (fieldErrors.username)
                setFieldErrors((prev) => ({ ...prev, username: undefined }));
            }}
            placeholder="Ví dụ: thuky.hop"
            aria-invalid={Boolean(fieldErrors.username)}
          />
        </FormField>

        <FormField label="Mật khẩu" required error={fieldErrors.password}>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              if (fieldErrors.password)
                setFieldErrors((prev) => ({ ...prev, password: undefined }));
            }}
            placeholder="Nhập mật khẩu của bạn"
            aria-invalid={Boolean(fieldErrors.password)}
          />
        </FormField>

        <Button
          type="submit"
          disabled={busy}
          style={{ width: "100%", marginTop: 4 }}
        >
          {busy ? <LoaderCircle className="animate-spin" size={16} /> : null}
          Đăng nhập
        </Button>
      </form>
    </AuthLayout>
  );
}

export function SetupPage({ user }: { user?: User | null }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const status = useQuery({
    queryKey: ["auth-status"],
    queryFn: () => api<{ requires_setup: boolean }>("/auth/status"),
    retry: false,
  });

  const [username, setUsername] = useState("admin");
  const [displayName, setDisplayName] = useState("Quản trị viên");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{
    username?: string;
    display_name?: string;
    password?: string;
  }>({});

  if (user) {
    return <Navigate to={user.role === "admin" ? "/admin" : "/"} replace />;
  }

  if (status.isLoading) {
    return (
      <AuthLayout
        title="Khởi tạo quản trị viên"
        subtitle="Đang kiểm tra trạng thái khởi tạo hệ thống…"
      >
        <Loading label="Đang kiểm tra cấu hình hệ thống…" />
      </AuthLayout>
    );
  }

  if (status.data && !status.data.requires_setup) {
    return <Navigate to="/login" replace />;
  }

  async function handleSetup(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const nextErrors: {
      username?: string;
      display_name?: string;
      password?: string;
    } = {};
    if (username.trim().length < 3) {
      nextErrors.username = "Tên đăng nhập cần tối thiểu 3 ký tự.";
    }
    if (!displayName.trim()) {
      nextErrors.display_name = "Vui lòng nhập tên hiển thị.";
    }
    if (password.length < 10) {
      nextErrors.password = "Mật khẩu quản trị cần tối thiểu 10 ký tự.";
    }
    if (Object.keys(nextErrors).length > 0) {
      setFieldErrors(nextErrors);
      return;
    }
    setFieldErrors({});
    setBusy(true);
    try {
      await post("/auth/setup", {
        username: username.trim(),
        display_name: displayName.trim(),
        password,
        role: "admin",
      });
      const loggedIn = await post<User>("/auth/login", {
        username: username.trim(),
        password,
      });
      queryClient.clear();
      queryClient.setQueryData(["me"], loggedIn);
      navigate("/admin", { replace: true });
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      title="Khởi tạo tài khoản quản trị đầu tiên"
      subtitle="Thiết lập tài khoản quản trị viên ban đầu cho máy chủ Minda."
      footer={
        <>
          <Link to="/login">Đã có tài khoản? Đăng nhập</Link>
          <Link to="/guide">Xem hướng dẫn</Link>
        </>
      }
    >
      {status.error ? (
        <ErrorBox
          error={status.error as Error}
          onRetry={() => void status.refetch()}
        />
      ) : null}
      <ErrorBox error={error} />
      <form className="stack" onSubmit={(e) => void handleSetup(e)} noValidate>
        <FormField
          label="Tên đăng nhập quản trị"
          required
          hint="Tối thiểu 3 ký tự, không chứa khoảng trắng."
          error={fieldErrors.username}
        >
          <input
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </FormField>

        <FormField
          label="Tên hiển thị"
          required
          error={fieldErrors.display_name}
        >
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </FormField>

        <FormField
          label="Mật khẩu khởi tạo"
          required
          hint="Tối thiểu 10 ký tự."
          error={fieldErrors.password}
        >
          <input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Nhập mật khẩu từ 10 ký tự trở lên"
          />
        </FormField>

        <Button type="submit" disabled={busy} style={{ width: "100%" }}>
          {busy ? <LoaderCircle className="animate-spin" size={16} /> : null}
          Tạo tài khoản quản trị & Bắt đầu
        </Button>
      </form>
    </AuthLayout>
  );
}

export function AccountHelpPage() {
  return (
    <AuthLayout
      title="Hỗ trợ tài khoản & Cấp lại mật khẩu"
      subtitle="Quy trình cấp tài khoản và khôi phục quyền truy cập trong hệ thống nội bộ."
      footer={
        <>
          <Link to="/login">
            <span className="row" style={{ gap: 6 }}>
              <ArrowLeft size={14} /> Quay lại đăng nhập
            </span>
          </Link>
          <Link to="/help">Trung tâm trợ giúp</Link>
        </>
      }
    >
      <div className="stack">
        <Notice tone="info">
          Minda vận hành độc lập trên máy chủ nội bộ của đơn vị và{" "}
          <strong>không sử dụng dịch vụ gửi email tự động ra bên ngoài</strong>.
          Việc cấp mới hoặc đặt lại mật khẩu do Quản trị viên hệ thống thực
          hiện.
        </Notice>

        <div
          style={{
            padding: 14,
            borderRadius: "var(--minda-radius-surface)",
            border: "1px solid var(--minda-border)",
            background: "var(--minda-canvas)",
          }}
        >
          <div className="row" style={{ gap: 8, marginBottom: 6 }}>
            <UserCheck size={16} className="muted" />
            <strong>1. Cấp tài khoản mới</strong>
          </div>
          <p className="muted small">
            Liên hệ Quản trị viên hệ thống để tạo tài khoản tại mục{" "}
            <code>Quản trị &gt; Tài khoản (/admin/users)</code> và nhận thông
            tin đăng nhập ban đầu.
          </p>
        </div>

        <div
          style={{
            padding: 14,
            borderRadius: "var(--minda-radius-surface)",
            border: "1px solid var(--minda-border)",
            background: "var(--minda-canvas)",
          }}
        >
          <div className="row" style={{ gap: 8, marginBottom: 6 }}>
            <KeyRound size={16} className="muted" />
            <strong>2. Quên mật khẩu hoặc tài khoản tạm khóa</strong>
          </div>
          <p className="muted small">
            Nhờ Quản trị viên đặt lại mật khẩu tạm hoặc mở khóa tài khoản. Sau
            khi đăng nhập lại, hãy vào <code>Thiết lập (/settings)</code> để đổi
            sang mật khẩu cá nhân của bạn.
          </p>
        </div>
      </div>
    </AuthLayout>
  );
}

export function NotFoundState({
  title = "Không tìm thấy trang hoặc tài nguyên",
  description = "Đường dẫn bạn truy cập không tồn tại, đã bị xóa hoặc bạn không có quyền xem tài nguyên này.",
  backTo = "/",
  backLabel = "Về trang tổng quan",
}: {
  title?: string;
  description?: string;
  backTo?: string;
  backLabel?: string;
}) {
  return (
    <div className="page-container--reading" style={{ paddingTop: 24 }}>
      <Panel>
        <div
          className="minda-state-card"
          style={{ border: 0, background: "transparent" }}
        >
          <span className="status-badge neutral">404 · Không tìm thấy</span>
          <h1>{title}</h1>
          <p className="muted" style={{ maxWidth: "52ch" }}>
            {description}
          </p>
          <div className="row wrap" style={{ marginTop: 12 }}>
            <Button asChild>
              <Link to={backTo}>{backLabel}</Link>
            </Button>
            <Button asChild variant="outline">
              <Link to="/meetings">Danh sách cuộc họp</Link>
            </Button>
            <Button asChild variant="ghost">
              <Link to="/help">Trợ giúp</Link>
            </Button>
          </div>
        </div>
      </Panel>
    </div>
  );
}

export function ForbiddenState({
  title = "Bạn không có quyền truy cập khu vực này",
  description = "Khu vực quản trị chỉ dành cho tài khoản có vai trò Quản trị viên (admin). Vui lòng quay lại không gian làm việc cá nhân.",
}: {
  title?: string;
  description?: string;
}) {
  const location = useLocation();
  return (
    <div className="page-container--reading" style={{ paddingTop: 24 }}>
      <Panel>
        <div
          className="minda-state-card"
          style={{ border: 0, background: "transparent" }}
        >
          <ShieldAlert size={32} className="danger-text" />
          <span className="status-badge danger">403 · Không đủ quyền</span>
          <h1>{title}</h1>
          <p className="muted" style={{ maxWidth: "56ch" }}>
            {description}
          </p>
          <small className="muted">
            Đường dẫn yêu cầu: {location.pathname}
          </small>
          <div className="row wrap" style={{ marginTop: 12 }}>
            <Button asChild>
              <Link to="/">Về không gian cá nhân</Link>
            </Button>
            <Button asChild variant="outline">
              <Link to="/meetings">Xem cuộc họp của tôi</Link>
            </Button>
          </div>
        </div>
      </Panel>
    </div>
  );
}
