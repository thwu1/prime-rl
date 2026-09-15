import * as esbuild from 'esbuild';

await esbuild.build({
  entryPoints: ['./src/index.ts'],
  bundle: true,
  format: 'esm',
  outfile: './dist/index.mjs',
  target: 'es2022',
  platform: 'neutral',
});
