import { launch, shot, signIn, check, done } from './lib.mjs';

const { browser, page, problems } = await launch();
try {
  await page.goto(process.env.APP_URL || 'http://localhost:8082');
  await page.getByLabel('Email').waitFor({ timeout: 20000 });
  check('sign-in screen renders', true);
  await shot(page, '01-signin');
  await signIn(page, 'live@demo.example');
  await page.waitForTimeout(4000);
  await shot(page, '02-after-signin');
  const text = await page.locator('body').innerText();
  check('signed in (no longer on sign-in)', !(await page.getByRole('button', { name: 'Sign in' }).isVisible().catch(() => false)), text.slice(0, 200));
} finally {
  await browser.close();
  done(problems);
}
