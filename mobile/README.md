# Smart Cane mobile app (Expo, TypeScript)

```
npm install --legacy-peer-deps
npx expo start        # Demo mode is on by default: no backend, simulated cane
npm test              # jest: sync, upload queue, chart logic
npm run typecheck     # tsc --noEmit
```

Demo accounts (mock mode): `patient@demo` or `clinician@demo`, password `demo`.
Live mode: set `EXPO_PUBLIC_API_URL` and `EXPO_PUBLIC_CANE_URL`, or turn off
Demo mode on the sign-in screen. Cane wire format: `PROTOCOL.md`.

Layout: `src/comm` (transports), `src/db` (SQLite + in-memory store),
`src/sync` (pull loop, upload worker), `src/api` (ApiClient + mock),
`src/charts` (pure no-data-is-not-zero logic), `app/` (Expo Router screens).
