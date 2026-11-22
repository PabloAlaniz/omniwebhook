import { defineConfig } from 'tsup';

export default defineConfig({
  entry: {
    index: 'src/index.ts',
    standard: 'src/standard.ts',
  },
  format: ['esm', 'cjs'],
  dts: true,
  clean: true,
  external: ['standardwebhooks'],
});
