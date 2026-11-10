// Deliberately dependency-free, shared by browser composition and render preflight.
const fail = (message) => { throw new Error(`Invalid manifest: ${message}`); };
const integer = (value, min, name) => {
  if (!Number.isSafeInteger(value) || value < min) fail(name);
};
export function assetPath(value) {
  // Relative ASCII paths inside public/, no URL, traversal, query, fragment or encoding.
  if (typeof value !== 'string' || !/^[a-zA-Z0-9_-][a-zA-Z0-9_./-]*$/.test(value) ||
      value.split('/').some((part) => !part || part === '.' || part === '..')) {
    fail('src must be a plain relative public/ asset path');
  }
  return value;
}
export function validateManifest(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail('object required');
  if (typeof value.title !== 'string' || value.title.length > 500) fail('title');
  integer(value.fps, 1, 'fps');
  if (value.fps > 120) fail('fps exceeds 120');
  for (const key of ['width', 'height']) {
    integer(value[key], 2, key);
    if (value[key] > 7680 || value[key] % 2) fail(`${key} must be even and at most 7680`);
  }
  if (!Array.isArray(value.clips) || !value.clips.length || value.clips.length > 10000) fail('clips');
  let end = 0;
  for (const clip of value.clips) {
    if (!clip || typeof clip !== 'object') fail('clip');
    integer(clip.startFrame, 0, 'startFrame');
    integer(clip.durationFrames, 1, 'durationFrames');
    integer(clip.sourceStartFrame, 0, 'sourceStartFrame');
    if (!['video', 'image'].includes(clip.kind)) fail('kind');
    assetPath(clip.src);
    if (clip.caption !== undefined && (typeof clip.caption !== 'string' || clip.caption.length > 2000)) fail('caption');
    if (clip.panZoom !== undefined) {
      if (clip.kind !== 'image' || !clip.panZoom || typeof clip.panZoom !== 'object') fail('panZoom is image-only');
      for (const key of ['fromScale', 'toScale']) {
        const n = clip.panZoom[key];
        if (typeof n !== 'number' || !Number.isFinite(n) || n < 1 || n > 3) fail(`panZoom.${key}`);
      }
      for (const key of ['fromX', 'toX', 'fromY', 'toY']) {
        const n = clip.panZoom[key];
        if (typeof n !== 'number' || !Number.isFinite(n) || n < -20 || n > 20) fail(`panZoom.${key}`);
      }
    }
    end = Math.max(end, clip.startFrame + clip.durationFrames);
  }
  if (!Number.isSafeInteger(end) || end > value.fps * 3600) fail('timeline exceeds one hour');
  if (!Array.isArray(value.audio) || value.audio.length > 1000) fail('audio');
  for (const track of value.audio) {
    if (!track || typeof track !== 'object') fail('audio track');
    integer(track.startFrame, 0, 'audio.startFrame');
    if (track.startFrame >= end) fail('audio must begin inside visual timeline');
    assetPath(track.src);
  }
  return value;
}
export const durationFrames = (manifest) => Math.max(...manifest.clips.map((c) => c.startFrame + c.durationFrames));
