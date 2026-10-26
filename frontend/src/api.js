import { requestJson } from "./http";
import { runScanJob } from "./scanJob";

const BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");
const request = (path, options) => requestJson(BASE, path, options);

export function getDailyRuns(index, setup) {
  return request(`/history?${new URLSearchParams({ index, setup })}`);
}

export function getDailyRun(index, setup, day) {
  return request(`/history/${day}?${new URLSearchParams({ index, setup })}`);
}

export async function getIndices() {
  return request("/indices");
}

export async function getSetups() {
  return request("/setups");
}

export async function runScan(index, setup, nearMatches = true, nearMatchScore = 70, options) {
  return runScanJob(request, { index, setup, mode: "single", near_matches: nearMatches, near_match_score: nearMatchScore }, options);
}

export async function runScanAll(index, direction = "all", options) {
  return runScanJob(request, { index, direction, mode: "all" }, options);
}

export async function getStockDetail(symbol, setup) {
  const res = await fetch(`${BASE}/stocks/${encodeURIComponent(symbol)}/detail?setup=${encodeURIComponent(setup)}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Detail failed: ${res.status}`);
  }
  return res.json();
}

export async function getStockHistory(symbol, timeframe = "daily") {
  const res = await fetch(`${BASE}/stocks/${encodeURIComponent(symbol)}/history?timeframe=${timeframe}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `History failed: ${res.status}`);
  }
  return res.json();
}

export function downloadUrl(symbol, timeframe = "daily") {
  return `${BASE}/stocks/${encodeURIComponent(symbol)}/download?timeframe=${timeframe}`;
}
