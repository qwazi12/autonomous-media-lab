# Optional local Remotion adapter

Status: source implementation only. **No packages have been installed, no browser has been downloaded, and no Remotion render or TypeScript check has run.** Dependency-free manifest tests can run using Node alone. The explicit dependency versions are an **untested compatible baseline**, not verified current versions. All Remotion packages deliberately use the same version. No model, paid API, upload, or hosted rendering is used.

## Installation boundary

Installation is a separate operator-approved step: `npm install` contacts the npm registry, downloads dependencies, and may execute package lifecycle scripts. Do not run it under the current no-install/no-network task authorization. Review dependency versions, applicable Remotion license, and installation policy first. No lockfile exists because dependency resolution has not occurred. After approval, install in this directory, retain the generated lockfile, and use `npm ci` for reproducible subsequent installations.

The render entry requires an existing compatible Chrome/Chromium installation. It deliberately supplies `browserExecutable` instead of requesting Remotion's automatic browser download. Browser installation, if needed, is a separate approval boundary. Rendering bundles files and serves them locally; it is not a promise of network isolation for the browser or third-party packages. Use host network isolation if strict offline enforcement is required.

## Usage after installation approval

1. Place trusted media under `public/`. Source strings are relative to that folder, e.g. `shots/scene.mp4`, not absolute paths or URLs. Do not put unrelated private files in `public/`: the bundler serves/copies this directory.
2. `npm test` runs dependency-free validation tests; `npm run check` type-checks after dependencies are installed.
3. Set `REMOTION_BROWSER_EXECUTABLE` to an existing absolute browser executable path.
4. `npm run render -- sample-manifest.json sample-output.mp4`

The sample uses a generated local PNG, lasts three seconds, and has no narration. Rendering refuses to overwrite an existing output. Do not run concurrently targeting the same output filename. Keep assets unchanged during rendering.

## Manifest contract

See `sample-manifest.json`, `src/types.ts`, and runtime checks in `manifest.mjs`. Root fields: title, fps (integer 1–120), even width/height (2–7680), nonempty clips, audio array. Timeline is capped at one hour. All times are integer **composition frames**, including video `sourceStartFrame`; the renderer converts source offsets using the composition frame rate. Images require sourceStartFrame but ignore its value.

Clips contain startFrame, durationFrames, src, sourceStartFrame, kind (`video` or `image`), optional plain-text caption, and optional image-only panZoom. PanZoom requires fromScale/toScale (1–3), fromX/toX/fromY/toY (-20–20, translation percentages). Pans may expose the background; increase scale if needed. Video clips are muted intentionally, so explicit audio tracks control the mix. Captions are React text, never injected HTML. Long captions may need editorial shortening for legibility.

Visual duration is the maximum clip end. Gaps are black; overlapping clips paint in array order (later clips above earlier ones), without crossfades. Audio starts at startFrame, plays from its beginning, and ends at its natural end or the visual timeline end. Multiple tracks mix at full volume; normalization, ducking, and loudness QA belong upstream. title is metadata, not an automatic title card.

Render preflight rejects missing assets, symlinks escaping public/, URL-like paths, traversal, SVG, and unsupported extensions. Allowed image extensions: PNG/JPEG/WebP; video: MP4/WebM/MOV; audio: WAV/MP3/M4A/AAC/OGG. Extension checks do not validate codecs or media duration. Trusted inputs are required. Run the parent pipeline's media QA before rendering; short source videos, unsupported codecs, browser compatibility, font substitution, final visuals, and audio sync remain runtime verification work. Timeline and animation parameters are deterministic; byte-identical video output across machines is not promised.

## Verification recorded

- Dependency-free tests: **3 passed** locally with `node --test test-manifest.mjs` (Node 24.22.1).
- TypeScript compilation: **not run**, dependencies absent.
- Remotion bundle, browser render, visual review, and output audio/video QA: **not run**, dependencies absent.

This adapter is standalone. It does not replace or automatically hook into the parent Python renderer. Call it explicitly with the manifest contract above.
