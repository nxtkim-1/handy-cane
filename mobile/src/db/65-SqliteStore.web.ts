// Web build: expo-sqlite needs a WebAssembly bundle we do not ship. Web is only used for testing the
// app in a browser, so keep the data in memory (services.ts already does this on web).
import type { LocalStore } from './LocalStore';
import { MemoryStore } from './MemoryStore';

export class SqliteStore {
  static async open(): Promise<LocalStore> {
    return new MemoryStore();
  }
}
