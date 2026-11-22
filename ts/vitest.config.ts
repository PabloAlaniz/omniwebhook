import { defineConfig } from 'vitest/config';

// El núcleo (dominio y casos de uso) no baja del 90 %: es donde viven las reglas.
const nucleo = { statements: 90, branches: 90, functions: 90, lines: 90 };

export default defineConfig({
  test: {
    include: ['test/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.ts'],
      reporter: ['text-summary', 'lcov'],
      thresholds: {
        'src/domain/**': nucleo,
        'src/application/**': nucleo,
      },
    },
  },
});
