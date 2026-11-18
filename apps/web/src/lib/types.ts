export interface User {
  id: string;
  username: string;
  display_name: string;
  role: "admin" | "user";
  active: boolean;
  created_at: string;
}
export interface AdminUser extends User {
  meeting_count: number;
  trashed_meeting_count: number;
}
export interface AdminMeeting {
  id: string;
  title: string;
  owner_id: string;
  owner_name: string;
  owner_username: string;
  date: string;
  location: string;
  state: string;
  trashed: boolean;
  created_at: string;
  updated_at: string;
  source_count: number;
  active_job: string | null;
  has_transcript: boolean;
  has_minutes: boolean;
  minutes_stale: boolean;
}
export interface Artifact {
  id: string;
  url: string;
  name: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
}
export interface Job {
  id: string;
  owner_id: string;
  owner_name?: string;
  resource_type: string;
  resource_id: string;
  kind: string;
  state: string;
  stage: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  error?: { code: string; message: string };
  result?: {
    backup?: Artifact;
    database?: string;
    data_directory?: string;
    message?: string;
  };
  cancel_requested: boolean;
}
export interface MeetingSource {
  id: string;
  name: string;
  artifact: Artifact;
  duration_sec?: number;
  sample_rate?: number;
  channels?: number;
  duration_source?: "stream" | "container";
  duration_is_estimate?: boolean;
}
export type TimelinePlacement =
  | {
      kind: "anchored";
      start_ms: number;
      origin?: "user" | "capture_log" | "audio_match";
      status?: "declared" | "verified" | "needs_review";
    }
  | {
      kind: "sequential";
      gap_before_ms?: number | null;
      after_clip_id?: string | null;
      origin?: "unknown" | "user" | "capture_log" | "audio_match";
    };
export type TimelineUserPlacement =
  | {
      kind: "anchored";
      start_ms: number;
      origin?: "user";
      status?: "declared";
    }
  | {
      kind: "sequential";
      gap_before_ms?: number | null;
      after_clip_id?: string | null;
      origin?: "unknown" | "user";
    };
export interface TimelineClip {
  id: string;
  asset_id: string;
  source_in_ms: number;
  source_out_ms: number;
  placement: TimelinePlacement;
  timing_history: { reason: string; placement: TimelinePlacement }[];
}
export interface TimelineTrack {
  id: string;
  name: string;
  device_id: string | null;
  clip_ids: string[];
}
export interface TimelineInterval {
  id: string;
  kind: "session" | "break" | "excluded";
  label?: string;
  start_ms?: number | null;
  end_ms?: number | null;
  start_clip_id?: string | null;
  end_clip_id?: string | null;
  confirmed?: boolean;
}
export interface AudioTimeline {
  schema_version: 1;
  alignment_mode?: "legacy" | "auto";
  clock_origin: {
    iso_time: string;
    origin: "user" | "capture_log";
    status: "declared" | "verified";
  } | null;
  tracks: TimelineTrack[];
  clips: TimelineClip[];
  unassigned_asset_ids: string[];
  intervals: TimelineInterval[];
}
export type TimelineOperation =
  | { op: "create_track"; id: string; name: string; device_id?: string | null }
  | {
      op: "update_track";
      track_id: string;
      name: string;
      device_id?: string | null;
    }
  | { op: "reorder_tracks"; track_ids: string[] }
  | { op: "remove_track"; track_id: string }
  | {
      op: "add_clip";
      id: string;
      track_id: string;
      asset_id: string;
      source_in_ms?: number;
      source_out_ms?: number;
      before_clip_id?: string | null;
      placement?: TimelineUserPlacement;
    }
  | {
      op: "move_clip";
      clip_id: string;
      track_id: string;
      before_clip_id?: string | null;
      placement?: TimelineUserPlacement;
    }
  | { op: "set_placement"; clip_id: string; placement: TimelineUserPlacement }
  | {
      op: "set_range";
      clip_id: string;
      source_in_ms: number;
      source_out_ms: number;
    }
  | { op: "remove_clip"; clip_id: string }
  | { op: "upsert_interval"; interval: TimelineInterval }
  | { op: "remove_interval"; interval_id: string }
  | {
      op: "set_clock_origin";
      value: { iso_time: string; origin?: "user"; status?: "declared" } | null;
    };
export interface TimelineView {
  revision: number;
  content_revision: number;
  legacy: boolean;
  timeline: AudioTimeline;
  timeline_hash: string;
  last_alignment?: Artifact | null;
  alignment_stale?: boolean;
  resolved_positions: Record<
    string,
    { start_ms: number | null; end_ms: number | null }
  >;
  assets: (Omit<MeetingSource, "artifact"> & { artifact: Artifact | null })[];
  processing: {
    supported: boolean;
    mode: "legacy_auto" | "timeline" | "pending_timeline_processing";
    blockers: string[];
  };
}
export interface TimelineClockSpan {
  clip_id: string;
  clock_id: string;
  start: number;
  end: number;
  scale: number;
  offset: number;
  origin:
    | "declared"
    | "reference"
    | "sequential"
    | "acoustic"
    | "extrapolated"
    | "local";
  residual_ms: number | null;
  anchors: number;
  via: string[];
  boundary_uncertainty_ms: number | null;
}
export interface TimelineAlignmentReport {
  schema_version: 1;
  algorithm: string;
  spans: Record<string, TimelineClockSpan[]>;
  proposed_spans: Record<string, TimelineClockSpan[]>;
  clock_ids: string[];
  timing_complete: boolean;
  clock_basis: "declared" | "reference_recording";
  meeting_origin_shift_sec: number;
  estimated_span_count: number;
  conflicts: {
    clip_id?: string;
    reason: string;
    declared_start_sec?: number;
    proposed_start_sec?: number;
  }[];
  resolved_intervals: {
    id: string;
    kind: "session" | "break" | "excluded";
    clock_id: string;
    start_sec: number;
    end_sec: number;
  }[];
}
export interface Meeting {
  id: string;
  title: string;
  date: string;
  location: string;
  notes: string;
  participant_ids: string[];
  revision: number;
  content_revision: number;
  state: string;
  active_job: string | null;
  active_transcript_id: string | null;
  active_minutes_id: string | null;
  minutes_stale: boolean;
  transcript_stale?: boolean;
  trashed: boolean;
  created_at: string;
  updated_at: string;
  duration_sec?: number | null;
  source_ids: string[];
  sources?: MeetingSource[];
  timeline?: AudioTimeline;
  reviewed_version?: string;
  transcript_exports?: Artifact[];
}
export interface Segment {
  id: string;
  turn_id: string;
  text: string;
  speaker_label: string;
  speaker_key: string | null;
  speaker_count: number;
  speaker_status: string;
  start_sec: number;
  end_sec: number;
  needs_review: boolean;
  review_reasons?: string[];
  source_candidates?: { label: string; text: string }[];
  context_audio?: {
    audio: Artifact;
    start_sec: number;
    end_sec: number;
  } | null;
  user_edited: boolean;
  clock_id?: string;
  clock_label?: string;
  time_status?: "meeting" | "estimated" | "unresolved";
  meeting_start_sec?: number | null;
  meeting_end_sec?: number | null;
  recording_evidence?: {
    asset_id: string;
    clip_id: string;
    source_track_id: string;
    source_start_sec: number;
    source_end_sec: number;
    decoded_sample_rate: number;
  }[];
  excluded_from_minutes?: boolean;
  clip?: Artifact;
}
export interface Version {
  id: string;
  created_at: string;
  reason: string;
  segment_count?: number;
  docx?: Artifact;
  input_content_revision?: number;
  input_timeline_hash?: string;
  timing_complete?: boolean;
}
export interface Transcript {
  version: Version | null;
  segments: Segment[];
}
export interface TemplateField {
  field_id: string;
  anchor_id: string;
  raw_label: string;
  semantic_type: string;
  section: string;
  mapper_status: string;
  cardinality: string;
  [key: string]: unknown;
}
export interface TemplateVersion {
  id: string;
  schema: { fields: TemplateField[] };
  normalized: Artifact;
  original: Artifact;
  previews: Artifact[];
  paragraphs: { index: number; text: string }[];
  report: {
    engine: string;
    needs_review: boolean;
    warnings: string[];
    preview_error?: string;
    pages?: {
      page: number;
      engine: string;
      word_count?: number;
      table_count?: number;
      mean_confidence?: number;
      low_confidence_count?: number;
    }[];
  };
}
export interface Template {
  id: string;
  name: string;
  owner_id: string;
  visibility: string;
  revision: number;
  state: string;
  active_job: string | null;
  field_count?: number;
  needs_review: boolean;
  version?: TemplateVersion;
}
export interface Voice {
  id: string;
  name: string;
  state: string;
  active_job: string | null;
  revision: number;
  samples: Artifact[];
  metadata?: {
    total_seconds?: number;
    total_speech_seconds?: number;
    warnings?: string[];
    sample_count?: number;
  };
}
export interface Evidence {
  clip_artifact_id?: string | null;
  text_snippet?: string;
  source_kind?: string;
  turn_id?: string;
  text?: string;
  start_sec?: number;
  end_sec?: number;
  source_type?: string;
  [key: string]: unknown;
}
export interface Fact {
  field_id: string;
  value: string | string[] | null;
  status: string;
  reason?: string;
  evidence_refs: Evidence[];
  user_edited: boolean;
  previous_edit?: { value: Fact["value"]; minutes_version_id: string } | null;
  confidence?: number;
}
export interface MinutesOptions {
  mode: "detailed" | "general";
  use_model: boolean;
  graph_enabled?: boolean;
  correct_transcript: boolean;
  use_fcm: boolean;
  clusters: number | null;
  content_field_id: string | null;
  format_standard: "nd30_2020" | "hd05_2026" | "minimal";
  two_sided: boolean;
  document_metadata: Record<string, string | null>;
}
export interface MinutesVersion extends Version {
  graph_id?: string;
  transcript_version_id?: string;
  facts: Fact[];
  schema: { fields: TemplateField[] };
  options: MinutesOptions;
  report: {
    warnings?: string[];
    model_id?: string;
    excluded_turns?: unknown[];
  };
  formatting: Record<string, unknown>;
  topics: {
    cluster_count?: number;
    ambiguous_indices?: number[];
    sections?: { title: string; items: { text: string }[] }[];
  };
  corrections: unknown[];
  docx: Artifact;
  zip: Artifact;
  previews: Artifact[];
  template_id: string;
}
export interface Preset {
  revision: number;
  identity_method: string;
  fusion_method: string;
  asr_fusion_mode: "transcript" | "audio";
  asr_variant: string;
  default_format: string;
  use_model: boolean;
  minutes_graph_enabled: boolean;
  minutes_style_learning_enabled: boolean;
}
export interface Capabilities {
  models: Record<string, unknown>;
  preset: Preset;
  max_sources: number;
  max_source_files: number;
  max_timeline_clips: number;
  max_audio_duration_sec: number;
  max_upload_bytes: number;
  documents: {
    word: boolean;
    pdf_text: boolean;
    ocr: boolean;
    preview: boolean;
    ocr_languages: string[];
  };
  worker: { online: boolean; last_seen?: string; active_job?: string };
  runtime: { python: string; platform: string };
}
export interface Audit {
  id: string;
  action: string;
  resource_id: string;
  owner_id: string;
  created_at: string;
  details: Record<string, unknown>;
}
export interface Experiment {
  id: string;
  name: string;
  created_at: string;
  metrics: {
    wer: number;
    cer: number;
    substitutions: number;
    deletions: number;
    insertions: number;
    reference_words: number;
  };
  transcript_version_id: string;
  git_revision: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
}

export type ReviewReasonCode =
  | "minutes_stale"
  | "minutes_unreviewed"
  | "transcript_needs_review"
  | "template_needs_review";

export interface ReviewQueueItem {
  id: string;
  resource_type: "meeting" | "template";
  resource_id: string;
  title: string;
  subtitle?: string;
  state: string;
  target_url: string;
  target_tab?: string;
  reason_codes: ReviewReasonCode[];
  reasons: string[];
  review_count: number;
  version_id?: string | null;
  updated_at: string;
}

export interface WorkspaceDocumentItem {
  id: string;
  meeting_id: string;
  meeting_title: string;
  meeting_date: string;
  meeting_location: string;
  version_id: string;
  created_at: string;
  updated_at: string;
  review_status: "reviewed" | "needs_review" | "stale";
  minutes_stale: boolean;
  reviewed_version?: string | null;
  template_id?: string | null;
  template_name?: string | null;
  docx?: Artifact | null;
  zip?: Artifact | null;
  previews?: Artifact[];
}

export interface WorkspaceJobItem extends Job {
  resource_title?: string;
  allowed_actions: ("cancel" | "retry" | "open_resource")[];
}

export interface VoiceDetail extends Voice {
  meetings?: {
    id: string;
    title: string;
    date: string;
    state: string;
    updated_at: string;
  }[];
}
