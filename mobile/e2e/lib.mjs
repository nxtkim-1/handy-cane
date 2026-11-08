// Shared helpers for the browser tests. Drives the REAL app (Expo web build) in the installed Chrome
// against the REAL API. Needs: API on :8000 (docker compose up -d api + seed), the web build served on :8082
// (npm run e2e:build && npm run e2e:serve), and optionally the cane simulator on :8765.
import { chromium } from 'playwright-core';
import fs from 'node:fs';

export const APP = process.env.APP_URL || 'http://localhost:8082';
export const API = process.env.API_URL || 'http://localhost:8000';
export const SHOTS = process.env.SHOT_DIR || 'e2e/shots';
fs.mkdirSync(SHOTS, { recursive: true });

export async function launch() {
  const browser = await chromium.launch({ channel: process.env.CHROME_CHANNEL || 'chrome', headless: true });
  const ctx = await browser.newContext({ viewport: { width: 400, height: 860 } });
  const page = await ctx.newPage();
  const problems = [];
  page.on('pageerror', (e) => problems.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') problems.push('console: ' + m.text()); });
  page.on('requestfailed', (r) => problems.push('requestfailed: ' + r.url() + ' ' + (r.failure()?.errorText || '')));
  page.on('response', (r) => { if (r.status() >= 400 && r.url().startsWith(API)) problems.push(`http ${r.status()}: ${r.request().method()} ${r.url()}`); });
  return { browser, page, problems };
}

export async function shot(page, name) {
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

export async function signIn(page, email, password = 'demo-password-1') {
  await page.goto(APP);
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
}

let failures = 0;
export function check(name, ok, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : '  ' + detail}`);
  if (!ok) failures++;
}
export function done(problems = []) {
  const real = problems.filter((p) => !/favicon|DevTools/.test(p));
  if (real.length) console.log('\nBrowser problems seen:\n  ' + [...new Set(real)].join('\n  '));
  console.log(failures ? `\n${failures} check(s) FAILED` : '\nall checks passed');
  process.exit(failures ? 1 : 0);
}
