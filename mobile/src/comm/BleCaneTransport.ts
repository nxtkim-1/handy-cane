import type { CaneEventRecord, CaneInfo, PullPage } from '../types';
import type { CaneTransport } from './CaneTransport';

/**
 * STUB (Phase 2). Intended design: MASTER 7.6 GATT service with a control
 * characteristic (HELLO/TIME_SYNC/PULL/ACK as framed commands), a data
 * characteristic (notify, PAGE chunks reassembled by seq), and an alert
 * characteristic (notify, CaneEventRecord). Uses react-native-ble-plx in a
 * dev build (not Expo Go). The sync loop in src/sync does not change.
 */
export class BleCaneTransport implements CaneTransport {
  private nope(): never {
    throw new Error('BleCaneTransport is not implemented yet (Phase 2). Use HttpCaneTransport.');
  }
  connect(): Promise<CaneInfo> { return this.nope(); }
  timeSync(_t: number): Promise<void> { return this.nope(); }
  pull(_a: number, _l: number): Promise<PullPage> { return this.nope(); }
  ack(_u: number): Promise<void> { return this.nope(); }
  onAlert(_cb: (e: CaneEventRecord) => void): () => void { return this.nope(); }
  disconnect(): Promise<void> { return this.nope(); }
}
