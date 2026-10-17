import { ErrorBox, Loading, Panel, useWork } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Admin } from "@/features/admin/pages";
import {
  Dashboard,
  Meetings,
  NewMeeting,
  Settings,
} from "@/features/meetings/pages";
import { Workspace } from "@/features/meetings/workspace";
import { TemplateDetail, Templates, Voices } from "@/features/templates/pages";
import { api, formatDate, labels, post } from "@/lib/api";
import type { Job, User } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeft,
  ArrowUpRight,
  AudioLines,
  Bell,
  BookOpen,
  ChevronRight,
  Database,
  FolderOpen,
  LayoutDashboard,
  LogOut,
  Menu,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  Users,
  X,
} from "lucide-react";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import {
  Link,
  NavLink,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";

const AuthContext = createContext<User | null>(null);
export const useUser = () => useContext(AuthContext)!;

function Login() {
  const status = useQuery({
    queryKey: ["setup-status"],
    queryFn: () => api<{ requires_setup: boolean }>("/auth/status"),
  });
  const [username, setUsername] = useState(""),
    [password, setPassword] = useState(""),
    [name, setName] = useState("");
  const { busy, work } = useWork();
  const query = useQueryClient();
  async function submit(e: FormEvent) {
    e.preventDefault();
    await work(async () => {
      if (status.data?.requires_setup)
        await post("/auth/setup", { username, password, display_name: name });
      const user = await post<User>("/auth/login", { username, password });
      query.setQueryData(["me"], user);
    }, "Đăng nhập thành công");
  }
  return (
    <div className="auth-page">
      <div className="auth-story">
        <Link className="brand" to="/">
          <span className="brand-symbol">
            <AudioLines size={23} />
          </span>
          Biên bản<span className="brand-dot">.</span>
        </Link>
        <span className="eyebrow">KHÔNG GIAN LÀM VIỆC CUỘC HỌP</span>
        <h1>
          Từ cuộc trò chuyện
          <br />
          đến văn bản
          <br />
          <em>rõ ràng.</em>
        </h1>
        <p>
          Chép lời, đối chiếu và hoàn thiện biên bản trong một quy trình liền
          mạch.
        </p>
        <div className="auth-note">
          <ShieldCheck size={22} />
          <div>
            <strong>Dữ liệu trong tầm kiểm soát</strong>
            <p>Xử lý tại máy chủ của bạn. Mọi thay đổi đều có lịch sử.</p>
          </div>
        </div>
        <span className="auth-footer">MEETING NOTES · RESEARCH PROTOTYPE</span>
      </div>
      <div className="auth-form">
        <div>
          <span className="step-label">BẮT ĐẦU LÀM VIỆC</span>
          <h2>
            {status.data?.requires_setup
              ? "Thiết lập quản trị viên"
              : "Chào mừng trở lại"}
          </h2>
          <p className="muted">
            {status.data?.requires_setup
              ? "Tạo tài khoản quản trị đầu tiên cho hệ thống của bạn."
              : "Đăng nhập để tiếp tục với các cuộc họp của bạn."}
          </p>
          <ErrorBox error={status.error} />
          <form onSubmit={submit} className="form-stack">
            {status.data?.requires_setup && (
              <label>
                Họ và tên
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  maxLength={200}
                  autoComplete="name"
                />
              </label>
            )}
            <label>
              Tên đăng nhập
              <Input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                minLength={3}
                pattern="[a-zA-Z0-9_.-]+"
                autoComplete="username"
                placeholder="Tên tài khoản của bạn"
              />
            </label>
            <label>
              Mật khẩu
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={status.data?.requires_setup ? 10 : 1}
                maxLength={128}
                autoComplete={
                  status.data?.requires_setup
                    ? "new-password"
                    : "current-password"
                }
              />
            </label>
            <Button size="lg" disabled={busy || !status.data} type="submit">
              {busy
                ? "Đang xác thực…"
                : status.data?.requires_setup
                  ? "Tạo tài khoản & bắt đầu"
                  : "Đăng nhập"}
              <ArrowUpRight size={17} />
            </Button>
          </form>
          <p className="small muted">
            {status.data?.requires_setup
              ? "Mật khẩu tối thiểu 10 ký tự. Hãy lưu lại thông tin đăng nhập."
              : "Liên hệ quản trị viên nếu bạn cần cấp lại mật khẩu."}
          </p>
        </div>
      </div>
    </div>
  );
}

function Shell() {
  const user = useUser(),
    location = useLocation(),
    navigate = useNavigate(),
    query = useQueryClient();
  const admin = location.pathname.startsWith("/admin");
  const [search, setSearch] = useState(""),
    [mobile, setMobile] = useState(false),
    [notifications, setNotifications] = useState(false);
  const { work } = useWork();
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api<Job[]>("/jobs"),
    refetchInterval: 5000,
  });
  const pending =
    jobs.data?.filter((j) =>
      ["queued", "running", "failed", "interrupted"].includes(j.state),
    ) || [];
  const links = admin
    ? ([
        [LayoutDashboard, "/admin", "Tổng quan"],
        [Users, "/admin/users", "Tài khoản"],
        [Activity, "/admin/jobs", "Tác vụ xử lý"],
        [SlidersHorizontal, "/admin/models", "Mô hình & cấu hình"],
        [BookOpen, "/admin/templates", "Mẫu dùng chung"],
        [Database, "/admin/backups", "Sao lưu dữ liệu"],
        [Activity, "/admin/experiments", "Đánh giá"],
        [ShieldCheck, "/admin/audit", "Nhật ký hệ thống"],
      ] as const)
    : ([
        [LayoutDashboard, "/", "Tổng quan"],
        [FolderOpen, "/meetings", "Cuộc họp"],
        [BookOpen, "/templates", "Thư viện mẫu"],
        [Users, "/voices", "Hồ sơ giọng"],
        [Trash2, "/trash", "Thùng rác"],
        [Settings2, "/settings", "Thiết lập"],
      ] as const);
  useEffect(() => {
    setMobile(false);
    setNotifications(false);
  }, [location.pathname]);
  return (
    <div className={`app-shell ${admin ? "admin-shell" : ""}`}>
      <aside className={`sidebar ${mobile ? "mobile-open" : ""}`}>
        <Link className="brand" to="/">
          <span className="brand-symbol">
            <AudioLines size={20} />
          </span>
          Biên bản<span className="brand-dot">.</span>
        </Link>
        <p className="nav-section">
          {admin ? "QUẢN TRỊ HỆ THỐNG" : "KHÔNG GIAN CỦA BẠN"}
        </p>
        <nav>
          {links.map(([Icon, to, label]) => (
            <NavLink end={to === "/" || to === "/admin"} to={to} key={to}>
              <Icon size={19} />
              <span>{label}</span>
              <ChevronRight className="nav-arrow" size={14} />
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          {user.role === "admin" && (
            <Link className="switch-area" to={admin ? "/" : "/admin"}>
              {admin ? <ArrowLeft size={17} /> : <ShieldCheck size={17} />}
              <span>
                {admin ? "Về không gian cá nhân" : "Quản trị hệ thống"}
              </span>
              <ArrowUpRight size={15} />
            </Link>
          )}
          <div className="local-note">
            <i />
            <div>
              <strong>Không gian cục bộ</strong>
              <p>Phiên bản nghiên cứu 1.0</p>
            </div>
          </div>
          <Button
            variant="ghost"
            className="logout"
            onClick={() =>
              void work(async () => {
                await post("/auth/logout");
                query.clear();
                window.location.assign("/");
              }, "Đã đăng xuất")
            }
          >
            <LogOut size={17} />
            Đăng xuất
          </Button>
        </div>
      </aside>
      {mobile && (
        <div className="mobile-overlay" onClick={() => setMobile(false)} />
      )}
      <div className="main-shell">
        <header className="topbar">
          <div className="row">
            <Button
              className="mobile-menu"
              variant="ghost"
              size="icon"
              aria-label="Mở menu"
              onClick={() => setMobile(!mobile)}
            >
              {mobile ? <X /> : <Menu />}
            </Button>
            <form
              className="global-search"
              onSubmit={(e) => {
                e.preventDefault();
                navigate("/meetings?q=" + encodeURIComponent(search));
              }}
            >
              <Search size={17} />
              <input
                aria-label="Tìm cuộc họp"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Tìm cuộc họp của bạn…"
              />
              <kbd>↵</kbd>
            </form>
          </div>
          <div className="row header-actions">
            <span className="today">
              {new Date().toLocaleDateString("vi-VN", {
                day: "2-digit",
                month: "long",
                year: "numeric",
              })}
            </span>
            <div className="notification-wrap">
              <button
                className="icon-button"
                aria-label="Thông báo tác vụ"
                onClick={() => setNotifications(!notifications)}
              >
                <Bell size={19} />
                {pending.length > 0 && <i className="notification-dot" />}
              </button>
              {notifications && (
                <div className="notifications">
                  <strong>Tác vụ của bạn</strong>
                  {pending.length ? (
                    pending.slice(0, 6).map((j) => (
                      <Link
                        key={j.id}
                        to={
                          j.resource_type === "meeting"
                            ? "/meetings/" + j.resource_id
                            : "/settings"
                        }
                      >
                        <span>{labels[j.kind] || j.kind}</span>
                        <small>{j.stage}</small>
                        <time>{formatDate(j.created_at)}</time>
                      </Link>
                    ))
                  ) : (
                    <p className="muted">
                      Bạn đã xem hết các tác vụ cần chú ý.
                    </p>
                  )}
                </div>
              )}
            </div>
            <Link to="/settings" className="account">
              <span className="avatar">
                {user.display_name.slice(0, 1).toUpperCase()}
              </span>
              <div>
                <strong>{user.display_name}</strong>
                <small>{admin ? "Quản trị viên" : "Không gian cá nhân"}</small>
              </div>
            </Link>
          </div>
        </header>
        <main className="page-content">
          <Outlet />
        </main>
        <footer className="app-footer">
          <span>Biên bản · Meeting workspace</span>
          <span>Rà soát nội dung trước khi sử dụng chính thức</span>
        </footer>
      </div>
    </div>
  );
}

function AdminGuard() {
  return useUser().role === "admin" ? <Outlet /> : <Navigate to="/" replace />;
}
export default function App() {
  const query = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/auth/me"),
    retry: false,
    refetchInterval: 60000,
  });
  useEffect(() => {
    const clear = () => {
      query.setQueryData(["me"], null);
      query.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    };
    window.addEventListener("session-expired", clear);
    return () => window.removeEventListener("session-expired", clear);
  }, [query]);
  if (me.isPending) return <Loading />;
  if (!me.data) return <Login />;
  return (
    <AuthContext.Provider value={me.data}>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Dashboard />} />
          <Route path="meetings" element={<Meetings />} />
          <Route path="meetings/new" element={<NewMeeting />} />
          <Route path="meetings/:id" element={<Workspace />} />
          <Route path="templates" element={<Templates />} />
          <Route path="templates/:id" element={<TemplateDetail />} />
          <Route path="voices" element={<Voices />} />
          <Route path="trash" element={<Meetings trashed />} />
          <Route path="settings" element={<Settings />} />
          <Route element={<AdminGuard />}>
            <Route path="admin/*" element={<Admin />} />
          </Route>
          <Route
            path="*"
            element={
              <Panel>
                <h1>Không tìm thấy trang</h1>
                <Link to="/">Về tổng quan</Link>
              </Panel>
            }
          />
        </Route>
      </Routes>
    </AuthContext.Provider>
  );
}
