import React from 'react';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { signOut, useApp } from '../state/services';
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View, type TextInputProps,
} from 'react-native';

// MASTER 15.1: 18 pt body, 48 dp touch targets, high contrast.
export const colors = {
  bg: '#FFFFFF',
  card: '#F3F5F8',
  text: '#10151C',
  sub: '#3B4654',
  primary: '#0B4F9E',
  onPrimary: '#FFFFFF',
  danger: '#9B1C1C',
  warn: '#8A5A00',
  ok: '#14633A',
  grey: '#B5BCC6',
  border: '#8A94A3',
  sim: '#5B2A86',
};

export const type = { body: 18, small: 16, h1: 28, h2: 22 };

/** topInset: keep content clear of the status bar/notch when the screen has no app bar above it. */
export function Screen({ children, scroll = true, topInset = false }: {
  children: React.ReactNode; scroll?: boolean; topInset?: boolean;
}) {
  const insets = useSafeAreaInsets();
  const pad = topInset ? insets.top : 0;
  const inner = <View style={styles.screenInner}>{children}</View>;
  return scroll ? (
    <ScrollView style={[styles.screen, { paddingTop: pad }]} contentContainerStyle={{ paddingBottom: 48 + insets.bottom }}>
      {inner}
    </ScrollView>
  ) : (
    <View style={[styles.screen, { paddingTop: pad }]}>{inner}</View>
  );
}

/** Top bar for signed-in screens: respects the notch, has Back, Profile and Sign out. */
export function AppBar({ back = false }: { back?: boolean }) {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const user = useApp((s) => s.user);
  const link = (label: string, onPress: () => void) => (
    <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress} style={styles.barBtn}>
      <Text style={styles.barBtnText}>{label}</Text>
    </Pressable>
  );
  return (
    <View style={[styles.bar, { paddingTop: insets.top + 8 }]}>
      {back ? link('‹ Back', () => router.back()) : <Text style={styles.brand}>Smart Cane</Text>}
      <View style={{ flex: 1 }} />
      {user && link('Profile', () => router.push('/profile'))}
      {user && link('Sign out', async () => { await signOut(); router.replace('/sign-in'); })}
    </View>
  );
}

export function H1({ children }: { children: React.ReactNode }) {
  return <Text accessibilityRole="header" style={styles.h1}>{children}</Text>;
}
export function H2({ children }: { children: React.ReactNode }) {
  return <Text accessibilityRole="header" style={styles.h2}>{children}</Text>;
}
export function Body({ children, sub, style }: { children: React.ReactNode; sub?: boolean; style?: object }) {
  return <Text style={[styles.body, sub && { color: colors.sub }, style]}>{children}</Text>;
}

export function Card({ children, tone }: { children: React.ReactNode; tone?: 'warn' | 'danger' }) {
  return (
    <View
      style={[
        styles.card,
        tone === 'warn' && { borderColor: colors.warn, borderWidth: 2 },
        tone === 'danger' && { borderColor: colors.danger, borderWidth: 2 },
      ]}
    >
      {children}
    </View>
  );
}

export function Button({
  label, onPress, kind = 'primary', disabled, loading, hint,
}: {
  label: string; onPress: () => void; kind?: 'primary' | 'secondary' | 'danger';
  disabled?: boolean; loading?: boolean; hint?: string;
}) {
  const bg = kind === 'primary' ? colors.primary : kind === 'danger' ? colors.danger : colors.bg;
  const fg = kind === 'secondary' ? colors.primary : colors.onPrimary;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={hint}
      accessibilityState={{ disabled: !!disabled || !!loading }}
      disabled={disabled || loading}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        { backgroundColor: bg, borderColor: colors.primary, opacity: disabled ? 0.5 : pressed ? 0.8 : 1 },
      ]}
    >
      {loading ? <ActivityIndicator color={fg} /> : <Text style={[styles.buttonText, { color: fg }]}>{label}</Text>}
    </Pressable>
  );
}

export function Field(props: TextInputProps & { label: string }) {
  const { label, ...rest } = props;
  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={styles.body}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        placeholderTextColor={colors.sub}
        style={styles.input}
        {...rest}
      />
    </View>
  );
}

export function Badge({ text, color = colors.sim }: { text: string; color?: string }) {
  return (
    <View accessibilityLabel={text} style={[styles.badge, { borderColor: color }]}>
      <Text style={[styles.badgeText, { color }]}>{text}</Text>
    </View>
  );
}

/** Shown whenever the data is simulated (MASTER 19.2). */
export function SimulatedBadge({ show }: { show: boolean }) {
  return show ? <Badge text="SIMULATED DATA" /> : null;
}

export function Chip({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={label}
      onPress={onPress}
      style={[styles.chip, selected && { backgroundColor: colors.primary }]}
    >
      <Text style={[styles.body, selected && { color: colors.onPrimary }]}>{label}</Text>
    </Pressable>
  );
}

export function ErrorText({ children }: { children?: React.ReactNode }) {
  return children ? <Text accessibilityRole="alert" style={[styles.body, { color: colors.danger }]}>{children}</Text> : null;
}

export function Loading() {
  return <ActivityIndicator size="large" color={colors.primary} style={{ margin: 24 }} />;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  screenInner: { padding: 16, gap: 12 },
  bar: {
    flexDirection: 'row', alignItems: 'center', paddingHorizontal: 8, paddingBottom: 8,
    backgroundColor: colors.bg, borderBottomWidth: 1, borderBottomColor: colors.grey,
  },
  brand: { fontSize: type.h2, fontWeight: '700', color: colors.text, paddingHorizontal: 8 },
  barBtn: { minHeight: 48, minWidth: 48, paddingHorizontal: 10, justifyContent: 'center' },
  barBtnText: { fontSize: type.small, fontWeight: '700', color: colors.primary },
  h1: { fontSize: type.h1, fontWeight: '700', color: colors.text },
  h2: { fontSize: type.h2, fontWeight: '700', color: colors.text, marginTop: 8 },
  body: { fontSize: type.body, color: colors.text, lineHeight: 26 },
  card: { backgroundColor: colors.card, borderRadius: 12, padding: 16, gap: 8 },
  button: {
    minHeight: 48, minWidth: 48, borderRadius: 10, borderWidth: 2, paddingHorizontal: 16,
    alignItems: 'center', justifyContent: 'center',
  },
  buttonText: { fontSize: type.body, fontWeight: '700' },
  input: {
    minHeight: 48, borderWidth: 2, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12,
    fontSize: type.body, color: colors.text, marginTop: 4,
  },
  badge: { alignSelf: 'flex-start', borderWidth: 2, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 2 },
  badgeText: { fontSize: type.small, fontWeight: '800', letterSpacing: 0.5 },
  chip: {
    minHeight: 48, justifyContent: 'center', paddingHorizontal: 14, borderRadius: 24,
    borderWidth: 2, borderColor: colors.primary, marginRight: 8, marginBottom: 8,
  },
});
