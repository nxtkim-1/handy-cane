import { QueryClient } from '@tanstack/react-query';

/** Shared so non-React code (sync, sign-out) can refresh or clear screen data. */
export const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1 } } });
