import { build } from 'esbuild';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';

// The //@ metadata header must lead the shipped file: RisuAI parses plugin
// name/args from it. Keep the header block in src/index.ts as the source of
// truth (lines starting with "// //@"), and prepend it to the bundle here.
const src = readFileSync('src/index.ts', 'utf8');
const meta = src
  .split('\n')
  .filter((l) => l.startsWith('// //@'))
  .map((l) => l.replace(/^\/\/ /, ''))
  .join('\n');

mkdirSync('dist', { recursive: true });
await build({
  entryPoints: ['src/index.ts'],
  bundle: true,
  format: 'iife',
  target: 'es2020',
  outfile: 'dist/plugin.body.js',
  legalComments: 'none',
});
const body = readFileSync('dist/plugin.body.js', 'utf8');
writeFileSync('dist/plugin.js', meta + '\n' + body);
console.log('dist/plugin.js written:', (meta + '\n' + body).length, 'bytes');
