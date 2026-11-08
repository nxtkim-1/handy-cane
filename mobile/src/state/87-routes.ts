import type { User } from '../api/types';
import { pendingConsent } from './consent';

/** Where a signed-in user lands. Patients see their own tabs; caregivers and clinicians start at the patient list. */
export function homeRouteFor(user: User | null, ready = true): '/splash' | '/sign-in' | '/consent' | '/home' | '/patients' {
  if (!ready) return '/splash';
  if (!user) return '/sign-in';
  if (pendingConsent(user)) return '/consent';
  return user.role === 'patient' ? '/home' : '/patients';
}

/** Can this user dismiss alerts for this patient? Clinicians acknowledge only; caregivers as the patient allowed. */
export function canDismissFor(user: User, pid: string): boolean {
  if (user.role === 'clinician') return false;
  const a = user.patients.find((p) => p.patient_id === pid);
  if (!a) return false;
  return user.role === 'patient' ? a.relation === 'self' || a.can_dismiss_events : a.can_dismiss_events;
}
