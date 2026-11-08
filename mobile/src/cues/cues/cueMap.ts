/** The five approved voice cues. Clip file is `<key>.mp3` on the cane. */
export const CUE_KEYS = ['dropped', 'ask_ok', 'help', 'cancelled', 'sos'] as const;
export type CueKey = (typeof CUE_KEYS)[number];

const LEGACY: Record<string, CueKey> = {
  cane_down: 'dropped',
  alert: 'help',
  flow_cancelled: 'cancelled',
};

/** Maps a cane event type to a cue key, or null when the event is not spoken. */
export function mapCue(eventType: string): string | null {
  if (typeof eventType !== 'string') return null;
  if (eventType.startsWith('cue:')) {
    const key = eventType.slice(4);
    return (CUE_KEYS as readonly string[]).includes(key) ? key : null;
  }
  return Object.prototype.hasOwnProperty.call(LEGACY, eventType) ? LEGACY[eventType] : null;
}
