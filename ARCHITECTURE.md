# Production architecture and implementation boundary

## Orchestrator versus creative workers

The deterministic orchestrator owns state and outputs, not creative truth. Jobs are immutable specifications; processing creates per-attempt artifacts and an audit log. A creative worker cannot publish, retry external writes or grant itself rights. Stage outputs are reviewable JSON. Media conversion runs without network protocols and outputs never overwrite sources.

## Current workers

| Stage | Implemented behavior | Evidence/limitation |
|---|---|---|
| Ingest | Local file check, source hash, rights declaration | No license verification |
| Video index | FFmpeg cuts, bounded intervals, thumbnails, SRT evidence | Midpoint still is not temporal understanding |
| Panel/card index | Ordered supplied images and evidence | Optional actual Tesseract + white-gutter heuristic; unverified layout order |
| Vision | Loopback Ollama JSON descriptions | Adapter implemented; live model untested |
| Analyst | Batches of 12 evidence scenes, constrained references | Local model inference; not grounded-proof guarantee |
| Writer | Workflow-specific original script, cited scene IDs | Imported plan mode separately labeled |
| Critic | Separate model call over evidence and draft | Same model may repeat errors; human review needed |
| Speech | Flite draft WAV or supplied WAV | No cloning, paid TTS or word alignment |
| Director | Cited ranges → audio-duration-based shot timeline | No advanced visual-intent retrieval yet |
| Renderer | FFmpeg MP4, SRT and CSV | Fully exercised on synthetic inputs |
| QA | Bounds/schema/audio checks, freeze warnings, black/silence/peak/duration scans | Semantic and rights checks remain review tasks |
| Review | Escaped offline HTML with evidence, warnings and video | Does not certify review completion |
| Queue | SQLite lease, dedup, audit, explicit retry | Hash-verified stage resume; no resume inside a model call; no remote worker deployment |

## Specialized brains: production target

1. **Movie:** temporal event graph, character identity ledger, causal outline, flashback handling, source-evidence entailment and visual retrieval. Current version implements evidence batching and prompt specialization, not the full graph.
2. **TV:** movie path plus episode/season continuity, prior-event ledger and spoiler boundary. Current worker filters episode-tagged evidence and records supplied continuity; persistent semantic continuity is not yet implemented.
3. **Anime:** video path plus alias/pronunciation dictionary, transformations, internal monologues and ambiguous identity. Current worker annotates supplied aliases without altering original evidence and records pronunciation context; identity inference remains model-dependent.
4. **Manhwa:** reading-order verification, panel/OCR/speaker graph, dialogue/narration separation and keyframed pan/zoom. Current version supports supplied panels or heuristic white-gutter segmentation plus actual Tesseract OCR and static holds. Speaker attribution and confident reading order remain unverified.
5. **Education:** objectives, research provenance, claim ledger, equations/numeric checks and designed diagrams. Current version builds a sourced claim ledger from the supplied cards and flags novel numeric assertions; original diagram fixture demonstrates rendering, not automatic research.

## Next provider contracts

Implement providers behind a capability contract: `analyze_frames`, `transcribe`, `write_json`, `synthesize_speech`, `render`. Record model/version, asset hashes, requested budget and actual measured cost. Do not silently fall back from local to paid cloud. Remote credential configuration and source upload require appropriate authorization. TTS must finish before timeline duration is locked.

A renderer adapter should consume an immutable frame-based manifest with source ranges, layers, keyframes, caption intervals and audio tracks. It must never call a model. FFmpeg stays the fallback; Remotion or HyperFrames can supply educational diagrams, overlays and motion templates. HeyGen avatar generation is optional presenter media, not the system's editorial brain.

## Required before unattended production

- Real authorized content corpus across all formats, measured factual/shot errors and reviewed acceptance criteria.
- Live-validation of the whisper.cpp transcription adapter, and temporal multi-frame understanding with character/continuity state.
- Semantic verification against source, not only self-critique; uncertainty thresholds block release.
- Forced alignment, loudness/clipping and black/silent-frame checks; editable captions and exact word timing.
- Production hardening of artifact hashing/stage resume and bounded retries, cost ceilings, cancellation, isolation and security review.
- Rights ledger beyond operator declaration, per-asset provenance and separate publication authorization.
- Real provider integration tests, renderer-adapter tests, review application usability tests and representative 5–8 minute recaps.

This first prototype is an inspectable base for those steps, not a completion claim for them.
