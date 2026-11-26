import { readStorage, writeStorage } from './storage';

const KEY = 'ballpark_device_id';
let memoryId: string | null = null;

function randomUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  // RFC 4122 v4 fallback
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

/** Random per-device UUID, persisted in localStorage when available. */
export function getDeviceId(): string {
  const stored = readStorage(KEY);
  if (stored) return stored;
  if (!memoryId) {
    memoryId = randomUUID();
    writeStorage(KEY, memoryId);
  }
  return memoryId;
}
