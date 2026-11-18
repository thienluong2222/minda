import { useEffect, useRef, useState, type ReactNode } from "react";
import { PanelRightOpen, X } from "lucide-react";
import { Button } from "@/components/ui/button";

export function SplitPane({
  primary,
  secondary,
  secondaryTitle = "Bảng căn cứ & đối chiếu",
  storageKey = "minda-panel-width",
}: {
  primary: ReactNode;
  secondary?: ReactNode;
  secondaryTitle?: string;
  storageKey?: string;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState<number>(() => {
    if (typeof window === "undefined") return 1200;
    return window.innerWidth >= 1200 ? 1024 : window.innerWidth - 96;
  });
  const [drawerOpen, setDrawerOpen] = useState(false);

  const [width, setWidth] = useState(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw !== null) {
        const value = Number(raw);
        if (value >= 45 && value <= 70) return value;
      }
      return 60;
    } catch {
      return 60;
    }
  });

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const updateWidth = () => {
      const measured = el.getBoundingClientRect().width;
      if (measured > 0) setContainerWidth(measured);
    };
    updateWidth();
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(() => updateWidth());
      observer.observe(el);
      return () => observer.disconnect();
    }
    window.addEventListener("resize", updateWidth);
    return () => window.removeEventListener("resize", updateWidth);
  }, []);

  function resize(value: number) {
    const boxWidth =
      root.current?.getBoundingClientRect().width || containerWidth;
    const minPrimaryPct =
      boxWidth >= 960 ? Math.max(45, (520 / boxWidth) * 100) : 50;
    const maxPrimaryPct =
      boxWidth >= 960 ? Math.min(70, ((boxWidth - 332) / boxWidth) * 100) : 68;
    const next = Math.max(minPrimaryPct, Math.min(maxPrimaryPct, value));
    setWidth(next);
    try {
      localStorage.setItem(storageKey, String(Math.round(next)));
    } catch {
      /* Layout persistence is optional. */
    }
  }

  const isWideWorkspace = containerWidth >= 960;

  if (!secondary) {
    return (
      <div ref={root} className="review-layout">
        <div className="review-primary">{primary}</div>
      </div>
    );
  }

  if (!isWideWorkspace) {
    return (
      <div ref={root} className="review-layout review-layout--compact">
        <div className="review-compact-bar">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setDrawerOpen(true)}
          >
            <PanelRightOpen size={16} />
            {secondaryTitle}
          </Button>
        </div>
        <div className="review-primary">{primary}</div>
        {drawerOpen && (
          <div
            className="mobile-drawer-backdrop"
            style={{ justifyContent: "flex-end" }}
            role="dialog"
            aria-modal="true"
            aria-label={secondaryTitle}
            onClick={(e) => {
              if (e.target === e.currentTarget) setDrawerOpen(false);
            }}
          >
            <aside
              className="mobile-drawer-panel"
              style={{
                width: "min(480px, calc(100vw - 24px))",
                maxWidth: "480px",
                background: "var(--minda-surface)",
                borderRight: 0,
                borderLeft: "1px solid var(--minda-border)",
                padding: "16px",
              }}
            >
              <div className="row between" style={{ marginBottom: 12 }}>
                <strong>{secondaryTitle}</strong>
                <button
                  type="button"
                  className="icon-btn"
                  aria-label="Đóng bảng phụ"
                  onClick={() => setDrawerOpen(false)}
                >
                  <X size={18} />
                </button>
              </div>
              <div className="review-secondary">{secondary}</div>
            </aside>
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      ref={root}
      className="review-layout has-secondary"
      style={{
        gridTemplateColumns: `minmax(520px, ${width}fr) 12px minmax(320px, ${100 - width}fr)`,
      }}
    >
      <div className="review-primary">{primary}</div>
      <div
        className="panel-divider"
        role="separator"
        aria-label="Độ rộng nội dung"
        aria-orientation="vertical"
        aria-valuemin={45}
        aria-valuemax={70}
        aria-valuenow={Math.round(width)}
        tabIndex={0}
        onKeyDown={(event) => {
          const change =
            event.key === "ArrowLeft" ? -5 : event.key === "ArrowRight" ? 5 : 0;
          if (change) {
            event.preventDefault();
            resize(width + change);
          }
          if (event.key === "Home" || event.key === "End") {
            event.preventDefault();
            resize(event.key === "Home" ? 45 : 70);
          }
        }}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (
            !event.currentTarget.hasPointerCapture(event.pointerId) ||
            !root.current
          )
            return;
          const box = root.current.getBoundingClientRect();
          resize(((event.clientX - box.left) / box.width) * 100);
        }}
        onPointerUp={(event) => {
          if (event.currentTarget.hasPointerCapture(event.pointerId))
            event.currentTarget.releasePointerCapture(event.pointerId);
        }}
      >
        <span />
      </div>
      <aside className="review-secondary">{secondary}</aside>
    </div>
  );
}
