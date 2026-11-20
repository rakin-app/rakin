import { MutationCache, QueryClient } from '@tanstack/react-query'
import { ApiError } from './client'
import { isTermsGate } from './terms'

const MAX_RETRIES = 2

export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // A 4xx will not fix itself on retry; network errors and 5xx might.
        retry: (failureCount, error) =>
          !(error instanceof ApiError && error.status < 500) && failureCount < MAX_RETRIES,
      },
    },
    mutationCache: new MutationCache({
      // A write the gym's terms hold back (#499), which the admin's gate normally keeps
      // anyone from reaching: who is signed in is read again, and the gate shows.
      onError: (error) => {
        if (isTermsGate(error)) void client.invalidateQueries({ queryKey: ['me', 'role'] })
      },
    }),
  })
  return client
}
