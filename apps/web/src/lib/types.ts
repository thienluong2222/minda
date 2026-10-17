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
  trashed: boolean;
  created_at: string;
  updated_at: string;
  duration_sec?: number;
  source_ids: string[];
  sources?: {
    id: string;
    name: string;
    artifact: Artifact;
    duration_sec?: number;
    sample_rate?: number;
    channels?: number;
  }[];
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
  user_edited: boolean;
  clip?: Artifact;
}
export interface Version {
  id: string;
  created_at: string;
  reason: string;
  segment_count?: number;
  docx?: Artifact;
  input_content_revision?: number;
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
  confidence?: number;
}
export interface MinutesOptions {
  mode: "detailed" | "general";
  use_model: boolean;
  correct_transcript: boolean;
  use_fcm: boolean;
  clusters: number | null;
  content_field_id: string | null;
  format_standard: "nd30_2020" | "hd05_2026";
  two_sided: boolean;
  document_metadata: Record<string, string | null>;
}
export interface MinutesVersion extends Version {
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
  asr_variant: string;
  default_format: string;
  use_model: boolean;
}
export interface Capabilities {
  models: Record<string, unknown>;
  preset: Preset;
  max_sources: number;
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
