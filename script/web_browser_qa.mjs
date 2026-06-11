#!/usr/bin/env node
import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const requireFromWeb = createRequire(path.join(root, "web", "package.json"));
const { chromium } = requireFromWeb("playwright");

const baseUrl = process.env.CLIPPING_OPS_WEB_URL || "http://127.0.0.1:8765/app";
const outDir = path.join(root, "artifacts", "web-qa");
const routes = [
  ["dashboard", baseUrl],
  ["reviews", `${baseUrl}/reviews`],
  ["campaigns", `${baseUrl}/campaigns`],
  ["readiness", `${baseUrl}/readiness`],
  ["settings", `${baseUrl}/settings`],
  ["advanced", `${baseUrl}/advanced`]
];

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function run() {
  await fs.mkdir(outDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => pageErrors.push(String(error)));

  const manifest = {
    ok: false,
    generated_at: new Date().toISOString(),
    base_url: baseUrl,
    screenshots: [],
    route_checks: [],
    interaction_checks: [],
    console_errors: consoleErrors,
    page_errors: pageErrors
  };

  for (const [name, url] of routes) {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForSelector("#root", { timeout: 10000 });
    await page.waitForSelector('.app-frame[data-loaded="true"]', { timeout: 30000 });
    const text = await page.locator("body").innerText({ timeout: 10000 });
    assert(text.includes(name === "dashboard" ? "Dashboard" : name === "reviews" ? "Review Kits" : name[0].toUpperCase() + name.slice(1)), `${name} route missing expected title`);
    const file = path.join(outDir, `${name}-desktop.png`);
    await page.screenshot({ path: file, fullPage: true });
    manifest.screenshots.push(file);
    manifest.route_checks.push({ route: name, ok: true, url });
  }

  await page.goto(`${baseUrl}/reviews`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForSelector('.app-frame[data-loaded="true"]', { timeout: 30000 });
  await page.getByRole("button", { name: "Approved", exact: true }).click();
  await page.getByRole("button", { name: "Rejected", exact: true }).click();
  await page.getByRole("button", { name: "All", exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll(".kit-row").length > 0, null, { timeout: 15000 }).catch(() => undefined);
  await page.getByPlaceholder("Search reviews").fill("YourRAGE");
  await page.getByPlaceholder("Search reviews").fill("");
  manifest.interaction_checks.push({ name: "review filters and search", ok: true });

  const kitCount = await page.locator(".kit-row").count();
  if (kitCount > 0) {
    await page.locator(".kit-row").first().click();
    await page.getByRole("button", { name: "TT", exact: true }).click();
    await page.waitForSelector(".platform-chrome.tt", { timeout: 5000 });
    await page.getByRole("button", { name: "IG", exact: true }).click();
    await page.waitForSelector(".platform-chrome.ig", { timeout: 5000 });
    await page.getByRole("button", { name: "YT", exact: true }).click();
    await page.waitForSelector(".platform-chrome.yt", { timeout: 5000 });
    const videoCount = await page.locator("video").count();
    assert(videoCount > 0, "selected review kit did not show a video element");
    const file = path.join(outDir, "reviews-overlay-desktop.png");
    await page.screenshot({ path: file, fullPage: true });
    manifest.screenshots.push(file);
    manifest.interaction_checks.push({ name: "platform overlay toggles", ok: true, kit_count: kitCount });
  } else {
    manifest.interaction_checks.push({ name: "platform overlay toggles", ok: true, skipped: "no visible review kits" });
  }

  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForSelector("#root", { timeout: 10000 });
  await page.waitForSelector('.app-frame[data-loaded="true"]', { timeout: 30000 });
  const mobileFile = path.join(outDir, "dashboard-mobile.png");
  await page.screenshot({ path: mobileFile, fullPage: true });
  manifest.screenshots.push(mobileFile);
  manifest.route_checks.push({ route: "dashboard-mobile", ok: true, url: baseUrl });

  await browser.close();
  const relevantErrors = consoleErrors.filter((item) => !item.includes("favicon"));
  assert(relevantErrors.length === 0, `console errors: ${relevantErrors.join(" | ")}`);
  assert(pageErrors.length === 0, `page errors: ${pageErrors.join(" | ")}`);
  manifest.ok = true;
  const manifestPath = path.join(outDir, "manifest.json");
  await fs.writeFile(manifestPath, JSON.stringify(manifest, null, 2) + "\n", "utf8");
  console.log(JSON.stringify({ ok: true, manifest: manifestPath, screenshots: manifest.screenshots.length }, null, 2));
}

run().catch(async (error) => {
  await fs.mkdir(outDir, { recursive: true });
  const manifestPath = path.join(outDir, "manifest.json");
  await fs.writeFile(manifestPath, JSON.stringify({ ok: false, error: String(error), generated_at: new Date().toISOString() }, null, 2) + "\n", "utf8");
  console.error(error);
  process.exit(1);
});
