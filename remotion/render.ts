import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';
import {readFile, realpath, stat, mkdtemp, rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {validateManifest} from './manifest.mjs';
import type {Manifest} from './src/types';

const root = path.dirname(fileURLToPath(import.meta.url));
const [input, output] = process.argv.slice(2);
if (!input || !output) throw new Error('Usage: npm run render -- manifest.json output.mp4');
// No automatic Chromium download: operator supplies an already installed browser.
const browserExecutable = process.env.REMOTION_BROWSER_EXECUTABLE;
if (!browserExecutable || !path.isAbsolute(browserExecutable)) throw new Error('Set REMOTION_BROWSER_EXECUTABLE to an existing absolute Chrome/Chromium path.');
if (!(await stat(browserExecutable)).isFile()) throw new Error('Browser is not a file');
const manifest = validateManifest(JSON.parse(await readFile(input, 'utf8'))) as Manifest;
const publicDir = await realpath(path.join(root, 'public'));
for (const asset of [...manifest.clips, ...manifest.audio]) {
  const resolved = await realpath(path.join(publicDir, asset.src));
  const relative = path.relative(publicDir, resolved);
  if (relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) throw new Error(`Asset escapes public/: ${asset.src}`);
  if (!(await stat(resolved)).isFile()) throw new Error(`Asset is not a file: ${asset.src}`);
  // SVG can reference external resources; only raster images are accepted here.
  const allowed = 'kind' in asset ? (asset.kind === 'image' ? ['.png', '.jpg', '.jpeg', '.webp'] : ['.mp4', '.webm', '.mov']) : ['.wav', '.mp3', '.m4a', '.aac', '.ogg'];
  if (!allowed.includes(path.extname(asset.src).toLowerCase())) throw new Error(`Unsupported asset extension: ${asset.src}`);
}
try { await stat(output); throw new Error('Output exists; choose a new filename.'); }
catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
const temporary = await mkdtemp(path.join(os.tmpdir(), 'recap-remotion-'));
try {
  const serveUrl = await bundle({entryPoint: path.join(root, 'src/index.tsx'), publicDir, outDir: path.join(temporary, 'bundle')});
  const inputProps = {manifest};
  const composition = await selectComposition({serveUrl, id: 'Recap', inputProps, browserExecutable});
  await renderMedia({serveUrl, composition, inputProps, codec: 'h264', outputLocation: path.resolve(output), browserExecutable});
  console.log(`Rendered ${output}`);
} finally { await rm(temporary, {recursive: true, force: true}); }
