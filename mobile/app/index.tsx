import { Redirect } from 'expo-router';
import { useApp } from '../src/state/services';

export default function Index() {
  const user = useApp((s) => s.user);
  if (!user) return <Redirect href="/sign-in" />;
  return <Redirect href={user.role === 'patient' ? '/home' : '/patients'} />;
}
