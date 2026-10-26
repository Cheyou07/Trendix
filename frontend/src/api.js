const BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

async function request(path, options) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 90000);
  try {
    const res = await fetch(`${BASE}${path}`, { ...options, signal: controller.signal });
    const body = await res.json().catch(() => null);
    if (!res.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed: ${res.status}`);
    if (body === null) throw new Error("The server may still be waking up. Please retry in a minute.");
    return body;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("The server took too long to respond. Please retry in a minute.");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function runJob(parameters) {
  const { job_id } = await request("/runs", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(parameters),
  });
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const job = await request(`/runs/${job_id}`);
    if (job.status === "completed") return job.result;
    if (job.status === "failed") throw new Error(job.error);
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
  throw new Error("This scan took longer than 30 minutes. Please retry later.");
}

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

export async function runScan(index, setup, nearMatches = true, nearMatchScore = 70) {
  return runJob({ index, setup, mode: "single", near_matches: nearMatches, near_match_score: nearMatchScore });
}

export async function runScanAll(index, direction = "all") {
  return runJob({ index, direction, mode: "all" });
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
