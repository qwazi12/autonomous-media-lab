import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateManifest, durationFrames, assetPath} from './manifest.mjs';
const sample = () => JSON.parse(readFileSync(new URL('./sample-manifest.json', import.meta.url), 'utf8'));
test('sample validates and yields 90 frames', () => assert.equal(durationFrames(validateManifest(sample())), 90));
test('rejects remote URLs and traversal', () => {
  for (const path of ['https://example.com/a.mp4', '../a.png', 'a/../b.png', '/tmp/a.png', 'a%2fb.png', 'a\\b.png', 'a//b.png', 'a.png?q=1']) assert.throws(() => assetPath(path));
});
test('rejects invalid timeline, dimensions, and audio', () => {
  for (const mutate of [m => m.clips[0].durationFrames = 0, m => m.width = 1279, m => m.fps = 0, m => m.audio = [{startFrame:90,src:'voice.wav'}], m => m.clips[0].panZoom.toScale = NaN]) {
    const m = sample(); mutate(m); assert.throws(() => validateManifest(m));
  }
});
