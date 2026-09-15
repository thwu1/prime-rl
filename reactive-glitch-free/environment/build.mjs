import * as esbuild from 'esbuild';

await esbuild.build({
  entryPoints: ['./src/reactive.ts'],
  bundle: true,
  format: 'cjs',
  outfile: './dist/index.cjs',
  target: 'es2015',
  platform: 'browser',
});
