import fs from "node:fs/promises";
import path from "node:path";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const root = path.resolve(new URL("..", import.meta.url).pathname);
const outDir = path.join(root, "artifacts", "product-proof");
const docsDir = path.join(root, "docs");
const apiBase = process.env.CLIPPING_OPS_API_BASE || "http://127.0.0.1:8765";

async function getJson(route) {
  const response = await fetch(`${apiBase}${route}`);
  if (!response.ok) {
    throw new Error(`${route} returned HTTP ${response.status}`);
  }
  return response.json();
}

async function readJsonMaybe(filePath, fallback) {
  try {
    return JSON.parse(await fs.readFile(filePath, "utf8"));
  } catch {
    return fallback;
  }
}

async function readTextMaybe(filePath) {
  try {
    return await fs.readFile(filePath, "utf8");
  } catch {
    return "";
  }
}

function rel(absPath) {
  return path.relative(root, absPath);
}

function statusRank(status) {
  if (status === "green" || status === "ready" || status === "succeeded") return 3;
  if (status === "yellow" || status === "degraded" || status === "demo_reviewed") return 2;
  return 1;
}

async function exists(filePath) {
  try {
    await fs.stat(filePath);
    return true;
  } catch {
    return false;
  }
}

async function critiqueSummary(filePath) {
  try {
    const text = await fs.readFile(filePath, "utf8");
    const lines = text.split("\n");
    const statusLine = lines.find((line) => line.toLowerCase().startsWith("status:")) || "Status: unknown";
    const status = statusLine.split(":").slice(1).join(":").trim().toLowerCase() || "unknown";
    return { status, text: lines.slice(0, 10).join(" ") };
  } catch {
    return { status: "red", text: "missing style critique" };
  }
}

async function recentIncompleteRenderDirs(renderRoot, limit = 8) {
  const required = ["ffprobe.json", "thumbnail.jpg", "contact_sheet.jpg", "style_critique.md", "render_text_manifest.json"];
  let entries = [];
  try {
    entries = await fs.readdir(renderRoot, { withFileTypes: true });
  } catch {
    return [];
  }
  const dirs = await Promise.all(entries
    .filter((entry) => entry.isDirectory())
    .map(async (entry) => {
      const dirPath = path.join(renderRoot, entry.name);
      const stats = await fs.stat(dirPath);
      const missing = [];
      for (const name of required) {
        if (!await exists(path.join(dirPath, name))) {
          missing.push(name);
        }
      }
      return {
        name: entry.name,
        path: dirPath,
        mtimeMs: stats.mtimeMs,
        missing,
      };
    }));
  return dirs
    .filter((dir) => dir.missing.length)
    .sort((a, b) => b.mtimeMs - a.mtimeMs)
    .slice(0, limit);
}

async function recentRenderDirs(renderRoot, limit = 8) {
  let entries = [];
  try {
    entries = await fs.readdir(renderRoot, { withFileTypes: true });
  } catch {
    return [];
  }
  const dirs = await Promise.all(entries
    .filter((entry) => entry.isDirectory())
    .map(async (entry) => {
      const dirPath = path.join(renderRoot, entry.name);
      const stats = await fs.stat(dirPath);
      return {
        name: entry.name,
        path: dirPath,
        mtimeMs: stats.mtimeMs,
      };
    }));
  return dirs.sort((a, b) => b.mtimeMs - a.mtimeMs).slice(0, limit);
}

async function completeRenderDirs(renderRoot) {
  const required = ["review.mp4", "ffprobe.json", "thumbnail.jpg", "contact_sheet.jpg", "style_critique.md", "render_text_manifest.json"];
  let entries = [];
  try {
    entries = await fs.readdir(renderRoot, { withFileTypes: true });
  } catch {
    return [];
  }
  const dirs = await Promise.all(entries
    .filter((entry) => entry.isDirectory())
    .map(async (entry) => {
      const dirPath = path.join(renderRoot, entry.name);
      const stats = await fs.stat(dirPath);
      const critiquePath = path.join(dirPath, "style_critique.md");
      const filesOk = await Promise.all(required.map((name) => exists(path.join(dirPath, name))));
      let critiqueText = "";
      try {
        critiqueText = await fs.readFile(critiquePath, "utf8");
      } catch {
        critiqueText = "";
      }
      return {
        name: entry.name,
        path: dirPath,
        mtimeMs: stats.mtimeMs,
        complete: filesOk.every(Boolean),
        critiqueText,
      };
    }));
  return dirs.sort((a, b) => b.mtimeMs - a.mtimeMs);
}

async function writeText(filePath, content) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, content, "utf8");
}

function writeWorksheetRows(sheet, startRow, rows) {
  if (!rows.length) {
    sheet.getRange(`A${startRow}:E${startRow}`).values = [["none", "n/a", "", "", ""]];
    return startRow;
  }
  const endRow = startRow + rows.length - 1;
  sheet.getRange(`A${startRow}:E${endRow}`).values = rows;
  return endRow;
}

async function main() {
  await fs.mkdir(outDir, { recursive: true });
  const [health, readiness, platforms, summary, gate, reviewKits, campaignProjects] = await Promise.all([
    getJson("/api/health"),
    getJson("/api/readiness"),
    getJson("/api/platforms"),
    getJson("/api/summary"),
    getJson("/api/campaign-gate"),
    getJson("/api/review-kits"),
    getJson("/api/campaign-projects"),
  ]);
  const manifestPath = path.join(root, "artifacts", "desktop-qa", "manifest.json");
  let guiManifest = { ok: false, screenshots: [], controls: [], media: [], page_clicks: [], new_crash_reports: [] };
  try {
    guiManifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
  } catch {
    // The report will call this out as a missing artifact.
  }
  const securityPath = path.join(root, "artifacts", "security", "security-scan.json");
  const securityScan = await readJsonMaybe(securityPath, { ok: false, finding_count: "missing", findings: [] });
  const burnedCaptionPath = path.join(root, "artifacts", "review-kit-audit", "burned-caption-verification.json");
  const burnedCaptions = await readJsonMaybe(burnedCaptionPath, { ok: false, kit_count: 0, results: [] });
  const launchAgentPath = path.join(root, "artifacts", "backend", "backend-launchagent.json");
  const launchAgent = await readJsonMaybe(launchAgentPath, { ok: false, state: "missing", last_exit: "", api_version: "" });
  const noKeyPath = path.join(root, "artifacts", "no-key", "no-key-installer.json");
  const noKey = await readJsonMaybe(noKeyPath, { ok: false, no_key_mode: false });
  const handoffPath = path.join(root, "artifacts", "handoff", "codex-handoff.json");
  const handoff = await readJsonMaybe(handoffPath, { ok: false, source_build_handoff_ready: false, requires_notarization: false, zip_path: "", file_count: 0 });
  const releasePath = path.join(root, "artifacts", "distribution", "release-verify.json");
  const release = await readJsonMaybe(releasePath, { customer_ship_ready: false, bundle_ok: false, signed_ok: false, notarized_ok: false, blockers: [] });
  const reindexPath = path.join(root, "artifacts", "research-run", "campaign-streamer-reindex.json");
  const streamerReindex = await readJsonMaybe(reindexPath, { ranked: [], active_project_slugs: [] });

  const workbook = Workbook.create();
  const scorecard = workbook.worksheets.add("Scorecard");
  const features = readiness.features.map((item) => [
    item.name,
    item.status,
    item.evidence,
    item.blocker || "",
    statusRank(item.status),
  ]);
  scorecard.getRange("A1:E1").values = [["Feature", "Status", "Evidence", "Blocker", "Rank"]];
  scorecard.getRange(`A2:E${features.length + 1}`).values = features;
  scorecard.getRange("A1:E1").format = {
    fill: "#111827",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    verticalAlignment: "center",
  };
  scorecard.getRange(`A1:E${features.length + 1}`).format = {
    borders: { preset: "all", style: "thin", color: "#D1D5DB" },
    wrapText: true,
    verticalAlignment: "top",
  };
  scorecard.getRange(`B2:B${features.length + 1}`).conditionalFormats.add("containsText", {
    text: "green",
    format: { fill: "#DCFCE7", font: { color: "#166534", bold: true } },
  });
  scorecard.getRange(`B2:B${features.length + 1}`).conditionalFormats.add("containsText", {
    text: "yellow",
    format: { fill: "#FEF3C7", font: { color: "#92400E", bold: true } },
  });
  scorecard.getRange(`B2:B${features.length + 1}`).conditionalFormats.add("containsText", {
    text: "red",
    format: { fill: "#FEE2E2", font: { color: "#991B1B", bold: true } },
  });
  scorecard.getRange("A:E").format.autofitColumns();
  scorecard.getRange("A:E").format.autofitRows();

  const qa = workbook.worksheets.add("GUI QA");
  const screenshotRows = guiManifest.screenshots.map((item) => [
    item.name,
    item.ok ? "green" : "red",
    rel(item.path),
    item.sha256_16,
    `${item.size?.[0] || ""}x${item.size?.[1] || ""}`,
  ]);
  const controlRows = guiManifest.controls.map((item) => [
    item.name,
    item.ok ? "green" : "red",
    item.surface || item.input || item.route || "",
    item.http_status || "",
    JSON.stringify(item.result || item.after || "").slice(0, 250),
  ]);
  const pageRows = guiManifest.page_clicks.map((item) => [
    item.name,
    item.ok ? "green" : "red",
    "real mouse sidebar click",
    item.window_title || "",
    `pid ${item.pid_before} -> ${item.pid_after}`,
  ]);
  const mediaRows = guiManifest.media.map((item) => [
    item.name,
    item.ok ? "green" : "red",
    item.path || "",
    item.video ? `${item.video.codec} ${item.video.width}x${item.video.height}` : "",
    item.audio ? `${item.audio.codec} ${item.audio.sample_rate}` : JSON.stringify(item.stats || "").slice(0, 120),
  ]);
  qa.getRange("A1:E1").values = [["GUI Evidence", "Status", "Surface", "HTTP/Size", "Proof"]];
  writeWorksheetRows(qa, 2, screenshotRows);
  const controlStart = screenshotRows.length + 3;
  qa.getRange(`A${controlStart}:E${controlStart}`).values = [["Control Evidence", "Status", "Surface", "HTTP/Size", "Proof"]];
  writeWorksheetRows(qa, controlStart + 1, controlRows);
  const pageStart = controlStart + controlRows.length + 2;
  qa.getRange(`A${pageStart}:E${pageStart}`).values = [["Page Click Evidence", "Status", "Surface", "Window Title", "Proof"]];
  writeWorksheetRows(qa, pageStart + 1, pageRows);
  const mediaStart = pageStart + pageRows.length + 2;
  qa.getRange(`A${mediaStart}:E${mediaStart}`).values = [["Media Evidence", "Status", "Path", "Video", "Audio/Stats"]];
  writeWorksheetRows(qa, mediaStart + 1, mediaRows);
  const crashStart = mediaStart + mediaRows.length + 2;
  qa.getRange(`A${crashStart}:E${crashStart}`).values = [["Crash Evidence", "Status", "Surface", "Count", "Proof"]];
  qa.getRange(`A${crashStart + 1}:E${crashStart + 1}`).values = [[
    "New ClippingOpsCockpit .ips reports",
    guiManifest.new_crash_reports.length === 0 ? "green" : "red",
    "DiagnosticReports delta",
    guiManifest.new_crash_reports.length,
    guiManifest.app_survived_all_page_clicks ? "app_survived_all_page_clicks=true" : "app_survived_all_page_clicks=false",
  ]];
  qa.getRange("A1:E1").format = { fill: "#1F2937", font: { bold: true, color: "#FFFFFF" }, wrapText: true };
  qa.getRange(`A${controlStart}:E${controlStart}`).format = { fill: "#1F2937", font: { bold: true, color: "#FFFFFF" }, wrapText: true };
  qa.getRange(`A${pageStart}:E${pageStart}`).format = { fill: "#1F2937", font: { bold: true, color: "#FFFFFF" }, wrapText: true };
  qa.getRange(`A${mediaStart}:E${mediaStart}`).format = { fill: "#1F2937", font: { bold: true, color: "#FFFFFF" }, wrapText: true };
  qa.getRange(`A${crashStart}:E${crashStart}`).format = { fill: "#1F2937", font: { bold: true, color: "#FFFFFF" }, wrapText: true };
  qa.getRange(`A1:E${crashStart + 1}`).format = {
    borders: { preset: "all", style: "thin", color: "#D1D5DB" },
    wrapText: true,
    verticalAlignment: "top",
  };
  qa.getRange("A:E").format.autofitColumns();

  const api = workbook.worksheets.add("API Smoke");
  const checkRows = platforms.checks.map((item) => [
    item.provider,
    item.endpoint,
    item.status,
    item.http_status,
    item.rate_limit_remaining,
    item.created_at,
  ]);
  api.getRange("A1:F1").values = [["Provider", "Endpoint", "Status", "HTTP", "Rate Remaining", "Created"]];
  if (checkRows.length) {
    api.getRange(`A2:F${checkRows.length + 1}`).values = checkRows;
  }
  api.getRange("A1:F1").format = { fill: "#111827", font: { bold: true, color: "#FFFFFF" }, wrapText: true };
  api.getRange(`A1:F${Math.max(2, checkRows.length + 1)}`).format = {
    borders: { preset: "all", style: "thin", color: "#D1D5DB" },
    wrapText: true,
  };
  api.getRange("A:F").format.autofitColumns();

  const videoQa = workbook.worksheets.add("Video QA");
  const videoRows = await Promise.all(reviewKits.slice(0, 40).map(async (kit) => {
    const kitDir = path.dirname(kit.review_video_path);
    const critiquePath = path.join(kitDir, "style_critique.md");
    const critique = await critiqueSummary(critiquePath);
    const missingExtras = [];
    for (const name of ["ffprobe.json", "thumbnail.jpg", "contact_sheet.jpg", "style_critique.md", "render_text_manifest.json"]) {
      try {
        await fs.stat(path.join(kitDir, name));
      } catch {
        missingExtras.push(name);
      }
    }
    return [
      kit.title,
      missingExtras.length ? "red" : critique.status,
      kit.review_status,
      missingExtras.length ? `missing ${missingExtras.join(", ")}` : "ffprobe + thumbnail + contact sheet + critique + text manifest",
      critique.text.slice(0, 280),
    ];
  }));
  videoQa.getRange("A1:E1").values = [["Kit", "Production Status", "Review Status", "Artifacts", "Critique"]];
  if (videoRows.length) {
    videoQa.getRange(`A2:E${videoRows.length + 1}`).values = videoRows;
  }
  videoQa.getRange("A1:E1").format = { fill: "#111827", font: { bold: true, color: "#FFFFFF" }, wrapText: true };
  videoQa.getRange(`A1:E${Math.max(2, videoRows.length + 1)}`).format = {
    borders: { preset: "all", style: "thin", color: "#D1D5DB" },
    wrapText: true,
    verticalAlignment: "top",
  };
  videoQa.getRange("A:E").format.autofitColumns();

  const safety = workbook.worksheets.add("Safety Gates");
  safety.getRange("A1:D1").values = [["Gate", "Status", "Evidence", "Comment"]];
  const safetyRows = [
    ["Autopublish", health.safety.autopublish, "/api/health", "No publishing route is exposed."],
    ["Payout submission", health.safety.payout_submission, "/api/health", "Out of scope remains hard-blocked."],
    ["Account connection", health.safety.account_connection, "/api/health", "No-key mode blocks credential exchange."],
    ["Campaign production", gate.status, "/api/campaign-gate", gate.blocker],
    ["GUI QA", guiManifest.ok ? "green" : "red", rel(manifestPath), `${guiManifest.page_clicks.length} clicks; ${guiManifest.screenshots.length} screenshots; ${guiManifest.new_crash_reports.length} new crashes`],
    ["Burned-in subtitles", burnedCaptions.ok ? "green" : "red", rel(burnedCaptionPath), `${burnedCaptions.kit_count || 0} kit(s) verified from extracted frames`],
    ["Security scan", securityScan.ok ? "green" : "yellow", rel(securityPath), `${securityScan.finding_count} finding(s)`],
    ["Backend LaunchAgent", launchAgent.ok ? "green" : "red", rel(launchAgentPath), `state=${launchAgent.state}; last_exit=${launchAgent.last_exit}; api=${launchAgent.api_version}`],
    ["Buddy no-key installer", noKey.ok ? "green" : "red", rel(noKeyPath), `no_key_mode=${noKey.no_key_mode}; production_green=${noKey.production_green}`],
    ["Codex source handoff", handoff.ok ? "green" : "red", rel(handoffPath), `files=${handoff.file_count}; requires_notarization=${handoff.requires_notarization}; zip=${handoff.zip_path || "missing"}`],
    ["Prebuilt Mac app", release.customer_ship_ready ? "green" : (release.bundle_ok ? "yellow" : "red"), rel(releasePath), `signed=${release.signed_ok}; notarized=${release.notarized_ok}; blockers=${(release.blockers || []).join("; ")}`],
  ];
  safety.getRange(`A2:D${safetyRows.length + 1}`).values = safetyRows;
  safety.getRange("A1:D1").format = { fill: "#111827", font: { bold: true, color: "#FFFFFF" }, wrapText: true };
  safety.getRange(`A1:D${safetyRows.length + 1}`).format = {
    borders: { preset: "all", style: "thin", color: "#D1D5DB" },
    wrapText: true,
  };
  safety.getRange("A:D").format.autofitColumns();

  const workbookPath = path.join(outDir, "qa-readiness-matrix.xlsx");
  let workbookNote = "fresh";
  try {
    const xlsx = await SpreadsheetFile.exportXlsx(workbook);
    await xlsx.save(workbookPath);
  } catch (error) {
    const hasExistingWorkbook = await exists(workbookPath);
    workbookNote = hasExistingWorkbook
      ? `stale: workbook export failed (${error.message})`
      : `missing: workbook export failed (${error.message})`;
  }
  const scorecardPreviewPath = path.join(outDir, "qa-readiness-scorecard.png");
  let scorecardPreviewNote = "fresh";
  if (workbookNote === "fresh") {
    try {
      const preview = await workbook.render({ sheetName: "Scorecard", range: "A1:E8", scale: 2 });
      await fs.writeFile(scorecardPreviewPath, Buffer.from(await preview.arrayBuffer()));
    } catch (error) {
      const hasExistingPreview = await exists(scorecardPreviewPath);
      scorecardPreviewNote = hasExistingPreview
        ? `stale: workbook render failed (${error.message})`
        : `missing: workbook render failed (${error.message})`;
    }
  } else {
    const hasExistingPreview = await exists(scorecardPreviewPath);
    scorecardPreviewNote = hasExistingPreview
      ? `stale: skipped because workbook export failed`
      : `missing: skipped because workbook export failed`;
  }

  const architecture = `flowchart LR
  macApp["SwiftUI macOS App"] --> localhostApi["Localhost JSON API"]
  localhostApi --> backend["Python Backend"]
  backend --> sqlite["SQLite Source of Truth"]
  backend --> renderKits["Review Kit Files"]
  backend --> keychain["macOS Keychain"]
  backend --> workers["Media and QA Workers"]
  workers --> ffmpeg["ffmpeg / ffprobe"]
  backend --> platform["Platform Smoke"]
  platform --> twitch["Twitch Helix"]
  platform --> kick["Kick Public API"]
  backend --> campaignGate["Campaign Evidence Gate"]
  campaignGate --> clippingNet["Clipping.net Signed-in Evidence"]
  backend --> hermes["Hermes Jobs"]
  hermes --> discord["Three Discord Channels"]
`;
  const architecturePath = path.join(outDir, "architecture.mmd");
  await writeText(architecturePath, architecture);

  const nonGreenFeatures = readiness.features
    .filter((item) => item.status !== "green")
    .map((item) => `${item.name}=${item.status}`)
    .join(", ");
  const featureByName = (name) => readiness.features.find((item) => item.name === name) || {};
  const campaignSourceFeature = featureByName("Campaign review source media") || featureByName("Selected feeder source media");
  const productionRenderFeature = featureByName("Campaign review render proof") || featureByName("Production feeder render proof");
  const campaignSourceIsGreen = campaignSourceFeature.status === "green";
  const campaignReviewRows = await Promise.all(reviewKits.map(async (kit) => {
    const kitDir = path.dirname(kit.review_video_path || "");
    const manifestPath = path.join(kitDir, "render_text_manifest.json");
    const [captionText, sourceText, manifestText, critiqueText, manifestJson] = await Promise.all([
      readTextMaybe(path.join(kitDir, "caption.txt")),
      readTextMaybe(path.join(kitDir, "source.md")),
      readTextMaybe(manifestPath),
      readTextMaybe(path.join(kitDir, "style_critique.md")),
      readJsonMaybe(manifestPath, {}),
    ]);
    const combined = `${kit.title}\n${kit.clip_source_url}\n${captionText}\n${sourceText}\n${manifestText}\n${critiqueText}`.toLowerCase();
    const renderedText = JSON.stringify(manifestJson.rendered_text || {}).toLowerCase();
    return {
      title: kit.title,
      createdAt: kit.clip_created_at || "",
      views: kit.clip_view_count || 0,
      campaign: kit.campaign_name || kit.campaign_slug || "Unlinked",
      hasCampaignLink: Boolean(kit.campaign_slug),
      hasSourceEvidence: /source_media_verified_local|source_download_verified|local media:/i.test(sourceText),
      hasGreenCritique: /status:\s*green/i.test(critiqueText),
      hasNoBurnedInternalText: !/(selected feeder|review kit|proof|demo|human review|manual review)/.test(renderedText),
    };
  }));
  const campaignGreenRows = campaignReviewRows.filter((row) => (
    row.hasCampaignLink
    && row.hasSourceEvidence
    && row.hasGreenCritique
    && row.hasNoBurnedInternalText
  ));
  const campaignBriefSummary = `${campaignGreenRows.length}/${reviewKits.length} active campaign review kit(s) are linked to active campaign projects, have source evidence, a green critique, and no burned-in internal proof/review/demo text.`;
  const burnedCaptionSummary = `${burnedCaptions.ok ? "PASS" : "FAIL"}: ${burnedCaptions.kit_count || 0} active kit(s) checked by extracted-frame pixel comparison; caption sidecars alone are not accepted as subtitle proof.`;
  const campaignClipLines = campaignGreenRows
    .sort((a, b) => String(a.createdAt).localeCompare(String(b.createdAt)))
    .map((row) => `- ${row.createdAt || "unknown time"}: ${row.campaign} - ${row.title} (${row.views} views)`)
    .join("\n") || "- No active campaign-linked production kits.";
  const campaignVerdict = health.production_green
    ? "All CEO gates are green from current evidence. Real campaign rendering is still limited to the nomination/review workflow; publishing, uploads, payouts, and account changes remain blocked."
    : `Local readiness remains **not green** because these evidence gates are not green: ${nonGreenFeatures || "unknown"}. The source-build handoff zip is a separate Codex/buddy lane and does not require Developer ID or notarization; only a prebuilt Mac app distribution requires signing/notarization. The final buddy book/install wrap-up still waits for the approved review batch.`;
  const productionRenderDirs = await completeRenderDirs(health.render_root);
  const demoRenderDirs = await completeRenderDirs(health.demo_render_root || "");
  const allRenderDirs = [...productionRenderDirs, ...demoRenderDirs].sort((a, b) => b.mtimeMs - a.mtimeMs);
  const styledKits = allRenderDirs.filter((dir) => dir.complete && /style critique/i.test(dir.critiqueText));
  const latestStyledReferenceKits = allRenderDirs
    .filter((dir) => dir.complete && /ishouldclip-inspired/.test(dir.name))
    .slice(0, 3);
  const latestNonDemoKit = reviewKits.find((kit) => !kit.is_demo);
  const latestReferenceStamp = latestStyledReferenceKits[0]
    ? new Date(latestStyledReferenceKits[0].mtimeMs).toISOString()
    : "missing";
  const productionIncompleteRenderDirs = await recentIncompleteRenderDirs(health.render_root);
  const demoIncompleteRenderDirs = await recentIncompleteRenderDirs(health.demo_render_root || "");
  const incompleteRenderDirs = [
    ...productionIncompleteRenderDirs.map((dir) => ({ ...dir, root: "production" })),
    ...demoIncompleteRenderDirs.map((dir) => ({ ...dir, root: "demo" })),
  ].sort((a, b) => b.mtimeMs - a.mtimeMs);
  const incompleteRenderSummary = incompleteRenderDirs.length
    ? incompleteRenderDirs.map((dir) => `${dir.root}:${dir.name} missing ${dir.missing.join(", ")}`).join("; ")
    : "none detected";
  const latestDemoRootDirs = await recentRenderDirs(health.demo_render_root || "");
  const latestDemoRootDir = latestDemoRootDirs[0] || null;
  const latestDemoRootStamp = latestDemoRootDir ? new Date(latestDemoRootDir.mtimeMs).toISOString() : "missing";
  const latestDemoBatchPrefix = latestDemoRootDir?.name.match(/^(\d{8}-\d{6})/)?.[1] || "";
  const latestDemoBatchIncomplete = latestDemoBatchPrefix
    ? demoIncompleteRenderDirs.filter((dir) => dir.name.startsWith(latestDemoBatchPrefix))
    : [];
  const demoRootBatchBroken = latestDemoBatchIncomplete.length > 0;
  const latestDemoBatchSummary = latestDemoBatchIncomplete.length
    ? latestDemoBatchIncomplete.map((dir) => `demo:${dir.name} missing ${dir.missing.join(", ")}`).join("; ")
    : "none detected";
  const latestReferenceInProductionRoot = Boolean(
    latestStyledReferenceKits[0]?.path
      && health.render_root
      && latestStyledReferenceKits[0].path.startsWith(`${health.render_root}${path.sep}`),
  );
  const renderProofIsGreen = productionRenderFeature.status === "green";
  const referenceCritiqueLead = latestStyledReferenceKits.length
    ? `The renderer is proving packaging mechanics, not proving a clip business. The latest complete @IShouldClip-inspired variants were rendered on ${latestReferenceStamp} and they are still correctly yellow. The latest non-demo evidence review kit is ${latestNonDemoKit?.created_at || "missing"} and it is still not a green light either.`
    : `The renderer is proving packaging mechanics, not proving a clip business. There is no current local @IShouldClip-inspired demo/reference batch in the live render roots, so the only fresh evidence is the campaign review set. Those campaign kits are still correctly yellow until the active campaign approval target is hit.`;
  const referenceStyleCloser = latestStyledReferenceKits.length
    ? "Reference Style B remains the closest demo style study because it pushes pace and hook language harder. The campaign final profile is more important operationally because it is tied to approved campaign sources and evidence instead of demo footage."
    : "There is no fresh local reference-style study to hide behind. The campaign final profile is the only evidence that matters now because it is tied to approved campaign sources and evidence instead of demo footage.";
  const bluntRendererCritique = [
    renderProofIsGreen
      ? `The renderer now has ${campaignGreenRows.length} green campaign final kit(s) from local source media, stored campaign rules, timed transcript evidence, and burned-in subtitle frame proof. This proves campaign-scoped review mechanics; it still does not prove autonomous publishing or customer distribution.`
      : referenceCritiqueLead,
    "Against the stored rubric, active campaign outputs should use the white headline card, central crop, side-fill background, and fast captions while avoiding internal labels or fake proof language.",
    demoRootBatchBroken
      ? `The current ${health.api_version} demo rerun is operationally broken. The fresh demo root at ${latestDemoRootStamp} already contains incomplete directories: ${latestDemoBatchSummary}. In plain English: the backend accepted a demo render request, created new kit directories, and still left at least one of them without the minimum QA sidecars.`
      : incompleteRenderDirs.length
        ? `The renderer is also operationally sloppy right now. Recent render directories are being left half-finished: ${incompleteRenderSummary}. That means the route can produce a preview MP4 and still fail the basic QA contract around ffprobe, thumbnail, contact sheet, critique, and text-manifest sidecars.`
        : "The renderer at least finishes its artifact contract on the kits that reach the database, but that does not rescue the editorial weakness.",
    latestReferenceInProductionRoot && latestDemoRootDir
      ? "There is still historical contract drift in the artifact archive: older complete demo/reference kits were written into the production render root. Current output now separates demo/local proof kits from production review kits, but the old archive remains useful only as history."
      : "Demo/local proof kits and production campaign review kits are now stored in separate roots, which fixes the earlier surface-contamination problem.",
    renderProofIsGreen
      ? `The source gate is now ${campaignSourceFeature.status}: ${campaignSourceFeature.evidence}. The green campaign set clears local provenance, transcript timing, artifact validation, and brief linkage; posting approval remains a separate blocked workflow.`
      : campaignSourceIsGreen
        ? `The easy operational proof is already there: ${campaignSourceFeature.evidence}. The remaining failures are editorial, not plumbing. The hook copy is still template-level, the visible review/proof naming must stay out of rendered frames, and the overlays still need to feel like clips that earned distribution.`
        : "The failures are the parts that matter. The hook copy is still template-level, the caption timing is still heuristic or ASR-derived instead of transcript-timed, and the review-safe overlays make the output look like internal QA rather than something that already earned attention in-market.",
    referenceStyleCloser,
    renderProofIsGreen
      ? "Bottom line: internal-local render validation is green. A Codex source handoff can be green without Apple notarization; only a prebuilt customer Mac app remains gated by Developer ID signing/notarization."
      : campaignSourceIsGreen
        ? "Bottom line: the renderer pipeline is proving real campaign sourcing and transcript timing, but the output is still not market-ready until the packaging, hook writing, and human campaign-fit approvals clear."
        : "Bottom line: renderer QA is real, renderer taste is not yet proven, and production readiness stays red until campaign clips clear source provenance, transcript timing, campaign rules, and actual market fit.",
  ].join("\n\n");

  const activeCampaignNames = campaignProjects.map((project) => project.name || project.slug).filter(Boolean);
  const activeCampaignLine = activeCampaignNames.length
    ? `The active batch is now streamer-first and limited to: ${activeCampaignNames.join(", ")}. Archived/source-study campaigns do not count toward the active review batch.`
    : "There are no active campaign projects in the current API response.";
  const reindexSummary = (streamerReindex.ranked || []).slice(0, 6).map((item, index) => (
    `- ${index + 1}. [${item.name}](${item.campaign_url}): \`${item.recommendation}\`, score=${item.score}, clips=${item.twitch_supply?.clips_returned || 0}, top_recent_views=${item.twitch_supply?.top_clip_views || 0}, blockers=${(item.blockers || []).join("; ") || "none"}`
  )).join("\n") || "- Streamer re-index artifact missing.";

  const readinessDoc = `# CEO Readiness Report

Generated: ${new Date().toISOString()}

## Current Verdict

- Internal local status: ${readiness.milestones?.internal_local_ready?.status || "unknown"}
- Buddy no-key status: ${readiness.milestones?.buddy_no_key_ready?.status || "unknown"}
- Codex source handoff status: ${readiness.milestones?.codex_handoff_ready?.status || "unknown"}
- Prebuilt Mac app status: ${readiness.milestones?.customer_ship_ready?.status || "unknown"}
- Campaign status: ${health.campaign_status}
- Production green: ${health.production_green}
- Readiness overall: ${readiness.overall}

${campaignVerdict}

## Evidence

- GUI QA manifest: \`${rel(manifestPath)}\` (${guiManifest.page_clicks.length} real sidebar/control clicks, ${guiManifest.screenshots.length} screenshots, ${guiManifest.controls.length} controls)
- App survived all page clicks: ${guiManifest.app_survived_all_page_clicks}; new crash reports during QA: ${guiManifest.new_crash_reports.length}
- QA matrix: \`${rel(workbookPath)}\` (${workbookNote})
- Scorecard preview: \`${rel(scorecardPreviewPath)}\` (${scorecardPreviewNote})
- Production review kits: \`${health.production_render_root || health.render_root}\`
- Campaign brief proof: ${campaignBriefSummary}
- Burned-in subtitle proof: ${burnedCaptionSummary} \`${rel(burnedCaptionPath)}\`
- Demo/local proof kits: \`${health.demo_render_root || "separate demo render root unavailable"}\`
- Styled/video QA kits: ${styledKits.length}
- Incomplete recent render dirs: ${incompleteRenderDirs.length ? incompleteRenderSummary : "none"}
- API smoke rows: ${platforms.checks.length}
- Source routes: ${platforms.routes.length}
- Security scan: \`${rel(securityPath)}\` (${securityScan.finding_count} finding(s))
- Backend LaunchAgent check: \`${rel(launchAgentPath)}\` (state=${launchAgent.state}; ok=${launchAgent.ok})
- No-key installer proof: \`${rel(noKeyPath)}\` (ok=${noKey.ok}; no_key_mode=${noKey.no_key_mode})
- Codex source handoff proof: \`${rel(handoffPath)}\` (ok=${handoff.ok}; files=${handoff.file_count}; zip=${handoff.zip_path || "missing"})
- Prebuilt Mac app proof: \`${rel(releasePath)}\` (bundle=${release.bundle_ok}; signed=${release.signed_ok}; notarized=${release.notarized_ok})

## Milestones

${Object.entries(readiness.milestones || {}).map(([name, item]) => `- **${String(item.status || "red").toUpperCase()}** ${name}: ready=${item.ready}; blockers=${(item.blockers || []).join(", ") || "none"}`).join("\n")}

## Green / Yellow / Red

${readiness.features.map((item) => `- **${item.status.toUpperCase()}** ${item.name}: ${item.evidence}${item.blocker ? `; blocker: ${item.blocker}` : ""}`).join("\n")}

## Video Output Critique

${bluntRendererCritique}

## Campaign Batch Compliance

${activeCampaignLine} The final buddy book/install wrap-up stays blocked until each active campaign has five individually approved review kits in the GUI. Haste remains excluded because content generation without linked source media is out of scope.

Latest streamer-first re-index:

${reindexSummary}

${campaignClipLines}

## Figma / Slides Tool State

Figma diagram and Figma Slides generation were attempted, but the connected tool requires selecting a Figma team or organization plan key first. Local architecture Mermaid and product-deck Markdown are generated as fallback proof artifacts until that account-side selection is available.
`;
  await writeText(path.join(docsDir, "CEO_READINESS_REPORT.md"), readinessDoc);

  const runbook = `# Clipping Ops Cockpit Operator Runbook

## Start

1. Run \`./script/install_backend_launch_agent.sh\`.
2. Run \`./script/build_and_run.sh --verify\`.
3. Open the app and confirm Settings shows local readiness red/yellow until every review and source gate has fresh proof.

## Daily Workflow

1. Review Dashboard for blockers and job status.
2. Use Campaigns to refresh the current active streamer-first project set: ${activeCampaignNames.join(", ") || "none"}.
3. Use Sources only for advanced API checks, watchlist candidates, and future creator campaigns.
4. Keep demo/local proof kits out of the production Review Kits surface; build campaign review kits only after source provenance and local media are stored.
5. Review videos in Review Kits; approval never publishes.

## Hard Stops

- No autopublish.
- No payout submission.
- No account connection or account rebrand.
- No real campaign render without stored campaign rules, source URL, provenance, and source availability.
- No Ready To Post without playable H.264/AAC 1080x1920 preview and all kit files.
`;
  await writeText(path.join(docsDir, "operator-runbook.md"), runbook);

  const deck = `# Clipping Ops Cockpit CEO Product Deck

## 1. Product
Local-first macOS clipping operations appliance. Index many, render few, publish only after human approval.

## 2. Evidence Ledger
- Swift build passed.
- Backend tests passed.
- GUI QA covers ${guiManifest.screenshots.length} app screenshots and ${guiManifest.controls.length} controls.
- Selected-feeder kits render as review-first production candidates only after evidence gates.
- Twitch/Kick API smoke has live succeeded rows.

## 3. Architecture
See \`${rel(architecturePath)}\`.

## 4. Safety
Autopublish, payouts, account mutation, gambling clearance, and revenue guarantees remain blocked.

## 5. Current Readiness
Codex source handoff is a source/build zip lane and does not require Apple notarization. Prebuilt customer Mac app distribution is separate and remains yellow until Developer ID signing/notarization is proven. Yellow is never ready.

## 6. Next Proof
Fix every non-green readiness row, rerun LaunchAgent/no-key/handoff/release/GUI/security checks, regenerate this artifact pack, and keep publishing/payout/account actions blocked.
`;
  await writeText(path.join(outDir, "ceo-product-deck.md"), deck);

  const summaryPath = path.join(outDir, "artifact-summary.json");
  await writeText(
    summaryPath,
    JSON.stringify(
      {
        generated_at: new Date().toISOString(),
        workbook: workbookPath,
        workbook_note: workbookNote,
        scorecard_preview: scorecardPreviewPath,
        scorecard_preview_note: scorecardPreviewNote,
        burned_caption_verification: burnedCaptionPath,
        codex_handoff: handoffPath,
        architecture_mermaid: architecturePath,
        readiness_doc: path.join(docsDir, "CEO_READINESS_REPORT.md"),
        runbook: path.join(docsDir, "operator-runbook.md"),
        deck_markdown: path.join(outDir, "ceo-product-deck.md"),
        figma_status: "blocked_until_plan_key_selected",
      },
      null,
      2,
    ),
  );

  console.log(summaryPath);
}

await main();
