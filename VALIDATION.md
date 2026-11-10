# Validation record

Validated in the isolated cloud workspace on 2026-11-09.

## Passed

- `python -m py_compile *.py`
- `python -m unittest discover -v`: **92 tests passed**.
- `python demo.py --output /tmp/autorecap-final --all`: five workflow integration renders passed with synthetic color/video/panel fixtures, imported scripts and real Flite narration.
- `python make_samples.py ...`: five original illustrated sample renders passed; actual output durations approximately 25–32 seconds, with video and narration audio.
- `ffprobe` confirms MP4 duration/size; first rendered movie frame visually inspected for layout.
- Job CLI help, empty worker and status smoke checks passed; queue claims/dedup/retry tested with unit fixtures.

## Not tested / not implemented

- No live Ollama model was available. The generation/vision adapters were **not** live-tested; a failure-path test proves no automatic remote fallback.
- Actual Tesseract OCR and heuristic four-panel segmentation pass on generated original fixtures. Whisper.cpp failure and output contracts are tested, but no local ASR model/executable is installed.
- No actual commercial movie, TV, anime or manhwa source was used. Samples are synthetic originals with imported hand-authored script plans, not source-understanding benchmarks.
- No representative 5–8 minute film recap, exact competitor editing match, retention quality or voice-quality assessment.
- No browser UI automation, mobile review test, real-world security audit, hosted deployment, source-rights verification, or publication.
- Optional Remotion source adapter and manifest export bridge implemented; 3 dependency-free Node tests pass and synthetic-run bundle export smoke-tested. TypeScript compilation/browser rendering not run. No HyperFrames/HeyGen runtime integration.

## Sample semantics

`make_samples.py` generates original illustrated storyboards/cards, narration scripts and source assets, then invokes the real pipeline. All five MP4s were produced by that pipeline. The phrase “movie workflow sample” describes the code route, not licensed film footage or full autonomous movie understanding.

A complete unattended multi-format production system still requires the work identified in ARCHITECTURE.md. This validation record must not be presented as that completion.

Final OCR integration: manhwa panel manifest → actual Tesseract OCR → imported plan → Flite → MP4/review completed successfully. All five final synthetic routes completed after specialized-worker and measured-QA integration.

Checkpoint integration: all five workflow renders completed with checkpoint tracking; an identical movie run with `--resume` reused verified artifacts successfully. Checkpoint unit coverage includes tamper, missing artifact, signature mismatch and concurrent lock refusal.

Final security regression suite: symlink/hardlink output source preservation, safe export filenames, disabled HTTP proxies/redirects, transcript checkpoint reuse/tamper rejection, QA-error blocking, export completion/source/project integrity all pass. Cloud-tagged Ollama model names are rejected; custom service/alias locality must still be verified by the operator.

## Mac OpenAI Whisper verification

Installed OpenAI Whisper 20250625 with cached base.en.pt transcribed an original 3.193-second Samantha-voice fixture on CPU in 2.802 seconds. Exact recognized sentence: “The little blue robot carries a lantern through the quiet garden.” Input/model hashes were unchanged. No installation, download, paid call, private source media or live-project mutation. The actual CLI command contract was tested on the Mac; the adapter module has six cloud unit tests, and the complete pipeline has not yet been run on the Mac. See `validation/mac_whisper_smoke.json`. The initial default-voice speech fixture was only 5ms and yielded empty SRT, correctly not counted as a pass.

## v0.3 validation (2026-11-10)

- 147 Python unit/integration tests passed; 3 Node manifest tests passed.
- All five workflows rendered MP4, SRT, EDL, acceptance reports and review artifacts in fresh integration runs.
- Actual local research ingestion -> hash-verified lesson manifest -> educational FFmpeg MP4 path completed on an original, hand-authored fixture. Its visual is a storyboard plumbing fixture, not a representative scientific explainer.
- Review decisions invalidate on artifact additions/removals/changes; linked metadata writes rejected.
- Persistent continuity ledger tests cover idempotence, immutable records, exact quotation provenance, episode limits, alias conflicts and linked-file protections.
- Temporal observation and bounded revision are contract-tested with deterministic fake model responses. No actual Ollama language/vision generation occurred because no local server/model was reachable. These tests do not establish semantic quality.
- Remotion has source and manifest tests only; no installed runtime/render validation. No HyperFrames/HeyGen/cloud service calls or publication.

The build remains an experimental local studio. Supplying authorized representative assets and a verified local model is required before producing and reviewing autonomous, channel-style samples. Synthetic clips are integration proof, not substitutes for those samples.
