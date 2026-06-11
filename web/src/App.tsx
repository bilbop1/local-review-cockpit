import {
  Activity,
  AlertTriangle,
  Archive,
  Bot,
  CheckCircle2,
  ChevronDown,
  Clock3,
  ExternalLink,
  Film,
  Gauge,
  HeartPulse,
  Loader2,
  Lock,
  Play,
  RefreshCw,
  Search,
  Send,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UploadCloud,
  XCircle
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost, reviewVideoUrl } from "./api";
import type {
  AgentsPayload,
  AppData,
  AuthStatus,
  CampaignProject,
  HealthPayload,
  JobRecord,
  PublishStatus,
  ReadinessPayload,
  RenderKit,
  SummaryPayload
} from "./types";

type Route = "dashboard" | "reviews" | "campaigns" | "readiness" | "settings" | "advanced";
type KitFilter = "needs" | "approved" | "rejected" | "all";
type PlatformOverlay = "off" | "ig" | "tt" | "yt";

const routeLabels: Record<Route, string> = {
  dashboard: "Dashboard",
  reviews: "Review Kits",
  campaigns: "Campaigns",
  readiness: "Readiness",
  settings: "Settings",
  advanced: "Advanced"
};

const visibleRoutes: Route[] = ["dashboard", "reviews", "campaigns", "readiness", "settings"];

const initialData: AppData = {
  projects: [],
  kits: [],
  jobs: []
};

function routeFromPath(): Route {
  const parts = window.location.pathname.replace(/^\/app\/?/, "").split("/").filter(Boolean);
  const raw = parts[0] as Route | undefined;
  return raw && raw in routeLabels ? raw : "dashboard";
}

function navigateTo(route: Route) {
  const target = route === "dashboard" ? "/app" : `/app/${route}`;
  window.history.pushState({}, "", target);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function statusTone(value?: string | boolean): "green" | "yellow" | "red" | "grey" {
  if (value === true) return "green";
  if (value === false) return "red";
  const text = String(value || "").toLowerCase();
  if (["green", "ready", "succeeded", "qualified", "ok", "approved_manual_prep", "demo_reviewed"].some((token) => text.includes(token))) return "green";
  if (["yellow", "queued", "running", "needs_review", "blocked", "degraded", "monitor"].some((token) => text.includes(token))) return "yellow";
  if (["red", "failed", "missing", "rejected", "error", "unavailable"].some((token) => text.includes(token))) return "red";
  return "grey";
}

function formatDate(value?: string, mode: "short" | "full" = "short"): string {
  if (!value) return "Missing";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: mode === "full" ? "numeric" : undefined,
    hour: "numeric",
    minute: "2-digit"
  }).format(date);
}

function formatDuration(seconds?: number): string {
  if (!seconds || seconds <= 0) return "Unknown";
  const minutes = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return minutes ? `${minutes}m ${secs}s` : `${secs}s`;
}

function compactNumber(value?: number): string {
  if (!value) return "0";
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function reviewStatusLabel(status?: string): string {
  if (status === "approved_manual_prep" || status === "demo_reviewed") return "Approved";
  if (status?.includes("rejected")) return "Needs Revision";
  return "Needs Review";
}

function sortKitTime(kit: RenderKit): number {
  const candidate = kit.rendered_at || kit.created_at || kit.clip_created_at || kit.clip_discovered_at || "";
  const parsed = Date.parse(candidate);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function kitMatchesFilter(kit: RenderKit, filter: KitFilter): boolean {
  const status = kit.review_status || "";
  if (filter === "all") return true;
  if (filter === "approved") return status === "approved_manual_prep" || status === "demo_reviewed";
  if (filter === "rejected") return status.includes("rejected");
  return !kitMatchesFilter(kit, "approved") && !kitMatchesFilter(kit, "rejected");
}

async function fetchFastCore(signal?: AbortSignal): Promise<Partial<AppData>> {
  const [summary, projects, kits, agents, publish, auth] = await Promise.all([
    apiGet<SummaryPayload>("/api/summary", signal),
    apiGet<CampaignProject[]>("/api/campaign-projects", signal),
    apiGet<RenderKit[]>("/api/review-kits", signal),
    apiGet<AgentsPayload>("/api/agents", signal),
    apiGet<PublishStatus>("/api/publish/status", signal),
    apiGet<AuthStatus>("/api/auth/status", signal)
  ]);
  return { summary, projects, kits, agents, publish, auth };
}

async function fetchProofCore(signal?: AbortSignal): Promise<Partial<AppData>> {
  const [health, readiness] = await Promise.all([
    apiGet<HealthPayload>("/api/health", signal),
    apiGet<ReadinessPayload>("/api/readiness", signal)
  ]);
  return { health, readiness };
}

async function fetchJobs(signal?: AbortSignal): Promise<JobRecord[]> {
  return apiGet<JobRecord[]>("/api/jobs?limit=80", signal);
}

function AppShell({
  route,
  setRoute,
  data,
  loading,
  error,
  refresh,
  children
}: {
  route: Route;
  setRoute: (route: Route) => void;
  data: AppData;
  loading: boolean;
  error: string;
  refresh: () => void;
  children: React.ReactNode;
}) {
  const hermesTone = statusTone(data.agents?.status);
  const publishReady = data.publish?.provider?.live_ready === true;
  const fastBackendOnline = Boolean(data.summary || data.kits.length || data.projects.length || data.jobs.length);
  return (
    <div className="app-frame" data-route={route} data-loaded={data.summary || data.kits.length || data.projects.length ? "true" : "false"}>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Film size={21} /></div>
          <div>
            <strong>Clipping Ops</strong>
            <span>Local web cockpit</span>
          </div>
        </div>
        <nav className="nav-list" aria-label="Main navigation">
          {visibleRoutes.map((item) => (
            <button key={item} className={route === item ? "nav-item active" : "nav-item"} onClick={() => setRoute(item)}>
              {item === "dashboard" && <Gauge size={17} />}
              {item === "reviews" && <Play size={17} />}
              {item === "campaigns" && <Sparkles size={17} />}
              {item === "readiness" && <ShieldCheck size={17} />}
              {item === "settings" && <Settings size={17} />}
              <span>{routeLabels[item]}</span>
            </button>
          ))}
          <details className="advanced-nav">
            <summary><SlidersHorizontal size={16} /> Agent Workbench</summary>
            <button className={route === "advanced" ? "nav-item active" : "nav-item"} onClick={() => setRoute("advanced")}>
              <Bot size={17} />
              <span>Advanced</span>
            </button>
          </details>
        </nav>
        <div className="sidebar-footer">
          <Pill tone={statusTone(data.health?.production_green)} label={data.health?.production_green ? "Local proof green" : "Proof gated"} />
          <span>Backend {data.health?.api_version || (fastBackendOnline ? "online" : "checking")}</span>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <p className="eyebrow">Browser control surface</p>
            <h1>{routeLabels[route]}</h1>
          </div>
          <div className="topbar-actions">
            <StatusChip icon={<HeartPulse size={16} />} tone={fastBackendOnline ? "green" : "grey"} label="Backend" detail={fastBackendOnline ? "online" : "checking"} />
            <StatusChip icon={<Bot size={16} />} tone={hermesTone} label="Hermes" detail={data.agents?.status || "checking"} />
            <StatusChip icon={publishReady ? <UploadCloud size={16} /> : <Lock size={16} />} tone={publishReady ? "green" : "yellow"} label="Publish" detail={publishReady ? "live ready" : "locked"} />
            <button className="icon-button" onClick={refresh} aria-label="Refresh cockpit data">
              {loading ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
            </button>
          </div>
        </header>
        {error && <div className="toast error"><AlertTriangle size={16} /> {error}</div>}
        {children}
      </main>
    </div>
  );
}

function Pill({ tone = "grey", label }: { tone?: "green" | "yellow" | "red" | "grey"; label: string }) {
  return <span className={`pill ${tone}`}>{label}</span>;
}

function StatusChip({ icon, label, detail, tone }: { icon: React.ReactNode; label: string; detail: string; tone: "green" | "yellow" | "red" | "grey" }) {
  return (
    <div className={`status-chip ${tone}`}>
      {icon}
      <span>{label}</span>
      <strong>{detail}</strong>
    </div>
  );
}

function StatCard({ label, value, detail, tone = "grey", icon }: { label: string; value: string | number; detail: string; tone?: "green" | "yellow" | "red" | "grey"; icon: React.ReactNode }) {
  return (
    <section className={`stat-card ${tone}`}>
      <div className="stat-icon">{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </section>
  );
}

function Dashboard({ data, action }: { data: AppData; action: (intent: string, payload?: Record<string, unknown>) => Promise<void> }) {
  const counts = data.summary?.counts || {};
  const latest = data.kits[0];
  const projectsReady = data.projects.filter((project) => statusTone(project.status || project.blocker) === "green").length;
  const subtitleProof = data.kits.some((kit) => kit.campaign_proof_status === "green");
  const customerBlocker = data.readiness?.milestones?.customer_ship_ready?.blockers?.[0] || "Source build repo. Prebuilt app notarization is legacy-only.";
  return (
    <div className="page-stack">
      <section className="stat-grid">
        <StatCard label="Reviews Waiting" value={counts.approvals_needed ?? data.kits.length} detail="Kits needing a human decision" tone={(counts.approvals_needed || 0) > 0 ? "yellow" : "green"} icon={<Play />} />
        <StatCard label="Latest Rendered" value={latest ? formatDate(latest.rendered_at || latest.created_at) : "None"} detail={latest?.title || "No review kits visible yet"} tone={latest ? "green" : "yellow"} icon={<Clock3 />} />
        <StatCard label="Campaign Status" value={`${projectsReady}/${data.projects.length || 0}`} detail="Projects with enough evidence to move" tone={projectsReady > 0 ? "green" : "yellow"} icon={<Sparkles />} />
        <StatCard label="Subtitle Proof" value={subtitleProof ? "Present" : "Needs proof"} detail="Review videos must have visible burned-in captions" tone={subtitleProof ? "green" : "yellow"} icon={<CheckCircle2 />} />
        <StatCard label="Publish Lock" value={data.publish?.provider?.live_ready ? "Open" : "Locked"} detail="Live posting requires key, warm-up, approval, dry-run, confirmation" tone={data.publish?.provider?.live_ready ? "green" : "yellow"} icon={<Lock />} />
        <StatCard label="Customer Ship" value={data.readiness?.milestones?.customer_ship_ready?.status || "Source build"} detail={customerBlocker} tone={statusTone(data.readiness?.milestones?.customer_ship_ready?.status)} icon={<Archive />} />
      </section>
      <section className="action-band">
        <div>
          <p className="eyebrow">Next safe actions</p>
          <h2>Queue the work, then review the outputs here.</h2>
          <p>These buttons create Hermes-readable jobs. Approval and live posting stay human-owned.</p>
        </div>
        <div className="button-row">
          <button className="primary" onClick={() => action("refresh_campaigns")}><RefreshCw size={16} /> Refresh Campaigns</button>
          <button onClick={() => action("review_risk_sweep")}><ShieldCheck size={16} /> Review Sweep</button>
          <button onClick={() => navigateTo("reviews")}><Play size={16} /> Open Reviews</button>
        </div>
      </section>
      <JobStrip jobs={data.jobs} />
    </div>
  );
}

function JobStrip({ jobs }: { jobs: JobRecord[] }) {
  const visible = jobs.slice(0, 6);
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Live queue</p>
          <h2>Recent agent work</h2>
        </div>
      </div>
      <div className="job-list compact">
        {visible.length === 0 && <EmptyState title="No recent jobs" detail="Queued work will appear here as Hermes or local scripts pick it up." />}
        {visible.map((job) => (
          <div className="job-row" key={job.id || job.name}>
            <Pill tone={statusTone(job.status)} label={job.status || "unknown"} />
            <strong>{job.intent || job.name || "Job"}</strong>
            <span>{job.stage || job.error || job.logs || "waiting"}</span>
            <time>{formatDate(job.created_at || job.started_at)}</time>
          </div>
        ))}
      </div>
    </section>
  );
}

function ReviewKits({ data, refresh }: { data: AppData; refresh: () => Promise<void> }) {
  const [filter, setFilter] = useState<KitFilter>("all");
  const [campaign, setCampaign] = useState("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string>("");
  const [overlay, setOverlay] = useState<PlatformOverlay>("off");
  const [rejectNote, setRejectNote] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);

  const filtered = useMemo(() => {
    const text = query.trim().toLowerCase();
    return [...data.kits]
      .filter((kit) => kitMatchesFilter(kit, filter))
      .filter((kit) => campaign === "all" || kit.campaign_slug === campaign)
      .filter((kit) => !text || [kit.title, kit.campaign_name, kit.review_status, kit.clip_source_platform].join(" ").toLowerCase().includes(text))
      .sort((a, b) => sortKitTime(b) - sortKitTime(a));
  }, [data.kits, filter, campaign, query]);

  const selected = useMemo(() => filtered.find((kit) => kit.id === selectedId) || filtered[0] || data.kits[0], [data.kits, filtered, selectedId]);

  useEffect(() => {
    if (selected?.id) {
      setSelectedId(selected.id);
      setRejectNote("");
      setError("");
    }
  }, [selected?.id]);

  useEffect(() => {
    const player = videoRef.current;
    if (!player || !selected?.id) return;
    player.load();
    const attempt = window.setTimeout(() => {
      player.play().catch(() => undefined);
    }, 120);
    return () => window.clearTimeout(attempt);
  }, [selected?.id]);

  async function approve() {
    if (!selected) return;
    setBusy("approve");
    setError("");
    try {
      await apiPost(`/api/review-kits/${selected.id}/approve`, {});
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy("");
    }
  }

  async function reject() {
    if (!selected) return;
    setBusy("reject");
    setError("");
    try {
      await apiPost(`/api/review-kits/${selected.id}/reject`, { notes: rejectNote });
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy("");
    }
  }

  async function preparePublish() {
    if (!selected) return;
    setBusy("publish");
    setError("");
    try {
      await apiPost(`/api/review-kits/${selected.id}/publish-prep`, {
        platforms: ["tiktok", "instagram", "youtube"],
        title: selected.title || "",
        caption: selected.title || ""
      });
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy("");
    }
  }

  async function dryRunPublish() {
    if (!selected) return;
    setBusy("dry-run");
    setError("");
    try {
      await apiPost("/api/publish/jobs", {
        mode: "dry_run",
        provider: "uploadpost",
        kit_id: selected.id,
        platforms: ["tiktok", "instagram", "youtube"],
        requested_by: "web-gui"
      });
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy("");
    }
  }

  const campaigns = data.projects.filter((project) => data.kits.some((kit) => kit.campaign_slug === project.slug));
  return (
    <div className="reviews-layout">
      <section className="review-list-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Newest rendered first</p>
            <h2>Review Kits</h2>
          </div>
          <Pill tone="grey" label={`${filtered.length} shown`} />
        </div>
        <div className="filter-row">
          {(["needs", "approved", "rejected", "all"] as KitFilter[]).map((item) => (
            <button key={item} className={filter === item ? "seg active" : "seg"} onClick={() => setFilter(item)}>
              {item === "needs" ? "Needs Review" : item[0].toUpperCase() + item.slice(1)}
            </button>
          ))}
        </div>
        <div className="toolbar-row">
          <label className="select-shell">
            Campaign
            <select value={campaign} onChange={(event) => setCampaign(event.target.value)}>
              <option value="all">All Campaigns</option>
              {campaigns.map((project) => <option value={project.slug} key={project.slug}>{project.name}</option>)}
            </select>
          </label>
          <label className="search-box">
            <Search size={16} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search reviews" />
          </label>
        </div>
        <div className="kit-list">
          {filtered.length === 0 && <EmptyState title="No kits match" detail="Change the filter or queue more campaign review work." />}
          {filtered.map((kit) => (
            <button key={kit.id} className={selected?.id === kit.id ? "kit-row active" : "kit-row"} onClick={() => setSelectedId(kit.id)}>
              <div className="kit-row-top">
                <strong>{kit.title || "Untitled review"}</strong>
                <Pill tone={statusTone(kit.review_status)} label={reviewStatusLabel(kit.review_status)} />
              </div>
              <div className="kit-meta-grid">
                <span><Clock3 size={14} /> Broadcast {formatDate(kit.clip_created_at)}</span>
                <span><Sparkles size={14} /> Created {formatDate(kit.created_at)}</span>
                <span><Film size={14} /> Rendered {formatDate(kit.rendered_at)}</span>
                <span><Activity size={14} /> {formatDuration(kit.clip_duration)} · {compactNumber(kit.clip_view_count)} views</span>
              </div>
              <div className="kit-row-footer">
                <span>{kit.campaign_name || "Campaign"}</span>
                <span>{kit.clip_source_platform || "Source"}</span>
              </div>
            </button>
          ))}
        </div>
      </section>
      <section className="review-detail-panel">
        {!selected ? (
          <EmptyState title="No review selected" detail="Render or discover campaign clips, then review kits will appear here." />
        ) : (
          <>
            <div className="detail-title">
              <div>
                <h2>{selected.title || "Untitled review"}</h2>
                <div className="detail-meta">
                  <span>{selected.campaign_name || "Campaign"}</span>
                  <span>Rendered {formatDate(selected.rendered_at, "full")}</span>
                  <span>Clip {formatDate(selected.clip_created_at, "full")}</span>
                </div>
              </div>
              <Pill tone={statusTone(selected.review_status)} label={reviewStatusLabel(selected.review_status)} />
            </div>
            <div className="overlay-controls">
              <span>Platform UI</span>
              {(["off", "ig", "tt", "yt"] as PlatformOverlay[]).map((item) => (
                <button key={item} className={overlay === item ? "seg active" : "seg"} onClick={() => setOverlay(item)}>
                  {item === "off" ? "Off" : item.toUpperCase()}
                </button>
              ))}
              <em>{overlay === "off" ? "No platform overlay" : `${overlay.toUpperCase()} safe-area preview`}</em>
            </div>
            <div className={`video-stage overlay-${overlay}`}>
              <video
                key={selected.id}
                ref={videoRef}
                controls
                autoPlay
                muted
                playsInline
                preload="metadata"
                src={reviewVideoUrl(selected.id)}
              />
              <PlatformChrome overlay={overlay} />
            </div>
            <div className="decision-panel">
              <div>
                <h3>Decision</h3>
                <p>Approval prepares files only. It does not publish.</p>
              </div>
              <div className="decision-actions">
                <button className="primary" onClick={approve} disabled={!!busy}><CheckCircle2 size={16} /> {busy === "approve" ? "Approving" : "Approve for Prep"}</button>
                <input value={rejectNote} onChange={(event) => setRejectNote(event.target.value)} placeholder="Revision note required" />
                <button onClick={reject} disabled={!!busy || !rejectNote.trim()}><XCircle size={16} /> Send Back</button>
              </div>
              {error && <p className="inline-error">{error}</p>}
            </div>
            <section className="detail-grid">
              <Info label="Broadcast" value={formatDate(selected.clip_created_at, "full")} />
              <Info label="Kit Created" value={formatDate(selected.created_at, "full")} />
              <Info label="Rendered" value={formatDate(selected.rendered_at, "full")} />
              <Info label="Views" value={compactNumber(selected.clip_view_count)} />
              <Info label="Duration" value={formatDuration(selected.clip_duration)} />
              <Info label="Source" value={selected.clip_source_platform || "Unknown"} />
              {selected.clip_source_url && (
                <a className="source-link" href={selected.clip_source_url} target="_blank" rel="noreferrer">
                  Source Link <ExternalLink size={14} />
                </a>
              )}
            </section>
            <PublishPanel status={data.publish} approved={kitMatchesFilter(selected, "approved")} busy={busy} onPrepare={preparePublish} onDryRun={dryRunPublish} />
            <details className="technical">
              <summary>Technical Artifacts <ChevronDown size={15} /></summary>
              <div className="artifact-grid">
                <Info label="Kit ID" value={selected.id} />
                <Info label="Video Path" value={selected.review_video_path || "hidden"} />
                <Info label="Caption" value={selected.caption_path || "missing"} />
                <Info label="Transcript" value={selected.transcript_path || "missing"} />
                <Info label="Checklist" value={selected.checklist_path || "missing"} />
                <Info label="Risk" value={selected.risk_path || "missing"} />
              </div>
            </details>
          </>
        )}
      </section>
    </div>
  );
}

function PlatformChrome({ overlay }: { overlay: PlatformOverlay }) {
  if (overlay === "off") return null;
  if (overlay === "yt") {
    return <div className="platform-chrome yt"><div className="yt-actions">♡<br />💬<br />↗</div><div className="yt-bottom">Shorts safe caption band</div></div>;
  }
  if (overlay === "ig") {
    return <div className="platform-chrome ig"><div className="ig-top">Reels</div><div className="ig-actions">♡<br />💬<br />↗</div><div className="ig-bottom">Caption, audio, profile controls</div></div>;
  }
  return <div className="platform-chrome tt"><div className="tt-actions">●<br />♡<br />💬<br />↗</div><div className="tt-bottom">TikTok caption/profile zone</div></div>;
}

function PublishPanel({ status, approved, busy, onPrepare, onDryRun }: { status?: PublishStatus; approved: boolean; busy: string; onPrepare: () => void; onDryRun: () => void }) {
  const provider = status?.provider;
  const blockers = provider?.blockers || [];
  return (
    <section className="publish-panel">
      <div>
        <p className="eyebrow">Publish lock</p>
        <h3>{approved ? "Approved kit can be packaged" : "Approve this kit before publish prep"}</h3>
        <p>Live Upload-Post stays locked until key, warm-up, dry-run proof, live mode, and final confirmation all pass.</p>
      </div>
      <div className="publish-controls">
        <button onClick={onPrepare} disabled={!approved || !!busy}><Send size={16} /> Prepare Post</button>
        <button onClick={onDryRun} disabled={!approved || !!busy}><ShieldCheck size={16} /> Dry Run</button>
        <button disabled><Lock size={16} /> Post Now</button>
      </div>
      <div className="blocker-list">
        {(blockers.length ? blockers : ["Live posting is intentionally locked until the provider is fully ready."]).slice(0, 4).map((blocker) => (
          <span key={blocker}><Lock size={13} /> {blocker}</span>
        ))}
      </div>
    </section>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="info">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Campaigns({ data, action }: { data: AppData; action: (intent: string, payload?: Record<string, unknown>, forceNew?: boolean) => Promise<void> }) {
  return (
    <div className="campaign-grid">
      {data.projects.length === 0 && <EmptyState title="No campaign projects" detail="Campaign records will appear once the backend seed data is available." />}
      {data.projects.map((project) => (
        <section className="campaign-card" key={project.slug}>
          <div className="campaign-card-top">
            <div>
              <p className="eyebrow">Campaign</p>
              <h2>{project.name}</h2>
            </div>
            <Pill tone={statusTone(project.status || project.blocker)} label={project.status || "gated"} />
          </div>
          <p>{project.source_strategy || project.blocker || "Source readiness will appear here after refresh."}</p>
          <div className="progress-line">
            <span>Approved {project.approved_count || 0}/{project.target_count || 5}</span>
            <span>Rendered {project.rendered_count || 0}</span>
          </div>
          <div className="button-row">
            <button onClick={() => action("refresh_campaigns", { campaign_slug: project.slug })}><RefreshCw size={16} /> Refresh Campaign</button>
            <button onClick={() => action("discover_campaign_sources", { campaign_slug: project.slug })}><Search size={16} /> Find Sources</button>
            <button className="primary" onClick={() => action("build_campaign_reviews", { campaign_slug: project.slug, limit: 5, style: "campaign_short_final_v1" })}><Play size={16} /> Build Reviews</button>
          </div>
          {project.campaign_url && <a href={project.campaign_url} target="_blank" rel="noreferrer">Open campaign brief <ExternalLink size={14} /></a>}
          {project.blocker && <p className="inline-error">{project.blocker}</p>}
        </section>
      ))}
    </div>
  );
}

function Readiness({ data }: { data: AppData }) {
  const milestones = data.readiness?.milestones || {};
  const milestoneEntries = Object.entries(milestones);
  return (
    <div className="page-stack">
      <section className="readiness-hero">
        <div>
          <p className="eyebrow">Truth layer</p>
          <h2>{data.readiness?.overall || "Checking readiness"}</h2>
          <p>Green means there is current proof. Yellow and red stay blockers, not vibes.</p>
        </div>
        <Pill tone={statusTone(data.readiness?.overall)} label={data.readiness?.overall || "unknown"} />
      </section>
      <div className="milestone-grid">
        {milestoneEntries.length === 0 && <EmptyState title="No readiness payload" detail="The backend did not return milestone data yet." />}
        {milestoneEntries.map(([name, row]) => (
          <section className={`milestone-card ${statusTone(row.status)}`} key={name}>
            <Pill tone={statusTone(row.status)} label={row.status || "unknown"} />
            <h3>{name.replaceAll("_", " ")}</h3>
            <p>{row.blockers?.[0] || row.evidence?.[0] || "No blocker recorded."}</p>
            <details>
              <summary>Proof details</summary>
              {[...(row.evidence || []), ...(row.blockers || [])].map((item) => <span key={item}>{item}</span>)}
            </details>
          </section>
        ))}
      </div>
    </div>
  );
}

function SettingsPage({ data, refresh }: { data: AppData; refresh: () => Promise<void> }) {
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  async function updatePublish(body: Record<string, unknown>) {
    setBusy("publish");
    setMessage("");
    try {
      await apiPost("/api/publish/settings", body);
      await refresh();
      setMessage("Settings updated.");
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy("");
    }
  }
  async function exportDiagnostics() {
    setBusy("diagnostics");
    setMessage("");
    try {
      const result = await apiPost<Record<string, unknown>>("/api/diagnostics/export", {});
      setMessage(String(result.path || result.status || "Diagnostics exported."));
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy("");
    }
  }
  return (
    <div className="settings-grid">
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">System health</p>
            <h2>Local services</h2>
          </div>
        </div>
        <div className="health-list">
          {Object.entries(data.health?.checks || {}).map(([name, check]) => (
            <div key={name}>
              <Pill tone={statusTone(check.ok)} label={check.ok ? "ok" : "blocked"} />
              <strong>{name.replaceAll("_", " ")}</strong>
              <span>{check.detail || ""}</span>
            </div>
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Credentials</p>
            <h2>Provider status</h2>
          </div>
        </div>
        <div className="health-list">
          {Object.entries(data.auth?.providers || {}).map(([name, provider]) => (
            <div key={name}>
              <Pill tone={statusTone(provider.ok)} label={provider.ok ? "configured" : "missing"} />
              <strong>{name}</strong>
              <span>{provider.client_id || provider.app_token || "no local secret installed"}</span>
            </div>
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Upload-Post</p>
            <h2>Warm-up and mode</h2>
          </div>
          <Pill tone={data.publish?.provider?.live_ready ? "green" : "yellow"} label={data.publish?.provider?.live_ready ? "live ready" : "locked"} />
        </div>
        <div className="button-row">
          <button onClick={() => updatePublish({ warmup_complete: true })} disabled={!!busy}>Mark Warm-up Complete</button>
          <button onClick={() => updatePublish({ warmup_complete: false })} disabled={!!busy}>Lock Warm-up</button>
          <button onClick={() => updatePublish({ mode: "uploadpost_dry_run" })} disabled={!!busy}>Dry-Run Mode</button>
          <button onClick={() => updatePublish({ mode: "uploadpost_live" })} disabled={!!busy}>Live Mode Gate</button>
        </div>
        <p>Keys stay outside the repo. Use Keychain/private runtime config only.</p>
      </section>
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Maintenance</p>
            <h2>Diagnostics and startup</h2>
          </div>
        </div>
        <div className="button-row">
          <button onClick={exportDiagnostics} disabled={!!busy}><Archive size={16} /> Export Diagnostics</button>
          <a className="button-link" href="/api/health" target="_blank" rel="noreferrer">Open Health JSON</a>
        </div>
        <p>Startup service setup remains local-only. The normal operator URL is <code>http://127.0.0.1:8765/app</code>.</p>
        {message && <p className="inline-note">{message}</p>}
      </section>
    </div>
  );
}

function Advanced({ data, action }: { data: AppData; action: (intent: string, payload?: Record<string, unknown>, forceNew?: boolean) => Promise<void> }) {
  return (
    <div className="page-stack">
      <section className="action-band warning">
        <div>
          <p className="eyebrow">Agent workbench</p>
          <h2>Technical controls live here.</h2>
          <p>Normal operation queues Hermes jobs. Use direct fallback scripts only when debugging locally.</p>
        </div>
        <div className="button-row">
          <button onClick={() => action("platform_smoke")}><Activity size={16} /> Run Platform Check</button>
          <button onClick={() => action("review_risk_sweep")}><ShieldCheck size={16} /> Review/Risk Sweep</button>
        </div>
      </section>
      <JobStrip jobs={data.jobs} />
      <section className="panel">
        <div className="section-heading"><h2>Campaign records</h2></div>
        <DataList rows={data.projects} />
      </section>
      <section className="panel">
        <div className="section-heading"><h2>Latest publish jobs</h2></div>
        <DataList rows={data.publish?.latest_jobs || []} />
      </section>
    </div>
  );
}

function DataList({ rows }: { rows: unknown[] }) {
  if (!rows.length) return <EmptyState title="No rows" detail="Nothing has been recorded for this section yet." />;
  return (
    <div className="data-list">
      {rows.slice(0, 18).map((row, index) => (
        <pre key={index}>{JSON.stringify(row, null, 2)}</pre>
      ))}
    </div>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <AlertTriangle size={18} />
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}

export function App() {
  const [route, setRouteState] = useState<Route>(routeFromPath());
  const [data, setData] = useState<AppData>(initialData);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refreshCore = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const fastController = new AbortController();
      const fastTimeout = window.setTimeout(() => fastController.abort(), 20000);
      const [fastCore, jobs] = await Promise.all([fetchFastCore(fastController.signal), fetchJobs(fastController.signal)]);
      window.clearTimeout(fastTimeout);
      setData((previous) => ({ ...previous, ...fastCore, jobs }));
      setLoading(false);

      const proofController = new AbortController();
      const proofTimeout = window.setTimeout(() => proofController.abort(), 25000);
      fetchProofCore(proofController.signal)
        .then((proofCore) => setData((previous) => ({ ...previous, ...proofCore })))
        .catch(() => undefined)
        .finally(() => window.clearTimeout(proofTimeout));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      setLoading(false);
    }
  }, []);

  const refreshJobs = useCallback(async () => {
    try {
      const jobs = await fetchJobs();
      setData((previous) => ({ ...previous, jobs }));
    } catch {
      // The core poll owns user-facing errors.
    }
  }, []);

  const setRoute = useCallback((next: Route) => {
    navigateTo(next);
  }, []);

  const queueJob = useCallback(async (intent: string, payload: Record<string, unknown> = {}, forceNew = false) => {
    setLoading(true);
    setError("");
    try {
      await apiPost("/api/jobs", {
        intent,
        requested_by: "web-gui",
        campaign_slug: typeof payload.campaign_slug === "string" ? payload.campaign_slug : "",
        payload,
        force_new: forceNew,
        dedupe_key: `${intent}:${payload.campaign_slug || "global"}`
      });
      await refreshCore();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [refreshCore]);

  useEffect(() => {
    const onPop = () => setRouteState(routeFromPath());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    refreshCore();
    const coreTimer = window.setInterval(refreshCore, 5000);
    const jobTimer = window.setInterval(refreshJobs, 2000);
    return () => {
      window.clearInterval(coreTimer);
      window.clearInterval(jobTimer);
    };
  }, [refreshCore, refreshJobs]);

  return (
    <AppShell route={route} setRoute={setRoute} data={data} loading={loading} error={error} refresh={refreshCore}>
      {route === "dashboard" && <Dashboard data={data} action={queueJob} />}
      {route === "reviews" && <ReviewKits data={data} refresh={refreshCore} />}
      {route === "campaigns" && <Campaigns data={data} action={queueJob} />}
      {route === "readiness" && <Readiness data={data} />}
      {route === "settings" && <SettingsPage data={data} refresh={refreshCore} />}
      {route === "advanced" && <Advanced data={data} action={queueJob} />}
    </AppShell>
  );
}
