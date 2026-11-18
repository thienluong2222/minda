import { api, patch, post } from "./api";
import type {
  Meeting,
  TimelineAlignmentReport,
  TimelineOperation,
  TimelineView,
} from "./types";

/** Save once on drop; keep the returned revision for the next edit. */
export const getTimeline = (meetingId: string) =>
  api<TimelineView>(`/meetings/${encodeURIComponent(meetingId)}/timeline`);

/** Use only an alignment generated for the current layout, never stale geometry. */
export const getTimelineAlignment = (view: TimelineView) =>
  view.last_alignment && !view.alignment_stale
    ? api<TimelineAlignmentReport>(
        `/artifacts/${encodeURIComponent(view.last_alignment.id)}`,
      )
    : Promise.resolve(null);

export const updateTimeline = (
  meetingId: string,
  revision: number,
  operations: TimelineOperation[],
) =>
  patch<TimelineView>(`/meetings/${encodeURIComponent(meetingId)}/timeline`, {
    revision,
    operations,
  });

/** An omitted track puts uploads in the unassigned pool, not at time zero. */
export const uploadTimelineFiles = (
  meetingId: string,
  revision: number,
  files: File[],
  trackId?: string,
) => {
  const query = new URLSearchParams({
    revision: String(revision),
    timeline_mode: "true",
  });
  if (trackId) query.set("track_id", trackId);
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  return post<Meeting>(
    `/meetings/${encodeURIComponent(meetingId)}/sources?${query}`,
    body,
  );
};
