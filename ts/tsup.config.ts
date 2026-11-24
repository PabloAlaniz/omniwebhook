import { defineConfig } from 'tsup';

export default defineConfig({
  entry: {
    index: 'src/index.ts',
    standard: 'src/standard.ts',
    node: 'src/node.ts',
    testing: 'src/testing.ts',
    otel: 'src/otel.ts',
    bin: 'src/bin.ts',
  },
  format: ['esm', 'cjs'],
  dts: true,
  clean: true,
  external: ['standardwebhooks', '@opentelemetry/api'],
});
