import { defineConfig } from 'vitest/config';

// Tests contra servicios reales. Necesitan OMNIWEBHOOK_PG_URL y OMNIWEBHOOK_REDIS_URL
// apuntando a un PostgreSQL y a un Redis de prueba.
export default defineConfig({
  test: {
    include: ['test/integration/**/*.test.ts'],
    fileParallelism: false,
  },
});
