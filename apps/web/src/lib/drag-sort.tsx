import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { createPortal } from "react-dom";

export type SortItem = {
  kind: "clip" | "asset" | "file" | "track";
  id: string;
  label: string;
};
export type SortDrop = {
  target: HTMLElement;
  x: number;
  y: number;
  after: boolean;
};

/** Pointer capture supports mouse, pen and touch; changes are committed once on release. */
export function useDragSort(
  scope: string,
  disabled: boolean,
  onDrop: (item: SortItem, drop: SortDrop) => void,
) {
  const latest = useRef({ disabled, onDrop });
  latest.current = { disabled, onDrop };
  const session = useRef<{ cancel: () => void } | null>(null);
  const ghost = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<SortItem | null>(null);
  useEffect(() => () => session.current?.cancel(), []);

  function start(event: ReactPointerEvent<HTMLElement>, item: SortItem) {
    if (
      latest.current.disabled ||
      session.current ||
      !event.isPrimary ||
      event.button !== 0
    )
      return;
    const origin = event.target as HTMLElement;
    const handle = origin.closest("[data-drag-handle]");
    if (
      !handle &&
      (event.pointerType !== "mouse" ||
        origin.closest("button,input,select,textarea,a,audio"))
    )
      return;
    event.preventDefault();
    event.stopPropagation();
    const source = event.currentTarget;
    const pointerId = event.pointerId;
    const initial = { x: event.clientX, y: event.clientY };
    let point = initial;
    let dragging = false;
    let frame = 0;
    let marked: HTMLElement | null = null;
    let side = "";
    source.setPointerCapture(pointerId);

    function hit(): SortDrop | null {
      const element = document.elementFromPoint(point.x, point.y);
      const selector =
        item.kind === "file"
          ? "[data-sort-file]"
          : item.kind === "track"
            ? "[data-sort-track]"
            : "[data-drop-track]";
      let target = element?.closest<HTMLElement>(selector);
      // A gap between rows is also a valid insertion point, including while
      // auto-scrolling moves the rows beneath a stationary finger.
      const list = element?.closest<HTMLElement>("[data-sort-list]");
      if (
        !target &&
        list?.dataset.sortScope === scope &&
        list.dataset.sortList === item.kind
      ) {
        let distance = Infinity;
        for (const row of list.querySelectorAll<HTMLElement>(selector)) {
          const rect = row.getBoundingClientRect();
          if (point.x < rect.left || point.x > rect.right) continue;
          const next = Math.max(rect.top - point.y, point.y - rect.bottom, 0);
          if (next < distance) {
            target = row;
            distance = next;
          }
        }
      }
      if (!target || target.dataset.sortScope !== scope) return null;
      const rect = target.getBoundingClientRect();
      return {
        target,
        ...point,
        after:
          target.dataset.sortAxis === "x"
            ? point.x >= rect.left + rect.width / 2
            : point.y >= rect.top + rect.height / 2,
      };
    }
    function unmark() {
      if (marked)
        marked.classList.remove("sort-before", "sort-after", "sort-over");
      marked = null;
      side = "";
    }
    function feedback() {
      if (ghost.current)
        ghost.current.style.transform = `translate3d(${point.x + 14}px,${point.y + 14}px,0)`;
      const destination = hit();
      const nextSide = destination?.target.dataset.sortItem
        ? destination.after
          ? "sort-after"
          : "sort-before"
        : "sort-over";
      if (marked !== destination?.target || side !== nextSide) {
        unmark();
        if (destination) {
          marked = destination.target;
          side = nextSide;
          marked.classList.add(side);
        }
      }
    }
    function autoScroll() {
      if (!dragging) return;
      const hitElement = document.elementFromPoint(point.x, point.y);
      const lane = hitElement?.closest<HTMLElement>(".timeline-scroll");
      if (lane) {
        const rect = lane.getBoundingClientRect();
        if (point.x > rect.right - 36) lane.scrollLeft += 12;
        if (point.x < rect.left + 36) lane.scrollLeft -= 12;
      }
      if (point.y < 70) window.scrollBy(0, -12);
      if (point.y > window.innerHeight - 70) window.scrollBy(0, 12);
      feedback();
      frame = requestAnimationFrame(autoScroll);
    }
    function cleanup() {
      cancelAnimationFrame(frame);
      unmark();
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      window.removeEventListener("pointercancel", cancel, true);
      window.removeEventListener("keydown", key, true);
      window.removeEventListener("blur", cancel);
      if (source.hasPointerCapture(pointerId))
        source.releasePointerCapture(pointerId);
      document.body.classList.remove("is-sorting");
      session.current = null;
      setActive(null);
    }
    function move(e: PointerEvent) {
      if (e.pointerId !== pointerId) return;
      point = { x: e.clientX, y: e.clientY };
      if (
        !dragging &&
        Math.hypot(point.x - initial.x, point.y - initial.y) >= 6
      ) {
        dragging = true;
        setActive(item);
        document.body.classList.add("is-sorting");
        frame = requestAnimationFrame(autoScroll);
      }
      if (dragging) {
        e.preventDefault();
        feedback();
      }
    }
    function up(e: PointerEvent) {
      if (e.pointerId !== pointerId) return;
      point = { x: e.clientX, y: e.clientY };
      const destination = dragging && !latest.current.disabled ? hit() : null;
      cleanup();
      if (destination) latest.current.onDrop(item, destination);
    }
    function cancel() {
      cleanup();
    }
    function key(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        cancel();
      }
    }
    session.current = { cancel };
    window.addEventListener("pointermove", move, {
      capture: true,
      passive: false,
    });
    window.addEventListener("pointerup", up, true);
    window.addEventListener("pointercancel", cancel, true);
    window.addEventListener("keydown", key, true);
    window.addEventListener("blur", cancel);
  }
  return {
    start,
    active,
    overlay: active
      ? createPortal(
          <div ref={ghost} className="sort-ghost" role="status">
            Đang di chuyển: {active.label}
          </div>,
          document.body,
        )
      : null,
  };
}

/** Move a row before/after a target without changing the original array. */
export function moveItem<T>(
  items: T[],
  from: number,
  target: number,
  after: boolean,
) {
  if (
    from < 0 ||
    target < 0 ||
    from >= items.length ||
    target >= items.length ||
    from === target
  )
    return items;
  const next = [...items];
  const [item] = next.splice(from, 1);
  const insert = target + (after ? 1 : 0) - (from < target ? 1 : 0);
  next.splice(insert, 0, item);
  return next;
}
