import { defineConfig } from 'vitest/config';

// Ninguna capa baja del 90 %. Lo que queda afuera se prueba contra el servicio de verdad.
const minimo = { statements: 90, branches: 90, functions: 90, lines: 90 };

export default defineConfig({
  test: {
    include: ['test/**/*.test.ts'],
    exclude: ['test/integration/**'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.ts'],
      // Lo de PostgreSQL se prueba contra una base real en test:integration.
      exclude: ['src/adapters/stores/postgres.ts', 'src/adapters/ledger/postgres.ts'],
      reporter: ['text-summary', 'lcov'],
      thresholds: {
        'src/domain/**': minimo,
        'src/application/**': minimo,
        'src/adapters/**': minimo,
        'src/entrypoints/**': minimo,
      },
    },
  },
});
