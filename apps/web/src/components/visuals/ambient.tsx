import {
  Component,
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

const Scene = lazy(() => import("./scenes"));

class GraphicsBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

export function AmbientVisual({ kind = "wave" }: { kind?: "wave" | "layers" }) {
  const host = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [reduced, setReduced] = useState(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const [foreground, setForeground] = useState(!document.hidden);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const motion = () => setReduced(media.matches);
    const focus = () => setForeground(!document.hidden);
    const observer = new IntersectionObserver(
      ([entry]) => setVisible(entry.isIntersecting),
      { rootMargin: "120px" },
    );
    if (host.current) observer.observe(host.current);
    media.addEventListener("change", motion);
    document.addEventListener("visibilitychange", focus);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", motion);
      document.removeEventListener("visibilitychange", focus);
    };
  }, []);
  return (
    <div
      ref={host}
      className={`ambient-visual ambient-${kind}`}
      aria-hidden="true"
    >
      {kind === "layers" ? (
        <img
          className="ambient-poster"
          src="/illustrations/evidence.webp"
          alt=""
          width="1200"
          height="900"
        />
      ) : (
        <svg
          className="wave-poster"
          viewBox="0 0 1440 900"
          preserveAspectRatio="none"
        >
          {Array.from({ length: 14 }, (_, i) => (
            <path
              key={i}
              d={`M-40 ${330 + i * 14} C220 ${100 + i * 20} 340 ${700 - i * 12} 650 ${460 + i * 7} S1100 ${180 + i * 24} 1480 ${400 + i * 13}`}
            />
          ))}
        </svg>
      )}
      {!reduced && visible && (
        <GraphicsBoundary>
          <Suspense fallback={null}>
            <Scene kind={kind} active={visible && foreground} />
          </Suspense>
        </GraphicsBoundary>
      )}
    </div>
  );
}

export function Reveal({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          ref.current?.classList.add("is-revealed");
          observer.disconnect();
        }
      },
      { threshold: 0.08 },
    );
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return (
    <div ref={ref} className={`reveal ${className}`}>
      {children}
    </div>
  );
}
