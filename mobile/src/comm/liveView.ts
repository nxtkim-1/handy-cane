import type { LiveSample } from '../types';
import type { CaneTransport } from './CaneTransport';
import { CaneHttpError } from './HttpCaneTransport';

export const LIVE_UNAVAILABLE_TEXT = 'Live view is not available on this cane';

/** True for "this cane has no live view" (no live() on the transport, or HTTP 404), as opposed to a passing glitch. */
export function liveIsUnavailable(t: CaneTransport, e?: unknown): boolean {
  if (!t.live) return true;
  return e instanceof CaneHttpError && e.status === 404;
}

/**
 * Polls live() once a second. Calls onUnavailable exactly once and stops polling when the cane has no
 * live view; other failures are reported through onError and polling continues.
 */
export function startLivePoller(
  transport: CaneTransport,
  cb: { onSample(s: LiveSample): void; onError(msg: string): void; onUnavailable(): void },
  everyMs = 1000,
): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setInterval> | null = null;
  const halt = () => { stopped = true; if (timer) clearInterval(timer); timer = null; };
  const tick = async () => {
    if (stopped) return;
    if (!transport.live) { halt(); cb.onUnavailable(); return; }
    try {
      const s = await transport.live();
      if (!stopped) cb.onSample(s);
    } catch (e) {
      if (stopped) return;
      if (liveIsUnavailable(transport, e)) { halt(); cb.onUnavailable(); return; }
      cb.onError(e instanceof Error ? e.message : 'Lost the cane.');
    }
  };
  void tick();
  if (!stopped) timer = setInterval(() => { void tick(); }, everyMs);
  return halt;
}
