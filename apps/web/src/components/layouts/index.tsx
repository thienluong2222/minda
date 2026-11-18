import { useEffect, useState, type ReactNode } from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  Activity,
  ArrowLeftRight,
  Bell,
  BookOpen,
  Calendar,
  CheckSquare,
  Cpu,
  DatabaseBackup,
  FileCheck2,
  FileSpreadsheet,
  FileText,
  FlaskConical,
  HelpCircle,
  Home,
  ListChecks,
  LogOut,
  Menu,
  Mic,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  Search,
  Settings,
  Shield,
  SlidersHorizontal,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { Brand } from "@/components/brand";
import { AmbientVisual } from "@/components/visuals/ambient";
import { Button } from "@/components/ui/button";
import { Status } from "@/components/common";
import {
  attentionJobs,
  formatDate,
  jobErrorMessage,
  labels,
  post,
} from "@/lib/api";
import type { Job, User } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export interface NavItem {
  to: string;
  label: string;
  icon: typeof Home;
  end?: boolean;
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

export const USER_NAV_GROUPS: NavGroup[] = [
  {
    title: "CÔNG VIỆC",
    items: [
      { to: "/", label: "Tổng quan", icon: Home, end: true },
      { to: "/meetings", label: "Cuộc họp", icon: Calendar },
      { to: "/review", label: "Cần rà soát", icon: CheckSquare },
      { to: "/jobs", label: "Tác vụ", icon: ListChecks },
    ],
  },
  {
    title: "TÀI NGUYÊN",
    items: [
      { to: "/templates", label: "Mẫu biên bản", icon: FileSpreadsheet },
      { to: "/voices", label: "Hồ sơ giọng", icon: Mic },
      { to: "/documents", label: "Thư viện biên bản", icon: FileCheck2 },
    ],
  },
  {
    title: "CÁ NHÂN",
    items: [
      { to: "/trash", label: "Thùng rác", icon: Trash2 },
      { to: "/settings", label: "Thiết lập", icon: Settings },
    ],
  },
];

export const ADMIN_NAV_GROUPS: NavGroup[] = [
  {
    title: "QUẢN TRỊ",
    items: [
      { to: "/admin", label: "Tổng quan", icon: Shield, end: true },
      { to: "/admin/users", label: "Tài khoản", icon: Users },
      { to: "/admin/meetings", label: "Cuộc họp", icon: Calendar },
      { to: "/admin/jobs", label: "Tác vụ", icon: Activity },
      { to: "/admin/models", label: "Model & preset", icon: SlidersHorizontal },
    ],
  },
  {
    title: "TÀI NGUYÊN & VẬN HÀNH",
    items: [
      { to: "/admin/templates", label: "Mẫu dùng chung", icon: FileText },
      { to: "/admin/backups", label: "Sao lưu", icon: DatabaseBackup },
      { to: "/admin/experiments", label: "Đánh giá", icon: FlaskConical },
      { to: "/admin/audit", label: "Nhật ký", icon: ScrollText },
      { to: "/admin/system", label: "Tình trạng hệ thống", icon: Cpu },
    ],
  },
];

export function PublicLayout({
  children,
  user,
}: {
  children: ReactNode;
  user?: User | null;
}) {
  return (
    <div className="public-shell">
      <a href="#main-content" className="skip-link">
        Chuyển tới nội dung chính
      </a>
      <header className="public-header">
        <div className="public-header-inner">
          <Brand
            context="public"
            variant="full"
            to="/welcome"
            label="Minda — Giới thiệu hệ thống"
            subtitle="Trợ lý biên bản"
          />
          <nav
            className="public-nav"
            aria-label="Điều hướng thông tin công khai"
          >
            <NavLink
              to="/welcome"
              className={({ isActive }) =>
                "public-nav-link" + (isActive ? " active" : "")
              }
            >
              Tổng quan
            </NavLink>
            <NavLink
              to="/guide"
              className={({ isActive }) =>
                "public-nav-link" + (isActive ? " active" : "")
              }
            >
              Hướng dẫn
            </NavLink>
            <NavLink
              to="/help"
              className={({ isActive }) =>
                "public-nav-link" + (isActive ? " active" : "")
              }
            >
              Trợ giúp
            </NavLink>
            <NavLink
              to="/data-policy"
              className={({ isActive }) =>
                "public-nav-link" + (isActive ? " active" : "")
              }
            >
              Dữ liệu & bảo mật
            </NavLink>
            {user ? (
              <Button asChild size="sm">
                <Link to={user.role === "admin" ? "/admin" : "/"}>
                  Mở ứng dụng
                </Link>
              </Button>
            ) : (
              <Button asChild size="sm">
                <Link to="/login">Đăng nhập</Link>
              </Button>
            )}
          </nav>
        </div>
      </header>
      <main id="main-content" className="public-main" tabIndex={-1}>
        {children}
      </main>
      <footer className="public-footer">
        <div className="public-footer-inner">
          <span>
            Minda · Dữ liệu âm thanh, lời chép và biên bản được lưu trữ trực
            tiếp trên máy chủ triển khai nội bộ.
          </span>
          <div className="public-footer-links">
            <Link to="/welcome">Tổng quan</Link>
            <Link to="/guide">Hướng dẫn sử dụng</Link>
            <Link to="/help">Trợ giúp & khắc phục lỗi</Link>
            <Link to="/data-policy">Dữ liệu & quyền riêng tư</Link>
            <Link to="/account-help">Hỗ trợ tài khoản</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}

export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="auth-shell">
      <AmbientVisual />
      <a href="#main-content" className="skip-link">
        Chuyển tới biểu mẫu xác thực
      </a>
      <header className="auth-topbar">
        <Brand
          context="public"
          variant="full"
          to="/welcome"
          label="Minda — Giới thiệu hệ thống"
        />
        <nav className="public-nav" aria-label="Liên kết hỗ trợ">
          <Link to="/guide" className="public-nav-link">
            Hướng dẫn
          </Link>
          <Link to="/help" className="public-nav-link">
            Trợ giúp
          </Link>
          <Link to="/data-policy" className="public-nav-link">
            Chính sách dữ liệu
          </Link>
        </nav>
      </header>
      <main id="main-content" className="auth-main" tabIndex={-1}>
        <section className="auth-container" aria-labelledby="auth-page-title">
          <div className="auth-brand-header">
            <Brand
              context="login"
              variant="full"
              to="/welcome"
              label="Minda — Trang giới thiệu"
            />
            <div>
              <h1 id="auth-page-title">{title}</h1>
              {subtitle && (
                <p className="muted" style={{ marginTop: 6 }}>
                  {subtitle}
                </p>
              )}
            </div>
          </div>
          {children}
          {footer && <div className="auth-footer-links">{footer}</div>}
        </section>
      </main>
    </div>
  );
}

function JobNotifications({ isAdmin }: { isAdmin: boolean }) {
  const [open, setOpen] = useState(false);
  const jobs = useQuery({
    queryKey: ["jobs", "notifications"],
    queryFn: () => api<Job[]>("/jobs"),
    refetchInterval: (query) =>
      query.state.data?.some((j) => ["queued", "running"].includes(j.state))
        ? 2500
        : 12000,
  });
  const recent = attentionJobs(jobs.data || []).slice(0, 6);
  const activeCount = (jobs.data || []).filter((j) =>
    ["queued", "running"].includes(j.state),
  ).length;

  return (
    <div className="notification-wrap">
      <button
        type="button"
        className="icon-btn"
        aria-label={
          activeCount ? `Tác vụ nền (${activeCount} đang chạy)` : "Tác vụ nền"
        }
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Bell size={18} />
        {activeCount > 0 && (
          <span className="notification-dot" aria-hidden="true">
            {activeCount}
          </span>
        )}
      </button>
      {open && (
        <div
          className="notification-popover"
          role="dialog"
          aria-label="Tác vụ gần đây"
        >
          <div className="row between" style={{ marginBottom: 8 }}>
            <strong>Tác vụ gần đây</strong>
            <Link
              to={isAdmin ? "/admin/jobs" : "/jobs"}
              className="small green-text"
              onClick={() => setOpen(false)}
            >
              Xem tất cả
            </Link>
          </div>
          {recent.length ? (
            <div className="stack compact-stack">
              {recent.map((job) => {
                const targetUrl =
                  job.resource_type === "meeting" && job.resource_id
                    ? `/meetings/${job.resource_id}?job=${job.id}`
                    : job.resource_type === "template" && job.resource_id
                      ? `/templates/${job.resource_id}`
                      : isAdmin
                        ? "/admin/jobs"
                        : "/jobs";
                return (
                  <Link
                    key={job.id}
                    to={targetUrl}
                    className="notification-item"
                    onClick={() => setOpen(false)}
                  >
                    <div className="row between">
                      <strong>{labels[job.kind] || job.kind}</strong>
                      <Status value={job.state} />
                    </div>
                    <small className="muted">
                      {job.stage || formatDate(job.created_at)}
                    </small>
                    {job.error && (
                      <small className="danger-text">
                        {jobErrorMessage(job.error)}
                      </small>
                    )}
                  </Link>
                );
              })}
            </div>
          ) : (
            <p className="muted small">
              Không có tác vụ đang chờ hoặc gặp lỗi.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function AppLayout({
  user,
  children,
}: {
  user: User;
  children: ReactNode;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isAdminArea = location.pathname.startsWith("/admin");
  const navGroups = isAdminArea ? ADMIN_NAV_GROUPS : USER_NAV_GROUPS;

  const [railPreference, setRailPreference] = useState<boolean>(() => {
    try {
      return localStorage.getItem("minda-sidebar-rail") === "1";
    } catch {
      return false;
    }
  });
  const [viewportWidth, setViewportWidth] = useState<number>(() =>
    typeof window !== "undefined" ? window.innerWidth : 1440,
  );
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    const onResize = () => {
      setViewportWidth(window.innerWidth);
      if (window.innerWidth >= 1024) setMobileDrawerOpen(false);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    setMobileDrawerOpen(false);
  }, [location.pathname, location.search]);

  const isAutoRail = viewportWidth >= 1024 && viewportWidth < 1280;
  const isRail = isAutoRail ? true : railPreference;

  function toggleSidebarRail() {
    const next = !railPreference;
    setRailPreference(next);
    try {
      localStorage.setItem("minda-sidebar-rail", next ? "1" : "0");
    } catch {
      /* Storage optional */
    }
  }

  async function handleLogout() {
    try {
      await post("/auth/logout");
    } finally {
      queryClient.clear();
      navigate("/login", { replace: true });
    }
  }

  function renderNavItems(inDrawer = false) {
    const effectiveRail = !inDrawer && isRail;
    return (
      <>
        {navGroups.map((group) => (
          <div key={group.title} className="sidebar-group">
            <p className="nav-section">{group.title}</p>
            <nav aria-label={group.title}>
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    title={effectiveRail ? item.label : undefined}
                    aria-label={effectiveRail ? item.label : undefined}
                    className={({ isActive }) => (isActive ? "active" : "")}
                  >
                    <Icon size={20} aria-hidden="true" />
                    <span className="nav-label">{item.label}</span>
                  </NavLink>
                );
              })}
            </nav>
          </div>
        ))}
        <div className="sidebar-bottom">
          <Link
            to="/guide"
            className="sidebar-footer-link"
            title={effectiveRail ? "Hướng dẫn sử dụng" : undefined}
            aria-label={effectiveRail ? "Hướng dẫn sử dụng" : undefined}
          >
            <BookOpen size={18} aria-hidden="true" />
            <span className="nav-label">Hướng dẫn</span>
          </Link>
          <Link
            to="/help"
            className="sidebar-footer-link"
            title={effectiveRail ? "Trợ giúp & FAQ" : undefined}
            aria-label={effectiveRail ? "Trợ giúp & FAQ" : undefined}
          >
            <HelpCircle size={18} aria-hidden="true" />
            <span className="nav-label">Trợ giúp</span>
          </Link>
          {user.role === "admin" && (
            <Link
              to={isAdminArea ? "/" : "/admin"}
              className="sidebar-footer-link"
              title={
                effectiveRail
                  ? isAdminArea
                    ? "Không gian cá nhân"
                    : "Khu vực quản trị"
                  : undefined
              }
              aria-label={
                effectiveRail
                  ? isAdminArea
                    ? "Không gian cá nhân"
                    : "Khu vực quản trị"
                  : undefined
              }
            >
              <ArrowLeftRight size={18} aria-hidden="true" />
              <span className="nav-label">
                {isAdminArea ? "Không gian cá nhân" : "Khu vực quản trị"}
              </span>
            </Link>
          )}
          <button
            type="button"
            className="sidebar-footer-link"
            title={effectiveRail ? "Đăng xuất" : undefined}
            aria-label={effectiveRail ? "Đăng xuất" : undefined}
            onClick={() => void handleLogout()}
          >
            <LogOut size={18} aria-hidden="true" />
            <span className="nav-label">Đăng xuất</span>
          </button>
        </div>
      </>
    );
  }

  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">
        Chuyển tới nội dung chính
      </a>
      <aside
        className={`sidebar ${isRail ? "sidebar--rail" : ""}`}
        aria-label={isAdminArea ? "Điều hướng quản trị" : "Điều hướng ứng dụng"}
      >
        <div className="sidebar-header">
          <Brand
            context={isRail ? "rail" : "sidebar"}
            variant={isRail ? "mark" : "full"}
            to={isAdminArea ? "/admin" : "/"}
            label={
              isAdminArea
                ? "Minda — Tổng quan quản trị"
                : "Minda — Tổng quan công việc"
            }
            subtitle={isAdminArea ? "Quản trị" : undefined}
          />
          {viewportWidth >= 1280 && (
            <button
              type="button"
              className="sidebar-collapse-btn"
              onClick={toggleSidebarRail}
              aria-label={
                isRail ? "Mở rộng thanh điều hướng" : "Thu gọn thanh điều hướng"
              }
              title={
                isRail ? "Mở rộng thanh điều hướng" : "Thu gọn thanh điều hướng"
              }
            >
              {isRail ? (
                <PanelLeftOpen size={16} />
              ) : (
                <PanelLeftClose size={16} />
              )}
            </button>
          )}
        </div>
        {renderNavItems(false)}
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-left">
            <DialogPrimitive.Root
              open={mobileDrawerOpen}
              onOpenChange={setMobileDrawerOpen}
            >
              <DialogPrimitive.Trigger asChild>
                <button
                  type="button"
                  className="mobile-menu-btn"
                  aria-label="Mở menu"
                >
                  <Menu size={20} />
                </button>
              </DialogPrimitive.Trigger>
              <DialogPrimitive.Portal>
                <DialogPrimitive.Overlay className="mobile-drawer-backdrop" />
                <DialogPrimitive.Content
                  className="mobile-drawer-panel"
                  aria-describedby={undefined}
                >
                  <DialogPrimitive.Title className="sr-only">
                    Menu điều hướng
                  </DialogPrimitive.Title>
                  <div className="sidebar-header">
                    <Brand
                      context="sidebar"
                      variant="full"
                      to={isAdminArea ? "/admin" : "/"}
                      label="Minda — Trang chính"
                      subtitle={isAdminArea ? "Quản trị" : undefined}
                    />
                    <DialogPrimitive.Close asChild>
                      <button
                        type="button"
                        className="icon-btn"
                        aria-label="Đóng menu điều hướng"
                      >
                        <X size={18} />
                      </button>
                    </DialogPrimitive.Close>
                  </div>
                  {renderNavItems(true)}
                </DialogPrimitive.Content>
              </DialogPrimitive.Portal>
            </DialogPrimitive.Root>
            {viewportWidth < 1024 && (
              <Brand
                context="mobile"
                variant="mark"
                to={isAdminArea ? "/admin" : "/"}
                label="Minda — Trang chính"
              />
            )}
            {location.pathname !== "/meetings" &&
              location.pathname !== "/trash" &&
              location.pathname !== "/admin/meetings" && (
                <form
                  className="global-search"
                  role="search"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const trimmed = searchQuery.trim();
                    const base = isAdminArea ? "/admin/meetings" : "/meetings";
                    navigate(
                      trimmed
                        ? `${base}?q=${encodeURIComponent(trimmed)}`
                        : base,
                    );
                  }}
                >
                  <Search size={16} className="muted" aria-hidden="true" />
                  <input
                    type="search"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={
                      isAdminArea
                        ? "Tìm cuộc họp trên hệ thống…"
                        : "Tìm nhanh cuộc họp…"
                    }
                    aria-label="Tìm nhanh cuộc họp"
                  />
                </form>
              )}
          </div>
          <div className="topbar-right">
            <Link
              to="/help"
              className="icon-btn"
              title="Trợ giúp"
              aria-label="Trợ giúp"
            >
              <HelpCircle size={18} />
            </Link>
            <JobNotifications isAdmin={isAdminArea} />
            <div className="account" title={user.username}>
              <div>
                <strong>{user.display_name || user.username}</strong>
                <small className="muted">
                  {user.role === "admin" ? "Quản trị viên" : "Người dùng"}
                </small>
              </div>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => void handleLogout()}
              aria-label="Đăng xuất khỏi tài khoản"
            >
              <LogOut size={16} />
              <span className="hide-on-mobile">Đăng xuất</span>
            </Button>
          </div>
        </header>
        <main id="main-content" className="page-content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}

export interface MeetingTabItem {
  id: "sources" | "transcript" | "minutes" | "history";
  label: string;
  badge?: string | number | null;
}

export function MeetingLayout({
  meetingTitle,
  meetingStatus,
  meetingMeta,
  activeTab,
  onSelectTab,
  onOpenOverview,
  headerActions,
  banner,
  hasStickyPlayer = false,
  children,
}: {
  meetingTitle: string;
  meetingStatus: string;
  meetingMeta?: ReactNode;
  activeTab: string;
  onSelectTab: (tab: string) => void;
  onOpenOverview: () => void;
  headerActions?: ReactNode;
  banner?: ReactNode;
  hasStickyPlayer?: boolean;
  children: ReactNode;
}) {
  const tabs: MeetingTabItem[] = [
    { id: "sources", label: "Nguồn âm thanh" },
    { id: "transcript", label: "Lời chép" },
    { id: "minutes", label: "Biên bản" },
    { id: "history", label: "Lịch sử" },
  ];

  return (
    <div
      className={
        "page-container--workspace" +
        (hasStickyPlayer ? " has-sticky-audio-player" : "")
      }
    >
      <div className="workspace-header">
        <div className="workspace-header-main">
          <nav className="breadcrumb" aria-label="Đường dẫn cuộc họp">
            <Link to="/meetings">Cuộc họp</Link>
            <span aria-hidden="true">/</span>
            <span>{meetingTitle}</span>
          </nav>
          <div className="row wrap" style={{ gap: 10, marginTop: 4 }}>
            <h1>{meetingTitle}</h1>
            <Status value={meetingStatus} />
          </div>
          {meetingMeta && (
            <div className="minda-page-header-meta">{meetingMeta}</div>
          )}
        </div>
        <div className="row wrap">
          <Button
            type="button"
            variant={activeTab === "overview" ? "default" : "outline"}
            size="sm"
            onClick={onOpenOverview}
          >
            Thông tin cuộc họp
          </Button>
          {headerActions}
        </div>
      </div>

      {banner}

      <div
        className="workspace-tabs"
        role="tablist"
        aria-label="Các bước xử lý cuộc họp"
      >
        {tabs.map((tab) => {
          const isCurrent =
            activeTab === tab.id ||
            (tab.id === "sources" && activeTab === "speakers");
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={isCurrent}
              className={"workspace-tab" + (isCurrent ? " active" : "")}
              onClick={() => onSelectTab(tab.id)}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      <div className="workspace-stage">{children}</div>
    </div>
  );
}
