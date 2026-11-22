import { defineConfig } from 'vitest/config';

// Tests contra servicios reales. Necesitan OMNIWEBHOOK_PG_URL apuntando a un PostgreSQL de prueba.
export default defineConfig({
  test: {
    include: ['test/integration/**/*.test.ts'],
    fileParallelism: false,
  },
});
