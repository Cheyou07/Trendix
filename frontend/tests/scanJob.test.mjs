import test from "node:test";
import assert from "node:assert/strict";
import { requestJson } from "../src/http.js";
import { runScanJob, waitFor } from "../src/scanJob.js";

function clock() {
  let elapsed = 0;
  return { now: () => elapsed, wait: async (ms) => { elapsed += ms; } };
}

test("HTTP 429 metadata drives countdown, admission retry, and successful polling", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const statuses = [];
  const responses = [
    new Response(JSON.stringify({ detail: "Cooling down" }), { status: 429, headers: { "Retry-After": "3" } }),
    new Response(JSON.stringify({ job_id: "shared-job", status: "running" }), { status: 202 }),
    new Response(JSON.stringify({ status: "running" })),
    new Response(JSON.stringify({ status: "completed", result: { results: ["TEST"] } })),
  ];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return responses.shift();
  };
  try {
    const time = clock();
    const result = await runScanJob((path, options) => requestJson("/api", path, options),
      { index: "NIFTY500" }, { ...time, onStatus: (s) => statuses.push(s) });
    assert.deepEqual(result, { results: ["TEST"] });
    assert.deepEqual(calls.map((c) => c.url), ["/api/runs", "/api/runs", "/api/runs/shared-job", "/api/runs/shared-job"]);
    assert.equal(calls[0].options.body, calls[1].options.body);
    assert.equal(time.now(), 6000);
    assert.deepEqual(statuses.filter((s) => s.includes("automatically")).map((s) => s.match(/(\d+)s/)[1]), ["3", "2", "1"]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("busy responses without Retry-After use a safe delay", async () => {
  const time = clock();
  let posts = 0;
  const request = async (path) => {
    if (path === "/runs") {
      if (++posts === 1) throw Object.assign(new Error("Busy"), { status: 429 });
      return { job_id: "job" };
    }
    return { status: "completed", result: {} };
  };
  await runScanJob(request, {}, time);
  assert.equal(time.now(), 30000);
  assert.equal(posts, 2);
});

test("actual scan failure is shown without resubmitting", async () => {
  let posts = 0;
  await assert.rejects(runScanJob(async (path) => {
    if (path === "/runs") { posts++; return { job_id: "job" }; }
    return { status: "failed", error: "Market data unavailable" };
  }, {}, clock()), /Market data unavailable/);
  assert.equal(posts, 1);
});

test("non-429 admission errors are not retried", async () => {
  let calls = 0;
  await assert.rejects(runScanJob(async () => {
    calls++;
    throw Object.assign(new Error("Invalid request"), { status: 400 });
  }, {}, clock()), /Invalid request/);
  assert.equal(calls, 1);
});

test("stopping a cooldown prevents another submission", async () => {
  const controller = new AbortController();
  let calls = 0;
  await assert.rejects(runScanJob(async () => {
    calls++;
    throw Object.assign(new Error("Busy"), { status: 429, retryAfter: 60 });
  }, {}, { signal: controller.signal, now: () => 0, wait: async () => controller.abort() }),
  { name: "AbortError" });
  assert.equal(calls, 1);
});

test("stopping an in-flight HTTP request preserves cancellation", async () => {
  const originalFetch = globalThis.fetch;
  const controller = new AbortController();
  globalThis.fetch = async (url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  });
  try {
    const pending = requestJson("/api", "/runs/job", { signal: controller.signal });
    controller.abort();
    await assert.rejects(pending, { name: "AbortError" });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("cancellable timers reject immediately when stopped", async () => {
  const controller = new AbortController();
  const pending = waitFor(60000, controller.signal);
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
});

test("repeated busy responses stop at the overall deadline", async () => {
  const time = clock();
  await assert.rejects(runScanJob(async () => {
    throw Object.assign(new Error("Busy"), { status: 429, retryAfter: 60 });
  }, {}, time), /30 minutes/);
  assert.equal(time.now(), 30 * 60 * 1000);
});
