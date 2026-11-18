import { Modal } from "@/components/common";
import { Button } from "@/components/ui/button";
import { useEffect, useRef, useState } from "react";
import { useBlocker } from "react-router-dom";

export function useUnsavedForm(dirty: boolean) {
  const allowed = useRef(false);
  const [close, setClose] = useState<(() => void) | null>(null);
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty &&
      !allowed.current &&
      currentLocation.pathname + currentLocation.search !==
        nextLocation.pathname + nextLocation.search,
  );
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty && !allowed.current) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function cancel() {
    setClose(null);
    if (blocker.state === "blocked") blocker.reset();
  }
  return {
    allowNavigation: () => {
      allowed.current = true;
    },
    requestClose: (action: () => void) =>
      dirty ? setClose(() => action) : action(),
    dialog: (
      <Modal
        open={!!close || blocker.state === "blocked"}
        onOpenChange={(open) => !open && cancel()}
        title="Thay đổi chưa lưu"
        description="Bạn có muốn rời phần đang sửa? Các thay đổi chưa lưu sẽ bị bỏ."
      >
        <div className="dialog-actions">
          <Button variant="outline" onClick={cancel}>
            Tiếp tục sửa
          </Button>
          <Button
            onClick={() => {
              if (blocker.state === "blocked") blocker.proceed();
              else close?.();
              setClose(null);
            }}
          >
            Bỏ thay đổi và rời
          </Button>
        </div>
      </Modal>
    ),
  };
}
