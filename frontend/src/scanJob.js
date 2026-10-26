export function waitFor(ms, signal) {
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reject(new DOMException("Stopped waiting for this scan.", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
  });
}

// Retry admission only. A failed scan is surfaced, never silently resubmitted.
export async function runScanJob(request, parameters, {
  onStatus = () => {}, signal, wait = waitFor, now = Date.now,
} = {}) {
  const deadline = now() + 30 * 60 * 1000;
  const checkDeadline = () => {
    if (signal?.aborted) throw new DOMException("Stopped waiting for this scan.", "AbortError");
    if (now() >= deadline) throw new Error("This scan could not finish within 30 minutes. Please retry later.");
  };
  let jobId;
  while (!jobId) {
    checkDeadline();
    onStatus("Connecting to the scanner…");
    try {
      const job = await request("/runs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parameters), signal,
      });
      jobId = job.job_id;
      if (!jobId) throw new Error("The server returned an invalid scan response.");
    } catch (error) {
      if (error.status !== 429) throw error;
      const seconds = Number(error.retryAfter);
      const delay = Number.isFinite(seconds) ? Math.max(1, Math.min(300, seconds)) : 30;
      const retryAt = now() + delay * 1000;
      while (now() < retryAt) {
        checkDeadline();
        const remaining = Math.ceil((retryAt - now()) / 1000);
        onStatus(`The scan queue is full. Retrying automatically in ${remaining}s…`);
        await wait(Math.min(1000, retryAt - now(), deadline - now()), signal);
      }
    }
  }
  onStatus("Scanning… Large indexes can take several minutes. Keep this page open.");
  while (true) {
    checkDeadline();
    const job = await request(`/runs/${jobId}`, { signal });
    checkDeadline();
    if (job.status === "completed") return job.result;
    if (job.status === "failed") throw new Error(job.error || "The scan failed. Please retry later.");
    if (job.status === "queued") {
      onStatus(`Your scan is queued (position ${job.queue_position}). It will start automatically.`);
    } else if (job.status === "running") {
      const progress = job.progress || {};
      const elapsed = job.elapsed_seconds || 0;
      const limit = job.timeout_seconds || 600;
      const detail = progress.total
        ? `${progress.phase === "fetching" ? "Fetching prices" : "Evaluating setups"}: ${progress.done}/${progress.total} stocks processed`
        : "Starting the scan";
      onStatus(`${detail}. ${elapsed}s elapsed; server limit ${limit}s.`);
    } else {
      throw new Error("The server returned an unknown scan status. Please retry.");
    }
    await wait(Math.min(3000, deadline - now()), signal);
  }
}
