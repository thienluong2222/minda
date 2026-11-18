import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp } from "lucide-react";
import { useState } from "react";
import { ErrorBox, Loading, Modal, useWork } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, patch } from "@/lib/api";
import { nodeStyle } from "./graph-data";

interface DraftItem {
  item_id: string;
  text: string;
  role: string;
  priority: "required" | "optional";
  included: boolean;
}

interface DraftSection {
  section_id: string;
  title: string;
  items: DraftItem[];
}

interface Draft {
  version_id: string;
  plan_id: string;
  revision: number;
  sections: DraftSection[];
}

function EditorForm({ base, draft, close }: { base: string; draft: Draft; close: () => void }) {
  const [sections, setSections] = useState(draft.sections);
  const [activeId, setActiveId] = useState(sections[0]?.section_id);
  const { busy, work } = useWork();
  const section = sections.find((item) => item.section_id === activeId);
  const dirty = JSON.stringify(sections) !== JSON.stringify(draft.sections);

  function updateSection(changed: DraftSection) {
    setSections((previous) => previous.map((item) =>
      item.section_id === changed.section_id ? changed : item
    ));
  }

  function moveItem(item: DraftItem, destination: string) {
    setSections((previous) => previous.map((group) =>
      group.section_id === activeId
        ? { ...group, items: group.items.filter((row) => row.item_id !== item.item_id) }
        : group.section_id === destination ? { ...group, items: [...group.items, item] } : group
    ));
  }

  function changeOrder(index: number, direction: -1 | 1) {
    if (!section) return;
    const items = [...section.items];
    const target = index + direction;
    [items[index], items[target]] = [items[target], items[index]];
    updateSection({ ...section, items });
  }

  return (
    <form className="form-stack" onSubmit={(event) => {
      event.preventDefault();
      void work(async () => {
        await patch(base, {
          version_id: draft.version_id,
          plan_id: draft.plan_id,
          revision: draft.revision,
          sections: sections.map((group) => ({
            section_id: group.section_id,
            title: group.title,
            items: group.items.map(({ item_id, priority, included }) => ({ item_id, priority, included })),
          })),
        });
        close();
      }, "Đã xếp tác vụ viết biên bản");
    }}>
      <label>
        Mục đang chỉnh
        <select value={activeId} onChange={(event) => setActiveId(event.target.value)}>
          {sections.map((group) => (
            <option key={group.section_id} value={group.section_id}>{group.title}</option>
          ))}
        </select>
      </label>
      {section && (
        <>
          <label>
            Tên mục
            <Input value={section.title} maxLength={160} onChange={(event) =>
              updateSection({ ...section, title: event.target.value })
            } />
          </label>
          <ol className="minutes-outline-items minutes-outline-edit-list">
            {section.items.map((item, index) => (
              <li key={item.item_id}>
                <p><strong>{nodeStyle(item.role).label}</strong> · {item.text}</p>
                <div className="minutes-outline-edit-controls">
                  <Button type="button" variant="ghost" size="icon" aria-label={`Đưa ý ${index + 1} lên`}
                    disabled={busy || index === 0} onClick={() => changeOrder(index, -1)}>
                    <ArrowUp size={16} />
                  </Button>
                  <Button type="button" variant="ghost" size="icon" aria-label={`Đưa ý ${index + 1} xuống`}
                    disabled={busy || index === section.items.length - 1} onClick={() => changeOrder(index, 1)}>
                    <ArrowDown size={16} />
                  </Button>
                  <select aria-label={`Mức ưu tiên của ý ${index + 1}`}
                    value={item.included ? item.priority : "excluded"}
                    onChange={(event) => {
                      const choice = event.target.value;
                      const updated: DraftItem = {
                        ...item,
                        priority: choice === "required" ? "required" : "optional",
                        included: choice !== "excluded",
                      };
                      updateSection({ ...section, items: section.items.map((row, i) => i === index ? updated : row) });
                    }}>
                    <option value="required">Bắt buộc</option>
                    <option value="optional">Có thể lược · đang giữ</option>
                    <option value="excluded">Lược khỏi bản viết</option>
                  </select>
                  {sections.length > 1 && (
                    <select aria-label={`Chuyển ý ${index + 1} sang mục`} value=""
                      onChange={(event) => moveItem(item, event.target.value)}>
                      <option disabled value="">Chuyển sang mục…</option>
                      {sections.filter((group) => group.section_id !== activeId).map((group) => (
                        <option key={group.section_id} value={group.section_id}>{group.title}</option>
                      ))}
                    </select>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
      <Button type="submit" disabled={!dirty || busy || sections.some((group) => !group.title.trim())}>
        Tạo bản mới từ dàn ý
      </Button>
    </form>
  );
}

export function OutlineEditor({ meetingId, close }: { meetingId: string; close: () => void }) {
  const base = `/meetings/${meetingId}/minutes/outline`;
  const draft = useQuery({
    queryKey: ["outline-draft", meetingId],
    queryFn: ({ signal }) => api<Draft>(`${base}/draft`, { signal }),
    gcTime: 0,
  });
  return (
    <Modal wide open onOpenChange={(open) => { if (!open) close(); }} title="Chỉnh dàn ý biên bản"
      description="Đổi thứ tự, chuyển mục hoặc chọn ý cần giữ. Hệ thống sẽ viết lại các mục bạn chỉnh.">
      {draft.isPending && <Loading />}
      <ErrorBox error={draft.error} onRetry={() => void draft.refetch()} />
      {draft.data && <EditorForm base={base} draft={draft.data} close={close} />}
    </Modal>
  );
}
