export async function requestJson(base, path, options = {}) {
  const controller = new AbortController();
  const { signal, ...fetchOptions } = options;
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timeout = setTimeout(abort, 90000);
  try {
    const res = await fetch(`${base}${path}`, { ...fetchOptions, signal: controller.signal });
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      const error = new Error(typeof body?.detail === "string" ? body.detail : `Request failed: ${res.status}`);
      error.status = res.status;
      const header = res.headers.get("Retry-After");
      const seconds = header ? Number(header) : NaN;
      error.retryAfter = Number.isFinite(seconds) ? Math.max(1, Math.min(300, seconds)) : 30;
      throw error;
    }
    if (body === null) throw new Error("The server may still be waking up. Please retry in a minute.");
    return body;
  } catch (error) {
    if (signal?.aborted) throw new DOMException("Stopped waiting for this scan.", "AbortError");
    if (error.name === "AbortError") throw new Error("The server took too long to respond. Please retry in a minute.");
    throw error;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}
