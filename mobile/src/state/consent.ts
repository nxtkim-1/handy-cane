/** Consent rules (MASTER 16.6). Pure functions and thin API wrappers, easy to unit test. */
import type { ApiClient } from '../api/ApiClient';
import type { PatientAccess, User } from '../api/types';

/**
 * The patient this user must give consent for before using the app, or null.
 * Clinicians never give consent; patients and caregivers do, for the patient whose data is collected.
 */
export function pendingConsent(user: User | null): PatientAccess | null {
  if (!user || user.role === 'clinician') return null;
  return user.patients.find((p) => p.relation !== 'clinician' && !p.consent_at) ?? null;
}

export function canManageOwnData(user: User, pid: string | null): boolean {
  return !!pid && user.patients.some((p) => p.patient_id === pid && p.relation === 'self');
}

/** True when the typed text is exactly the word that confirms deletion. */
export function deleteConfirmed(typed: string): boolean {
  return typed.trim() === 'DELETE';
}

export type ConsentStep = 'ask' | 'saving' | 'done' | 'error';

/** Accept: records consent on the server, then re-reads the user so the gate sees consent_at. */
export async function acceptConsent(api: ApiClient, pid: string): Promise<User> {
  await api.giveConsent(pid);
  return api.me();
}

/** Used by Profile: both end with the caller signing out. */
export async function withdrawConsent(api: ApiClient, pid: string): Promise<void> {
  await api.withdrawConsent(pid);
}

export async function deleteMyData(api: ApiClient, pid: string, typed: string): Promise<void> {
  if (!deleteConfirmed(typed)) throw new Error('Type DELETE to confirm.');
  await api.deleteData(pid);
}
