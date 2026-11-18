import { createContext, useContext, useEffect } from "react";
import {
  Link,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, WifiOff } from "lucide-react";
import { Loading } from "@/components/common";
import { AppLayout, AuthLayout } from "@/components/layouts";
import { Button } from "@/components/ui/button";
import { Admin } from "@/features/admin/pages";
import {
  AccountHelpPage,
  ForbiddenState,
  LoginPage,
  NotFoundState,
  SetupPage,
} from "@/features/auth/pages";
import { DocumentsLibraryPage } from "@/features/documents/pages";
import { UserJobsPage } from "@/features/jobs/pages";
import {
  Dashboard,
  Meetings,
  NewMeeting,
  Settings,
} from "@/features/meetings/pages";
import { Workspace } from "@/features/meetings/workspace";
import {
  DataPolicyPage,
  GuidePage,
  HelpPage,
  WelcomePage,
} from "@/features/public/pages";
import { ReviewQueuePage } from "@/features/review/pages";
import {
  TemplateDetail,
  TemplateNewPage,
  Templates,
  VoiceDetailPage,
  Voices,
} from "@/features/templates/pages";
import { ApiError, api, sanitizeReturnTo } from "@/lib/api";
import type { User } from "@/lib/types";

const AuthContext = createContext<User | null>(null);
export const useUser = () => useContext(AuthContext)!;

function AdminGuard() {
  const user = useUser();
  return user.role === "admin" ? <Outlet /> : <ForbiddenState />;
}

function ProtectedShell({
  user,
  isPending,
  error,
  onRetry,
}: {
  user: User | null | undefined;
  isPending: boolean;
  error: Error | null;
  onRetry: () => void;
}) {
  const location = useLocation();

  if (isPending) {
    return <Loading label="Đang tải không gian làm việc…" />;
  }

  if (error && !(error instanceof ApiError && error.status === 401)) {
    const apiErr = error instanceof ApiError ? error : null;
    return (
      <AuthLayout
        title="Mất kết nối tới máy chủ"
        subtitle="Không thể tải thông tin phiên làm việc do lỗi mạng hoặc dịch vụ cơ sở dữ liệu tạm thời gián đoạn."
        footer={
          <>
            <Link to="/welcome">Trang giới thiệu</Link>
            <Link to="/help">Trợ giúp</Link>
          </>
        }
      >
        <div className="stack">
          <div className="notice danger" role="alert">
            <div className="row" style={{ alignItems: "flex-start", gap: 10 }}>
              <WifiOff size={18} style={{ flexShrink: 0, marginTop: 2 }} />
              <div>
                <strong>Không thể kết nối dịch vụ API</strong>
                <p>{error.message}</p>
                {apiErr?.requestId && (
                  <small className="muted">
                    Mã yêu cầu: {apiErr.requestId}
                  </small>
                )}
              </div>
            </div>
          </div>
          <Button type="button" onClick={onRetry} style={{ width: "100%" }}>
            <RefreshCw size={16} />
            Thử kết nối lại
          </Button>
        </div>
      </AuthLayout>
    );
  }

  if (!user) {
    const currentPath = location.pathname + location.search;
    const safeTarget = sanitizeReturnTo(currentPath);
    const loginHref =
      safeTarget && safeTarget !== "/"
        ? `/login?returnTo=${encodeURIComponent(safeTarget)}`
        : "/login";
    return <Navigate to={loginHref} replace />;
  }

  return (
    <AuthContext.Provider value={user}>
      <AppLayout user={user}>
        <div key={location.pathname} className="route-motion">
          <Outlet />
        </div>
      </AppLayout>
    </AuthContext.Provider>
  );
}

export default function App() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/auth/me"),
    retry: false,
    refetchInterval: 60000,
  });

  useEffect(() => {
    const onSessionExpired = () => {
      const pathname = window.location.pathname;
      const publicPaths = new Set([
        "/welcome",
        "/guide",
        "/help",
        "/data-policy",
        "/account-help",
        "/login",
        "/setup",
      ]);
      queryClient.setQueryData(["me"], null);
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      if (publicPaths.has(pathname)) return;
      const currentPath = pathname + window.location.search;
      const safeTarget = sanitizeReturnTo(currentPath);
      const targetUrl =
        safeTarget && safeTarget !== "/"
          ? `/login?expired=1&returnTo=${encodeURIComponent(safeTarget)}`
          : "/login?expired=1";
      navigate(targetUrl, { replace: true });
    };
    window.addEventListener("session-expired", onSessionExpired);
    return () =>
      window.removeEventListener("session-expired", onSessionExpired);
  }, [queryClient, navigate]);

  const currentUser = me.data || null;

  return (
    <Routes>
      {/* Public & Auth Routes (A01 - A07) */}
      <Route path="/welcome" element={<WelcomePage user={currentUser} />} />
      <Route path="/guide" element={<GuidePage user={currentUser} />} />
      <Route path="/help" element={<HelpPage user={currentUser} />} />
      <Route
        path="/data-policy"
        element={<DataPolicyPage user={currentUser} />}
      />
      <Route path="/login" element={<LoginPage user={currentUser} />} />
      <Route path="/setup" element={<SetupPage user={currentUser} />} />
      <Route path="/account-help" element={<AccountHelpPage />} />

      {/* Protected Workspace & Admin Routes (B01 - E06) */}
      <Route
        element={
          <ProtectedShell
            user={currentUser}
            isPending={me.isPending}
            error={(me.error as Error | null) || null}
            onRetry={() => void me.refetch()}
          />
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="meetings" element={<Meetings />} />
        <Route path="meetings/new" element={<NewMeeting />} />
        <Route path="meetings/:id" element={<Workspace />} />
        <Route path="review" element={<ReviewQueuePage />} />
        <Route path="jobs" element={<UserJobsPage />} />
        <Route path="templates" element={<Templates />} />
        <Route path="templates/new" element={<TemplateNewPage />} />
        <Route path="templates/:id" element={<TemplateDetail />} />
        <Route path="voices" element={<Voices />} />
        <Route path="voices/:id" element={<VoiceDetailPage />} />
        <Route path="documents" element={<DocumentsLibraryPage />} />
        <Route path="trash" element={<Meetings trashed />} />
        <Route path="settings" element={<Settings />} />
        <Route element={<AdminGuard />}>
          <Route path="admin/*" element={<Admin />} />
        </Route>
        <Route path="*" element={<NotFoundState />} />
      </Route>
    </Routes>
  );
}
