import { build, context } from 'esbuild';
import { mkdir, copyFile } from 'node:fs/promises';
await mkdir('dist', { recursive: true });
await copyFile('frontend/index.html', 'dist/index.html');
const options = { entryPoints: ['frontend/main.tsx'], bundle: true, outdir: 'dist/assets', minify: true, sourcemap: true, define: { 'process.env.NODE_ENV': '"production"' }, loader: { '.woff2': 'file' } };
if (process.argv.includes('--watch')) { const ctx = await context(options); await ctx.watch(); console.log('Watching frontend. Run the Python server separately.'); }
else await build(options);
