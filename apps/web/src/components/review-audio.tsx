import { Button } from "@/components/ui/button";
import { Headphones, X } from "lucide-react";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

interface AudioSelection {
  url: string;
  title: string;
  range?: string;
  start?: number;
  end?: number;
}
const AudioContext = createContext<{
  play: (selection: AudioSelection) => void;
  stop: () => void;
}>({ play: () => {}, stop: () => {} });
export const useReviewAudio = () => useContext(AudioContext).play;
export const useStopReviewAudio = () => useContext(AudioContext).stop;

export function ReviewAudioProvider({ children }: { children: ReactNode }) {
  const [selection, setSelection] = useState<
    (AudioSelection & { nonce: number; target: HTMLElement | null }) | null
  >(null);
  const [message, setMessage] = useState("");
  const player = useRef<HTMLAudioElement>(null);
  useEffect(() => {
    const element = player.current;
    if (!element || !selection) return;
    setMessage("");
    const ready = () => {
      element.currentTime = selection.start || 0;
      void element
        .play()
        .catch(() => setMessage("Nhấn phát để nghe đoạn đã chọn."));
    };
    element.addEventListener("loadedmetadata", ready, { once: true });
    element.load();
    return () => {
      element.pause();
      element.removeEventListener("loadedmetadata", ready);
    };
  }, [selection]);
  useEffect(() => {
    if (!selection?.target) return;
    const observer = new MutationObserver(() => {
      if (!selection.target?.isConnected) setSelection(null);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [selection]);
  const controls = selection && (
    <section className="review-player" aria-label="Nghe lại nguồn âm thanh">
      <div className="player-caption">
        <Headphones size={18} />
        <div>
          <strong>{selection.title}</strong>
          <span>{selection.range || "Âm thanh gốc"}</span>
        </div>
      </div>
      <audio
        ref={player}
        controls
        preload="metadata"
        src={selection.url}
        aria-label={selection.title}
        onPlay={(event) => {
          if (
            event.currentTarget.currentTime < (selection.start || 0) ||
            (selection.end != null &&
              event.currentTarget.currentTime >= selection.end)
          )
            event.currentTarget.currentTime = selection.start || 0;
        }}
        onTimeUpdate={(event) => {
          if (
            selection.end != null &&
            event.currentTarget.currentTime >= selection.end
          )
            event.currentTarget.pause();
        }}
        onError={() =>
          setMessage("Không tải được audio. Hãy chọn lại đoạn hoặc thử lại.")
        }
      />
      <Button
        variant="ghost"
        size="icon"
        aria-label="Đóng trình nghe"
        onClick={() => setSelection(null)}
      >
        <X size={18} />
      </Button>
      {message && <p role="status">{message}</p>}
    </section>
  );
  return (
    <AudioContext.Provider
      value={{
        play: (value) =>
          setSelection({
            ...value,
            nonce: Date.now(),
            target:
              document.activeElement?.closest<HTMLElement>('[role="dialog"]') ||
              null,
          }),
        stop: () => setSelection(null),
      }}
    >
      {children}
      {selection?.target?.isConnected
        ? createPortal(controls, selection.target)
        : controls}
    </AudioContext.Provider>
  );
}
