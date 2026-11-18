import { useReviewAudio } from "@/components/review-audio";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Empty,
  ErrorBox,
  Loading,
  Modal,
  Notice,
  Panel,
} from "@/components/common";
import { ApiError, api, post, size, time } from "@/lib/api";
import {
  getTimeline,
  getTimelineAlignment,
  updateTimeline,
  uploadTimelineFiles,
} from "@/lib/timeline";
import type {
  Capabilities,
  Meeting,
  TimelineClip,
  TimelineInterval,
  TimelineOperation,
  TimelineTrack,
  TimelineUserPlacement,
} from "@/lib/types";
import { useUnsavedForm } from "@/lib/unsaved";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  AudioLines,
  GripVertical,
  Headphones,
  Plus,
  Settings2,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { useState } from "react";
import {
  moveItem,
  useDragSort,
  type SortDrop,
  type SortItem,
} from "@/lib/drag-sort";

const id = () => "item-" + crypto.randomUUID();
type Editor = {
  clip: TimelineClip;
  revision: number;
  track: string;
  start: string;
  end: string;
  kind: "anchored" | "sequential";
  at: string;
  gap: string;
};

export function SourcesTimeline({ meeting }: { meeting: Meeting }) {
  const query = useQueryClient(),
    listen = useReviewAudio();
  const data = useQuery({
    queryKey: ["timeline", meeting.id],
    queryFn: () => getTimeline(meeting.id),
  });
  const caps = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<Capabilities>("/capabilities"),
  });
  const alignment = useQuery({
    queryKey: [
      "alignment",
      meeting.id,
      data.data?.timeline_hash,
      data.data?.last_alignment?.id,
    ],
    queryFn: () => getTimelineAlignment(data.data!),
    enabled: !!data.data,
  });
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<Error | null>(null),
    [message, setMessage] = useState("");
  const [name, setName] = useState(""),
    [mode, setMode] = useState<"order" | "time">("order"),
    [zoom, setZoom] = useState(1);
  const [editor, setEditor] = useState<Editor | null>(null),
    [rangeDirty, setRangeDirty] = useState(false);
  const [interval, setInterval] = useState<{
    revision: number;
    id: string;
    kind: TimelineInterval["kind"];
    label: string;
    start: string;
    end: string;
  } | null>(null);
  const [intervalDirty, setIntervalDirty] = useState(false),
    [selected, setSelected] = useState<string | null>(null);
  const [rename, setRename] = useState<{
    track: TimelineTrack;
    revision: number;
    name: string;
  } | null>(null);
  const [removeTrack, setRemoveTrack] = useState<TimelineTrack | null>(null);
  const [removeAsset, setRemoveAsset] = useState<string | null>(null);
  const [origin, setOrigin] = useState("");
  const guard = useUnsavedForm(
    rangeDirty ||
      intervalDirty ||
      !!name.trim() ||
      !!origin ||
      !!(rename && rename.name !== rename.track.name),
  );
  const view = data.data;
  const disabled = busy || !!meeting.active_job || meeting.trashed;
  const sortScope = "sources-" + meeting.id;
  const sort = useDragSort(sortScope, disabled, handleSortDrop);
  async function apply(
    operations: TimelineOperation[],
    revision = view!.revision,
  ) {
    setBusy(true);
    setError(null);
    setMessage("Đang lưu bố cục…");
    try {
      const result = await updateTimeline(meeting.id, revision, operations);
      query.setQueryData(["timeline", meeting.id], result);
      await query.invalidateQueries({ queryKey: ["meeting", meeting.id] });
      setMessage("Đã lưu bố cục");
      return true;
    } catch (caught) {
      const problem = caught as Error;
      if (problem instanceof ApiError && problem.status === 409) {
        await data.refetch();
        setError(
          new Error(
            "Bố cục đã thay đổi. Hãy kiểm tra bản mới trước khi thao tác lại; nội dung đang nhập vẫn được giữ.",
          ),
        );
      } else setError(problem);
      setMessage("Chưa lưu được bố cục");
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function upload(files: File[], track?: string) {
    if (!files.length || !view) return;
    setBusy(true);
    setError(null);
    setMessage("Đang tải file âm thanh…");
    try {
      await uploadTimelineFiles(meeting.id, view.revision, files, track);
      await Promise.all([
        data.refetch(),
        query.invalidateQueries({ queryKey: ["meeting", meeting.id] }),
      ]);
      setMessage("Đã tải file. Xếp từng file vào nguồn ghi tương ứng.");
    } catch (caught) {
      setError(caught as Error);
      setMessage("Tải file chưa thành công");
    } finally {
      setBusy(false);
    }
  }
  if (data.isPending) return <Loading />;
  if (!view) return <ErrorBox error={data.error} />;
  const assets = new Map(view.assets.map((asset) => [asset.id, asset]));
  const clips = new Map(view.timeline.clips.map((clip) => [clip.id, clip]));
  const positions = Object.values(view.resolved_positions).filter(
    (p) => p.start_ms != null,
  );
  const axisStart = Math.min(0, ...positions.map((p) => p.start_ms!));
  const axisEnd = Math.max(60000, ...positions.map((p) => p.end_ms || 0));
  const axisSpan = axisEnd - axisStart;
  const selectedClip = selected ? clips.get(selected) : undefined;
  const selectedAsset = selectedClip
    ? assets.get(selectedClip.asset_id)
    : undefined;
  function edit(clip: TimelineClip, track: string) {
    setError(null);
    setEditor({
      clip,
      revision: view!.revision,
      track,
      start: String(clip.source_in_ms / 1000),
      end: String(clip.source_out_ms / 1000),
      kind: clip.placement.kind,
      at:
        clip.placement.kind === "anchored"
          ? String(clip.placement.start_ms / 1000)
          : "0",
      gap:
        clip.placement.kind === "sequential" &&
        clip.placement.gap_before_ms != null
          ? String(clip.placement.gap_before_ms / 1000)
          : "",
    });
    setRangeDirty(false);
  }
  function handleSortDrop(item: SortItem, destination: SortDrop) {
    if (!view || disabled) return;
    if (item.kind === "track") {
      const target = destination.target.dataset.sortTrack;
      const tracks = view.timeline.tracks;
      const from = tracks.findIndex((track) => track.id === item.id);
      const to = tracks.findIndex((track) => track.id === target);
      const reordered = moveItem(tracks, from, to, destination.after);
      if (
        reordered !== tracks &&
        reordered.some((track, index) => track.id !== tracks[index].id)
      ) {
        void apply([
          {
            op: "reorder_tracks",
            track_ids: reordered.map((track) => track.id),
          },
        ]);
      }
      return;
    }
    const clipId = item.kind === "clip" ? item.id : "";
    const assetId = item.kind === "asset" ? item.id : "";
    if (!clips.has(clipId) && !assets.has(assetId)) return;
    const track = view.timeline.tracks.find(
      (track) => track.id === destination.target.dataset.dropTrack,
    );
    if (!track) return;
    const targetId = destination.target.dataset.sortItem;
    if (clipId === targetId && mode === "order") return;
    let before: string | undefined;
    let placement: TimelineUserPlacement | undefined;
    if (mode === "time") {
      const lane = destination.target.closest<HTMLElement>(".track-lane");
      if (!lane) {
        setError(new Error("Kéo đoạn lên trục thời gian để đặt mốc."));
        return;
      }
      const rect = lane.getBoundingClientRect();
      const at =
        Math.round(
          (axisStart + ((destination.x - rect.left) / rect.width) * axisSpan) /
            1000,
        ) * 1000;
      placement = {
        kind: "anchored",
        start_ms: at,
        origin: "user",
        status: "declared",
      };
      before = track.clip_ids.find(
        (key) =>
          key !== clipId &&
          (view.resolved_positions[key]?.start_ms ?? Infinity) >= at,
      );
    } else {
      const remaining = track.clip_ids.filter((key) => key !== clipId);
      if (targetId && remaining.includes(targetId)) {
        const index = remaining.indexOf(targetId);
        before = destination.after ? remaining[index + 1] : targetId;
      } else {
        const next = Array.from(
          destination.target.querySelectorAll<HTMLElement>(".timeline-clip"),
        ).find(
          (card) =>
            card.dataset.sortItem !== clipId &&
            destination.x <
              card.getBoundingClientRect().left +
                card.getBoundingClientRect().width / 2,
        );
        before = next?.dataset.sortItem;
      }
      if (clipId && track.clip_ids.includes(clipId)) {
        const reordered = [...remaining];
        reordered.splice(
          before ? reordered.indexOf(before) : reordered.length,
          0,
          clipId,
        );
        if (reordered.every((key, index) => key === track.clip_ids[index]))
          return;
      }
    }
    void apply([
      clipId
        ? {
            op: "move_clip",
            clip_id: clipId,
            track_id: track.id,
            before_clip_id: before,
            placement,
          }
        : {
            op: "add_clip",
            id: id(),
            asset_id: assetId,
            track_id: track.id,
            before_clip_id: before,
            placement,
          },
    ]);
  }
  const renderClip = (
    clip: TimelineClip,
    track: TimelineTrack,
    index: number,
    positioned = false,
  ) => {
    const asset = assets.get(clip.asset_id),
      position = view.resolved_positions[clip.id];
    const unknown =
      clip.placement.kind === "sequential" &&
      clip.placement.gap_before_ms == null &&
      index > 0;
    return (
      <div
        key={clip.id}
        className={"timeline-clip" + (selected === clip.id ? " selected" : "")}
        data-sort-scope={sortScope}
        data-drop-track={track.id}
        data-sort-item={clip.id}
        data-sort-axis="x"
        onPointerDown={(event) =>
          sort.start(event, {
            kind: "clip",
            id: clip.id,
            label: asset?.name || "File âm thanh",
          })
        }
        style={
          positioned
            ? {
                left: `${((position.start_ms! - axisStart) / axisSpan) * 100}%`,
                width: `${((clip.source_out_ms - clip.source_in_ms) / axisSpan) * 100}%`,
              }
            : undefined
        }
      >
        <div className="clip-main">
          <button
            type="button"
            className="drag-handle"
            data-drag-handle
            disabled={disabled}
            aria-label={
              "Kéo " + (asset?.name || "file âm thanh") + " để sắp xếp"
            }
            onPointerDown={(event) =>
              sort.start(event, {
                kind: "clip",
                id: clip.id,
                label: asset?.name || "File âm thanh",
              })
            }
          >
            <GripVertical size={16} />
          </button>
          <button
            className="clip-select"
            type="button"
            aria-pressed={selected === clip.id}
            onClick={() => setSelected(clip.id)}
          >
            <span>
              <strong>{asset?.name || "File âm thanh"}</strong>
              <small>
                {time((clip.source_out_ms - clip.source_in_ms) / 1000)}
                {position?.start_ms != null
                  ? " · " + time(position.start_ms / 1000)
                  : " · Chưa có mốc"}
              </small>
            </span>
          </button>
        </div>
        <div className="clip-tags">
          {unknown && <span className="timing-label">Khoảng nghỉ chưa rõ</span>}
          {clip.placement.kind === "anchored" && (
            <span className="timing-label">Mốc do bạn đặt</span>
          )}
          {clip.placement.kind === "sequential" &&
            clip.placement.gap_before_ms != null && (
              <span className="timing-label">
                Cách phần trước {time(clip.placement.gap_before_ms / 1000)}
              </span>
            )}
        </div>
        <div className="clip-actions">
          <Button
            size="icon"
            variant="ghost"
            aria-label={"Đưa " + asset?.name + " lên trước"}
            disabled={disabled || index === 0}
            onClick={() =>
              void apply([
                {
                  op: "move_clip",
                  clip_id: clip.id,
                  track_id: track.id,
                  before_clip_id: track.clip_ids[index - 1],
                },
              ])
            }
          >
            <ArrowUp size={14} />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            aria-label={"Đưa " + asset?.name + " ra sau"}
            disabled={disabled || index === track.clip_ids.length - 1}
            onClick={() =>
              void apply([
                {
                  op: "move_clip",
                  clip_id: clip.id,
                  track_id: track.id,
                  before_clip_id: track.clip_ids[index + 2],
                },
              ])
            }
          >
            <ArrowDown size={14} />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={disabled}
            onClick={() => edit(clip, track.id)}
          >
            <Settings2 size={14} />
            Sắp xếp & mốc
          </Button>
        </div>
      </div>
    );
  };
  return (
    <>
      {sort.overlay}
      <div className="source-toolbar">
        <div>
          <h2>Nguồn âm thanh</h2>
          <p className="muted">
            {view.assets.length} file · {view.timeline.tracks.length} nguồn ghi
          </p>
        </div>
        <label className="upload-button">
          <UploadCloud size={17} />
          <span>{busy ? "Đang tải…" : "Tải file âm thanh"}</span>
          <input
            type="file"
            multiple
            disabled={disabled}
            accept=".wav,.mp3,.m4a,.aac,.flac,.ogg,.webm,.mp4"
            onChange={(event) => {
              void upload(Array.from(event.target.files || []));
              event.target.value = "";
            }}
          />
        </label>
      </div>
      <p className="upload-limits">
        Tối đa {time(caps.data?.max_audio_duration_sec || 7200)} mỗi file ·{" "}
        {size(caps.data?.max_upload_bytes || 1e9)}/file ·{" "}
        {caps.data?.max_sources || 8} nguồn ghi
      </p>
      <ErrorBox error={error || data.error} />
      {(meeting.transcript_stale || meeting.minutes_stale) && (
        <Notice>
          Đầu vào đã thay đổi. Hãy xử lý lại để cập nhật lời chép và biên bản.
        </Notice>
      )}
      {view.alignment_stale && (
        <Notice>
          Kết quả căn thời gian trước đây không còn khớp bố cục đang lưu.
        </Notice>
      )}
      <p className="save-status" role="status">
        {message}
      </p>
      {!!view.timeline.unassigned_asset_ids.length && (
        <Panel
          title={
            "File chưa xếp (" + view.timeline.unassigned_asset_ids.length + ")"
          }
        >
          <div className="unassigned-files">
            {view.timeline.unassigned_asset_ids.map((key) => {
              const asset = assets.get(key);
              if (!asset) return null;
              return (
                <div
                  className="unassigned-file"
                  key={key}
                  onPointerDown={(event) =>
                    sort.start(event, {
                      kind: "asset",
                      id: key,
                      label: asset.name,
                    })
                  }
                >
                  <button
                    type="button"
                    className="drag-handle"
                    data-drag-handle
                    disabled={disabled}
                    aria-label={"Kéo " + asset.name + " vào nguồn ghi"}
                    onPointerDown={(event) =>
                      sort.start(event, {
                        kind: "asset",
                        id: key,
                        label: asset.name,
                      })
                    }
                  >
                    <GripVertical size={16} />
                  </button>
                  <div>
                    <strong>{asset.name}</strong>
                    <small>
                      {time(asset.duration_sec || 0)} ·{" "}
                      {size(asset.artifact?.size_bytes || 0)}
                    </small>
                  </div>
                  <select
                    aria-label={"Xếp nguồn cho " + asset.name}
                    value=""
                    disabled={disabled}
                    onChange={(event) => {
                      if (event.target.value)
                        void apply([
                          {
                            op: "add_clip",
                            id: id(),
                            asset_id: key,
                            track_id: event.target.value,
                          },
                        ]);
                    }}
                  >
                    <option value="">Chọn nguồn…</option>
                    {view.timeline.tracks.map((track) => (
                      <option key={track.id} value={track.id}>
                        {track.name}
                      </option>
                    ))}
                  </select>
                  <Button
                    variant="ghost"
                    size="icon"
                    disabled={disabled}
                    aria-label={"Bỏ file " + asset.name + " khỏi cuộc họp"}
                    onClick={() => setRemoveAsset(key)}
                  >
                    <X size={15} />
                  </Button>
                </div>
              );
            })}
          </div>
        </Panel>
      )}
      <section
        className="timeline-panel"
        aria-label="Bố cục các nguồn âm thanh"
      >
        <div className="timeline-tools">
          <div
            className="segmented-control"
            role="group"
            aria-label="Cách xem nguồn âm thanh"
          >
            <button
              aria-pressed={mode === "order"}
              className={mode === "order" ? "active" : ""}
              onClick={() => setMode("order")}
            >
              Thứ tự các phần
            </button>
            <button
              aria-pressed={mode === "time"}
              className={mode === "time" ? "active" : ""}
              onClick={() => setMode("time")}
            >
              Thời gian đã đặt
            </button>
          </div>
          {mode === "time" && (
            <label>
              Thu phóng{" "}
              <select
                aria-label="Thu phóng timeline"
                value={zoom}
                onChange={(event) => setZoom(Number(event.target.value))}
              >
                <option value={1}>100%</option>
                <option value={2}>200%</option>
                <option value={4}>400%</option>
              </select>
            </label>
          )}
        </div>
        {mode === "time" && (
          <p className="context-hint">
            Kéo đoạn để đặt thời điểm do bạn khai báo. Phần chưa có mốc vẫn được
            giữ riêng bên dưới.
          </p>
        )}
        {view.timeline.tracks.map((track, trackIndex) => (
          <section
            className="source-track"
            key={track.id}
            aria-label={track.name}
            data-sort-scope={sortScope}
            data-sort-track={track.id}
            data-sort-item={track.id}
            data-sort-axis="y"
          >
            <header>
              <div className="track-heading">
                <button
                  type="button"
                  className="drag-handle"
                  data-drag-handle
                  disabled={disabled}
                  aria-label={"Kéo nguồn " + track.name + " để đổi thứ tự"}
                  onPointerDown={(event) =>
                    sort.start(event, {
                      kind: "track",
                      id: track.id,
                      label: track.name,
                    })
                  }
                >
                  <GripVertical size={16} />
                </button>
                <AudioLines size={18} />
                <h3>{track.name}</h3>
                <span>{track.clip_ids.length} phần</span>
              </div>
              <div className="row">
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={"Đưa nguồn " + track.name + " lên"}
                  disabled={disabled || trackIndex === 0}
                  onClick={() => {
                    const order = view.timeline.tracks.map((t) => t.id);
                    [order[trackIndex - 1], order[trackIndex]] = [
                      order[trackIndex],
                      order[trackIndex - 1],
                    ];
                    void apply([{ op: "reorder_tracks", track_ids: order }]);
                  }}
                >
                  <ArrowUp size={14} />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={disabled}
                  onClick={() =>
                    setRename({
                      track,
                      revision: view.revision,
                      name: track.name,
                    })
                  }
                >
                  Đổi tên
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={"Bỏ hàng " + track.name}
                  disabled={disabled}
                  onClick={() => setRemoveTrack(track)}
                >
                  <Trash2 size={15} />
                </Button>
              </div>
            </header>
            <div className="timeline-scroll">
              <div
                className={
                  "track-lane " +
                  (mode === "time" ? "timed-lane" : "ordered-lane")
                }
                style={mode === "time" ? { minWidth: 720 * zoom } : undefined}
                data-sort-scope={sortScope}
                data-drop-track={track.id}
                data-sort-axis="x"
              >
                {mode === "time" && (
                  <div className="time-ruler" aria-hidden="true">
                    {Array.from({ length: 5 }, (_, i) => (
                      <span key={i}>
                        {time((axisStart + (axisSpan * i) / 4) / 1000)}
                      </span>
                    ))}
                  </div>
                )}
                {track.clip_ids
                  .filter(
                    (key) =>
                      mode !== "time" ||
                      view.resolved_positions[key]?.start_ms != null,
                  )
                  .map((key) =>
                    renderClip(
                      clips.get(key)!,
                      track,
                      track.clip_ids.indexOf(key),
                      mode === "time",
                    ),
                  )}
                {!track.clip_ids.length && (
                  <p className="track-empty">
                    Kéo file vào đây hoặc chọn nguồn trong danh sách file chưa
                    xếp.
                  </p>
                )}
              </div>
            </div>
            {mode === "time" &&
              track.clip_ids.some(
                (key) => view.resolved_positions[key]?.start_ms == null,
              ) && (
                <div className="unplaced-clips">
                  <span className="muted">Chưa có mốc trên trục chung</span>
                  <div>
                    {track.clip_ids
                      .filter(
                        (key) => view.resolved_positions[key]?.start_ms == null,
                      )
                      .map((key) =>
                        renderClip(
                          clips.get(key)!,
                          track,
                          track.clip_ids.indexOf(key),
                        ),
                      )}
                  </div>
                </div>
              )}
          </section>
        ))}
        {!view.timeline.tracks.length && (
          <Empty
            title="Thêm nguồn ghi đầu tiên"
            description="Mỗi thiết bị hoặc luồng ghi có một hàng; các file nối tiếp có thể cùng thuộc một nguồn."
          />
        )}
        <form
          className="add-source-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim())
              void apply([
                { op: "create_track", id: id(), name: name.trim() },
              ]).then((saved) => saved && setName(""));
          }}
        >
          <Input
            aria-label="Tên nguồn ghi mới"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={100}
            placeholder="Ví dụ: Điện thoại A"
            disabled={disabled}
          />
          <Button
            variant="outline"
            disabled={
              disabled ||
              !name.trim() ||
              view.timeline.tracks.length >= (caps.data?.max_sources || 8)
            }
          >
            <Plus size={16} />
            Thêm nguồn
          </Button>
        </form>
      </section>
      {selectedClip && selectedAsset && (
        <Panel className="clip-detail">
          <div className="row between">
            <h3>{selectedAsset.name}</h3>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Đóng chi tiết đoạn"
              onClick={() => setSelected(null)}
            >
              <X size={16} />
            </Button>
          </div>
          <p className="muted">
            Vùng file gốc: {time(selectedClip.source_in_ms / 1000)} –{" "}
            {time(selectedClip.source_out_ms / 1000)}
          </p>
          {selectedAsset.artifact && (
            <Button
              variant="outline"
              onClick={() =>
                listen({
                  url: selectedAsset.artifact!.url,
                  title: selectedAsset.name,
                  start: selectedClip.source_in_ms / 1000,
                  end: selectedClip.source_out_ms / 1000,
                  range: "Vùng audio gốc đã chọn",
                })
              }
            >
              <Headphones size={16} />
              Nghe đoạn gốc
            </Button>
          )}
          {!!alignment.data?.spans[selectedClip.id]?.length && (
            <details>
              <summary>Kết quả căn thời gian</summary>
              {alignment.data.spans[selectedClip.id].map((span, index) => (
                <p key={index}>
                  {time(span.start)}–{time(span.end)} trong đoạn →{" "}
                  {span.clock_id === "meeting" ? "Cuộc họp" : "Giờ cục bộ"}:{" "}
                  {time(
                    span.scale * span.start +
                      span.offset +
                      (span.clock_id === "meeting"
                        ? alignment.data!.meeting_origin_shift_sec
                        : 0),
                  )}{" "}
                  ·{" "}
                  {
                    {
                      acoustic: "Khớp âm thanh",
                      extrapolated: "Ước lượng — cần rà",
                      declared: "Mốc do bạn đặt",
                      reference: "Nguồn tham chiếu",
                      local: "Chưa có mốc chung",
                      sequential: "Khoảng cách đã khai báo",
                    }[span.origin]
                  }
                </p>
              ))}
            </details>
          )}
        </Panel>
      )}
      <details className="interval-manager">
        <summary>
          Phiên họp, khoảng nghỉ và phần ngoài biên bản (
          {view.timeline.intervals.length})
        </summary>
        {view.timeline.intervals.map((item) => (
          <div className="interval-row" key={item.id}>
            <div>
              <strong>
                {item.label ||
                  {
                    session: "Phiên họp",
                    break: "Giải lao",
                    excluded: "Ngoài biên bản",
                  }[item.kind]}
              </strong>
              <p>
                {item.start_ms != null
                  ? time(item.start_ms / 1000)
                  : "Theo phần ghi"}{" "}
                –{" "}
                {item.end_ms != null
                  ? time(item.end_ms / 1000)
                  : "Theo phần ghi"}
              </p>
            </div>
            <Button
              variant="ghost"
              disabled={disabled}
              onClick={() => {
                setInterval({
                  revision: view.revision,
                  id: item.id,
                  kind: item.kind,
                  label: item.label || "",
                  start:
                    item.start_ms != null ? String(item.start_ms / 1000) : "",
                  end: item.end_ms != null ? String(item.end_ms / 1000) : "",
                });
                setIntervalDirty(false);
              }}
            >
              Sửa mốc
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={"Bỏ khoảng " + (item.label || item.kind)}
              disabled={disabled}
              onClick={() =>
                void apply([{ op: "remove_interval", interval_id: item.id }])
              }
            >
              <Trash2 size={15} />
            </Button>
          </div>
        ))}
        <Button
          variant="outline"
          disabled={disabled}
          onClick={() => {
            setInterval({
              revision: view.revision,
              id: id(),
              kind: "break",
              label: "",
              start: "",
              end: "",
            });
            setIntervalDirty(false);
          }}
        >
          <Plus size={16} />
          Thêm khoảng
        </Button>
        <div className="clock-origin">
          <label>
            Giờ thực bắt đầu cuộc họp{" "}
            <Input
              type="datetime-local"
              aria-label="Giờ thực bắt đầu cuộc họp"
              value={origin}
              onChange={(event) => setOrigin(event.target.value)}
              disabled={disabled}
            />
            <small className="muted">
              Theo múi giờ của thiết bị (
              {Intl.DateTimeFormat().resolvedOptions().timeZone}).
            </small>
          </label>
          <Button
            variant="outline"
            disabled={disabled || !origin}
            onClick={() => {
              const value = new Date(origin);
              if (Number.isFinite(value.valueOf()))
                void apply([
                  {
                    op: "set_clock_origin",
                    value: {
                      iso_time: value.toISOString(),
                      origin: "user",
                      status: "declared",
                    },
                  },
                ]).then((saved) => saved && setOrigin(""));
            }}
          >
            Lưu giờ thực
          </Button>
          {view.timeline.clock_origin && (
            <>
              <p>
                Đã khai báo:{" "}
                {new Date(view.timeline.clock_origin.iso_time).toLocaleString(
                  "vi-VN",
                )}
              </p>
              <Button
                variant="ghost"
                disabled={disabled}
                onClick={() =>
                  void apply([{ op: "set_clock_origin", value: null }])
                }
              >
                Bỏ giờ thực
              </Button>
            </>
          )}
        </div>
      </details>
      <div className="source-submit">
        <div>
          {view.processing.blockers.map((text) => (
            <p key={text}>{text}</p>
          ))}
          {view.processing.supported && (
            <p className="muted">
              {view.timeline.clips.length} phần sẵn sàng xử lý. File gốc được
              giữ nguyên.
            </p>
          )}
        </div>
        <Button
          disabled={disabled || !view.processing.supported}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await post("/meetings/" + meeting.id + "/process", {
                revision: view.revision,
              });
              await query.invalidateQueries({
                queryKey: ["meeting", meeting.id],
              });
              setMessage("Đã xếp hàng xử lý âm thanh");
            } catch (caught) {
              setError(caught as Error);
            } finally {
              setBusy(false);
            }
          }}
        >
          {meeting.active_transcript_id
            ? "Xử lý lại âm thanh"
            : "Bắt đầu xử lý"}
        </Button>
      </div>
      <Modal
        open={!!editor}
        onOpenChange={(open) =>
          !open &&
          guard.requestClose(() => {
            setEditor(null);
            setRangeDirty(false);
          })
        }
        title="Sắp xếp đoạn và đặt mốc"
        wide
      >
        {editor && (
          <form
            className="form-stack"
            onSubmit={async (event) => {
              event.preventDefault();
              const track = view.timeline.tracks.find(
                (t) => t.id === editor.track,
              )!;
              const sameTrack = track.clip_ids.includes(editor.clip.id);
              const previous = sameTrack
                ? track.clip_ids[track.clip_ids.indexOf(editor.clip.id) - 1]
                : track.clip_ids.at(-1);
              const placement: TimelineUserPlacement =
                editor.kind === "anchored"
                  ? {
                      kind: "anchored",
                      start_ms: Math.round(Number(editor.at) * 1000),
                      origin: "user",
                      status: "declared",
                    }
                  : {
                      kind: "sequential",
                      gap_before_ms:
                        editor.gap === ""
                          ? null
                          : Math.round(Number(editor.gap) * 1000),
                      after_clip_id: previous || null,
                      origin: editor.gap === "" ? "unknown" : "user",
                    };
              const operations: TimelineOperation[] = [];
              if (!sameTrack)
                operations.push({
                  op: "move_clip",
                  clip_id: editor.clip.id,
                  track_id: track.id,
                  placement,
                });
              else
                operations.push({
                  op: "set_placement",
                  clip_id: editor.clip.id,
                  placement,
                });
              operations.push({
                op: "set_range",
                clip_id: editor.clip.id,
                source_in_ms: Math.round(Number(editor.start) * 1000),
                source_out_ms: Math.round(Number(editor.end) * 1000),
              });
              if (await apply(operations, editor.revision)) {
                setEditor(null);
                setRangeDirty(false);
              }
            }}
          >
            <ErrorBox error={error} />
            <label>
              Nguồn ghi
              <select
                value={editor.track}
                onChange={(event) => {
                  setEditor({ ...editor, track: event.target.value });
                  setRangeDirty(true);
                }}
              >
                {view.timeline.tracks.map((track) => (
                  <option key={track.id} value={track.id}>
                    {track.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="form-grid">
              <label>
                Dùng từ giây
                <Input
                  type="number"
                  min={0}
                  step="0.001"
                  required
                  value={editor.start}
                  onChange={(event) => {
                    setEditor({ ...editor, start: event.target.value });
                    setRangeDirty(true);
                  }}
                />
              </label>
              <label>
                Đến giây
                <Input
                  type="number"
                  min={0}
                  step="0.001"
                  required
                  value={editor.end}
                  onChange={(event) => {
                    setEditor({ ...editor, end: event.target.value });
                    setRangeDirty(true);
                  }}
                />
              </label>
            </div>
            <label>
              Cách đặt thời gian
              <select
                value={editor.kind}
                onChange={(event) => {
                  setEditor({
                    ...editor,
                    kind: event.target.value as Editor["kind"],
                  });
                  setRangeDirty(true);
                }}
              >
                <option value="sequential">Theo phần trước</option>
                <option value="anchored">Có mốc trên cuộc họp</option>
              </select>
            </label>
            {editor.kind === "anchored" ? (
              <label>
                Bắt đầu trên cuộc họp (giây)
                <Input
                  type="number"
                  step="0.001"
                  required
                  value={editor.at}
                  onChange={(event) => {
                    setEditor({ ...editor, at: event.target.value });
                    setRangeDirty(true);
                  }}
                />
              </label>
            ) : (
              <label>
                Khoảng cách với phần trước (giây)
                <Input
                  type="number"
                  min={0}
                  step="0.001"
                  placeholder="Để trống nếu chưa biết"
                  value={editor.gap}
                  onChange={(event) => {
                    setEditor({ ...editor, gap: event.target.value });
                    setRangeDirty(true);
                  }}
                />
              </label>
            )}
            <p className="context-hint">
              Để trống khoảng cách khi chưa biết độ dài nghỉ. Nhập 0 chỉ khi hai
              phần nối liền. Mốc lưu ở đây là do bạn khai báo.
            </p>
            <div className="dialog-actions">
              <Button
                variant="ghost"
                type="button"
                disabled={disabled}
                onClick={async () => {
                  if (
                    await apply(
                      [{ op: "remove_clip", clip_id: editor.clip.id }],
                      editor.revision,
                    )
                  ) {
                    setEditor(null);
                    setRangeDirty(false);
                  }
                }}
              >
                <Trash2 size={15} />
                Bỏ đoạn khỏi bố cục
              </Button>
              <Button
                disabled={
                  disabled ||
                  !rangeDirty ||
                  Number(editor.end) <= Number(editor.start)
                }
              >
                Lưu đoạn
              </Button>
            </div>
          </form>
        )}
      </Modal>
      <Modal
        open={!!interval}
        onOpenChange={(open) =>
          !open &&
          guard.requestClose(() => {
            setInterval(null);
            setIntervalDirty(false);
          })
        }
        title="Khoảng thời gian cuộc họp"
      >
        {interval && (
          <form
            className="form-stack"
            onSubmit={async (event) => {
              event.preventDefault();
              if (
                await apply(
                  [
                    {
                      op: "upsert_interval",
                      interval: {
                        id: interval.id,
                        kind: interval.kind,
                        label: interval.label,
                        start_ms: Math.round(Number(interval.start) * 1000),
                        end_ms: Math.round(Number(interval.end) * 1000),
                        confirmed: true,
                      },
                    },
                  ],
                  interval.revision,
                )
              ) {
                setInterval(null);
                setIntervalDirty(false);
              }
            }}
          >
            <ErrorBox error={error} />
            <label>
              Loại khoảng
              <select
                value={interval.kind}
                onChange={(event) => {
                  setInterval({
                    ...interval,
                    kind: event.target.value as TimelineInterval["kind"],
                  });
                  setIntervalDirty(true);
                }}
              >
                <option value="session">Phiên họp</option>
                <option value="break">Giải lao</option>
                <option value="excluded">Loại khỏi biên bản</option>
              </select>
            </label>
            <label>
              Nhãn
              <Input
                value={interval.label}
                maxLength={200}
                onChange={(event) => {
                  setInterval({ ...interval, label: event.target.value });
                  setIntervalDirty(true);
                }}
              />
            </label>
            <div className="form-grid">
              <label>
                Bắt đầu (giây)
                <Input
                  type="number"
                  required
                  min={0}
                  step="0.001"
                  value={interval.start}
                  onChange={(event) => {
                    setInterval({ ...interval, start: event.target.value });
                    setIntervalDirty(true);
                  }}
                />
              </label>
              <label>
                Kết thúc (giây)
                <Input
                  type="number"
                  required
                  min={0}
                  step="0.001"
                  value={interval.end}
                  onChange={(event) => {
                    setInterval({ ...interval, end: event.target.value });
                    setIntervalDirty(true);
                  }}
                />
              </label>
            </div>
            <p className="context-hint">
              Mốc tính trên đồng hồ chung đã khai báo. Chọn “Loại khỏi biên bản”
              để vẫn giữ lời chép nhưng không đưa khoảng này vào biên bản.
            </p>
            <Button
              disabled={
                disabled ||
                !intervalDirty ||
                !interval.start ||
                !interval.end ||
                Number(interval.end) <= Number(interval.start)
              }
            >
              Lưu khoảng
            </Button>
          </form>
        )}
      </Modal>
      <Modal
        open={!!rename}
        onOpenChange={(open) =>
          !open && guard.requestClose(() => setRename(null))
        }
        title="Đổi tên nguồn ghi"
      >
        <label>
          Tên nguồn
          <Input
            value={rename?.name || ""}
            maxLength={100}
            onChange={(event) =>
              rename && setRename({ ...rename, name: event.target.value })
            }
          />
        </label>
        <Button
          disabled={disabled || !rename?.name.trim()}
          onClick={async () => {
            if (
              rename &&
              (await apply(
                [
                  {
                    op: "update_track",
                    track_id: rename.track.id,
                    name: rename.name.trim(),
                  },
                ],
                rename.revision,
              ))
            )
              setRename(null);
          }}
        >
          Lưu tên
        </Button>
      </Modal>
      <Modal
        open={!!removeAsset}
        onOpenChange={(open) => !open && setRemoveAsset(null)}
        title="Bỏ file khỏi cuộc họp"
        description="File này sẽ không tham gia lần xử lý tiếp theo. Các tài liệu và phiên bản đã lưu được giữ lại."
      >
        <Button
          variant="destructive"
          disabled={disabled}
          onClick={async () => {
            setBusy(true);
            try {
              await api("/meetings/" + meeting.id + "/sources/" + removeAsset, {
                method: "DELETE",
                body: JSON.stringify({ revision: view.revision }),
              });
              setRemoveAsset(null);
              await Promise.all([
                data.refetch(),
                query.invalidateQueries({ queryKey: ["meeting", meeting.id] }),
              ]);
              setMessage("Đã bỏ file khỏi cuộc họp");
            } catch (caught) {
              setError(caught as Error);
            } finally {
              setBusy(false);
            }
          }}
        >
          Bỏ file
        </Button>
        <ErrorBox error={error} />
      </Modal>
      <Modal
        open={!!removeTrack}
        onOpenChange={(open) => !open && setRemoveTrack(null)}
        title="Bỏ hàng nguồn"
        description="Các đoạn trên hàng được đưa về kho file chưa xếp. File gốc vẫn được giữ."
      >
        <Button
          variant="destructive"
          disabled={disabled || (removeTrack?.clip_ids.length || 0) > 199}
          onClick={async () => {
            if (
              removeTrack &&
              (await apply([
                ...removeTrack.clip_ids.map((clip_id) => ({
                  op: "remove_clip" as const,
                  clip_id,
                })),
                { op: "remove_track", track_id: removeTrack.id },
              ]))
            )
              setRemoveTrack(null);
          }}
        >
          Bỏ hàng {removeTrack?.name}
        </Button>
        {(removeTrack?.clip_ids.length || 0) > 199 && (
          <p>Hãy chuyển hoặc bỏ bớt các đoạn trước khi bỏ hàng nguồn này.</p>
        )}
      </Modal>
      {guard.dialog}
    </>
  );
}
