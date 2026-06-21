export type StatusColor = "green" | "yellow" | "red" | "grey";

export type HealthPayload = {
  api_version?: string;
  production_green?: boolean;
  checks?: Record<string, { ok?: boolean; detail?: string }>;
  auth?: {
    no_key_mode?: boolean;
    providers?: Record<string, { ok?: boolean; client_id?: string; app_token?: string }>;
  };
  publish?: PublishStatus;
};

export type SummaryPayload = {
  counts?: {
    review_kits?: number;
    approvals_needed?: number;
    blocked_jobs?: number;
    clips?: number;
    nominations?: number;
  };
  latest_review_kit?: RenderKit;
  latest_jobs?: JobRecord[];
};

export type ReadinessPayload = {
  overall?: string;
  milestones?: Record<string, { status?: string; blockers?: string[]; evidence?: string[] }>;
  gates?: Record<string, unknown>;
  blockers?: string[];
};

export type CampaignProject = {
  slug: string;
  name: string;
  campaign_url?: string;
  status?: string;
  blocker?: string;
  rendered_count?: number;
  approved_count?: number;
  target_count?: number;
  source_ready?: boolean;
  source_strategy?: string;
  last_checked_at?: string;
};

export type ReviewScheduleCampaign = {
  campaign_slug?: string;
  campaign_name?: string;
  enabled?: boolean;
  cadence_hours?: number;
  daily_cap?: number;
  generated_today?: number;
  pending?: boolean;
  last_queued_at?: string;
  next_due_at?: string;
  learning?: {
    recent_signal_count?: number;
    avoid_tags?: Record<string, number>;
    recent_notes?: string[];
  };
};

export type ReviewSchedule = {
  status?: string;
  day?: string;
  daily_cap?: number;
  generated_today?: number;
  approved_today?: number;
  rejected_today?: number;
  needs_review_backlog?: number;
  backlog_limit?: number;
  campaigns?: ReviewScheduleCampaign[];
};

export type RenderKit = {
  id: string;
  title?: string;
  campaign_slug?: string;
  campaign_name?: string;
  campaign_url?: string;
  review_status?: string;
  campaign_proof_status?: string;
  created_at?: string;
  rendered_at?: string;
  clip_created_at?: string;
  clip_discovered_at?: string;
  clip_view_count?: number;
  clip_duration?: number;
  clip_source_platform?: string;
  clip_source_url?: string;
  source_path?: string;
  risk_path?: string;
  transcript_path?: string;
  checklist_path?: string;
  caption_path?: string;
  review_video_path?: string;
  rejection_notes?: string;
  publish_package_id?: string;
  publish_package_status?: string;
  publish_job_id?: string;
  publish_status?: string;
  publish_stage?: string;
  publish_mode?: string;
  publish_scheduled_at?: string;
  publish_hermes_job_id?: string;
  publish_error?: string;
};

export type JobRecord = {
  id?: string;
  intent?: string;
  name?: string;
  status?: string;
  stage?: string;
  progress?: number;
  campaign_slug?: string;
  requested_by?: string;
  claimed_by?: string;
  hermes_profile?: string;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
  logs?: string;
};

export type PublishStatus = {
  supported_platforms?: string[];
  capture_platforms?: string[];
  default_platforms?: string[];
  auto_schedule?: {
    auto_slot_on_approve?: boolean;
    mode?: string;
    auto_post_approved?: boolean;
    slots_per_day?: number;
    slot_minute?: number;
    slot_hours?: number[];
    cadence_hours?: number;
    timezone?: string;
  };
  provider?: {
    mode?: string;
    api_key?: string;
    warmup_complete?: boolean;
    user?: string;
    profile_configured?: boolean;
    live_ready?: boolean;
    blockers?: string[];
    supported_platforms?: string[];
    platforms?: Record<string, { warmup_complete?: boolean; live_ready?: boolean; blockers?: string[] }>;
  };
  runway?: {
    scheduled_count?: number;
    live_scheduled_count?: number;
    check_scheduled_count?: number;
    slots_per_day?: number;
    estimated_hours?: number;
    estimated_days?: number;
    next_slot?: string;
    last_slot?: string;
  };
  latest_jobs?: PublishJob[];
};

export type PublishJob = {
  id?: string;
  status?: string;
  mode?: string;
  provider?: string;
  platforms?: string[] | string;
  created_at?: string;
  scheduled_at?: string;
  error?: string;
};

export type AgentsPayload = {
  status?: string;
  selected_profile?: string;
  provider?: string;
  model?: string;
  minimax?: {
    status?: string;
    ready?: boolean;
    blockers?: string[];
    expected_profile?: string;
    expected_model?: string;
  };
  hermes_available?: boolean;
  cron_jobs?: string[];
};

export type AuthStatus = {
  no_key_mode?: boolean;
  providers?: Record<string, { ok?: boolean; client_id?: string; app_token?: string }>;
};

export type AppData = {
  health?: HealthPayload;
  summary?: SummaryPayload;
  readiness?: ReadinessPayload;
  projects: CampaignProject[];
  kits: RenderKit[];
  jobs: JobRecord[];
  agents?: AgentsPayload;
  schedule?: ReviewSchedule;
  learning?: unknown[];
  publish?: PublishStatus;
  auth?: AuthStatus;
  platforms?: unknown;
  audit?: unknown[];
  clips?: unknown[];
  nominations?: unknown[];
};
