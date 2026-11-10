# Autonomous Media Lab · experimental local prototype

An isolated production core for movie, TV, anime, manhwa and educational drafts. It does not connect to live channels, queues or publishing APIs.

**This is a runnable first-stage prototype, not a finished autonomous studio or a claim of channel-quality output.** The deterministic media path is tested end to end. Autonomous semantic analysis uses a local Ollama vision/language model, which was not installed in the build environment and therefore has not been live-validated. Generated scripts require factual and visual review.

## What runs today

- Local movie/episode input: FFmpeg shot/cut detection, midpoint thumbnails and timed subtitle evidence.
- Local ordered panel/card manifests: image preparation and a renderable source timeline.
- Optional local vision descriptions and hierarchical evidence analysis → original script → independent critique, using Ollama on loopback only. No paid API or remote fallback.
- Imported-script mode for repeatable fixtures, edited plans or externally reviewed scripts.
- Offline Flite draft speech or imported per-segment WAV recordings. Actual audio duration determines edit timing.
- Evidence-linked shot assembly, MP4 export, proportional SRT captions, edit-decision CSV, structural QA and offline review screen.
- Durable SQLite job queue: deduplication, atomic leased claims, heartbeat, audit records, explicit retry with a fresh output directory.
- Publishing disabled. Rights confirmation required, but it is an operator declaration, **not a legal determination or automated clearance**.

## Requirements

Python 3.10+, FFmpeg and ffprobe on PATH. Offline draft speech requires an FFmpeg build with `flite`. Sample artwork generation additionally needs Pillow. The base video pipeline and review use Python standard library only. OCR/page-preparation workers need Pillow and installed Tesseract; ASR needs an installed whisper.cpp executable and an existing local model file.

For AI generation, separately install/start Ollama and a suitable local text model. For frame descriptions, select a vision-capable local model. Choose models based on hardware and evaluate their actual results. The tool never downloads models or creates credentials automatically. Cloud-tagged Ollama model names are rejected. You must verify the selected model and Ollama service are truly local: an arbitrary custom alias/proxy can conceal remote inference, which this prototype cannot independently audit. Loopback transport alone is not a billing guarantee.

## Quick start: reproducible end-to-end test

```sh
python demo.py --output demo --all
python -m unittest discover -v
```

This makes **five synthetic integration MP4s with hand-authored narration fixtures**. It is not an autonomous-story quality test. Open `demo/movie/review.html` (or the other workflow directories). Each run includes `draft.mp4`, `draft.srt`, `draft_edit_decisions.csv`, `index.json`, `plan.json`, `project.json`, `qa.json` and `run.json`.

For more illustrative original storyboard fixtures:

```sh
python make_samples.py samples
```

Those sample scripts and drawings are original test content. Movie/TV/anime samples use illustrated storyboard videos, not footage from an actual film or show. Manhwa uses ordered original illustrated cards, not a chapter from a copyrighted series. The education sample is a simple original shadow diagram. Flite is a robotic draft voice, not a cloned or production narrator.

## Actual movie workflow

```sh
python pipeline.py --workflow movie --source /path/authorized-film.mp4 \
  --subtitles /path/film.srt --output runs/movie-001 \
  --vision-model YOUR_LOCAL_VISION_MODEL --model YOUR_LOCAL_TEXT_MODEL \
  --target-seconds 360 --rights-confirmed
```

The target is a writing goal, not a guarantee: final length is measured from generated audio. Inspect `qa.json` for freeze padding and `review.html` for evidence/criticism. No subtitle input means no dialogue evidence: use `--asr-model /path/to/existing-whisper-model.bin` to invoke local whisper.cpp if installed. This adapter was contract-tested only because no executable/model is available in the build environment. Without a vision model, it does not understand silent visual action. Do not describe either path as full-film understanding.

To use an edited or reviewed plan instead of a model:

```sh
python pipeline.py --source authorized-film.mp4 --plan reviewed-plan.json \
  --output runs/reviewed-001 --rights-confirmed
```

To use higher-quality recordings, pass `--audio-dir narration/` containing one WAV per segment ID, e.g. `B001.wav`. No TTS paid service is invoked.

## Specialized workflow input contracts

### Movie, TV and anime

Use `--workflow movie`, `tv` or `anime` with local video and optional SRT. These share the same implemented cut/evidence/render path. Separate deterministic workers specialize these paths: TV filters evidence tagged to other episodes; anime annotates source-name aliases without rewriting evidence; movie checks source-order regressions. Their model instructions specialize causal plot, episode boundaries or alias/vision ambiguity respectively. **They are not yet fully distinct semantic engines**: persistent season continuity, automated alias tracking, ASR and multi-frame temporal reasoning remain future work.

### Manhwa

`--source chapter.json --workflow manhwa`. The JSON has a `panels` array in verified reading order:

```json
{"panels":[{"image":"panel-1.png","description":"Visible action only","evidence":["Verified dialogue or observation"]}]}
```

Image paths are relative to the manifest. This version consumes prepared panels, or `prepare_pages.py` proposes panels with a white-gutter heuristic and runs local Tesseract OCR. Add `--ocr` to OCR a supplied panel manifest. Segmentation and OCR were tested on original fixtures; irregular page layouts, speaker attribution and production pan/zoom composition still require review/work. It never scrapes third-party chapters.

### Educational

`--source lesson.json --workflow educational`. The JSON has a `cards` array:

```json
{"cards":[{"image":"diagram.png","description":"Diagram explanation","evidence":["A source-supported claim"],"source_url":"https://example.org/actual-source","as_of":"2026-11-09"}]}
```

The educational worker builds a source/date claim ledger and flags numeric assertions absent from the cited evidence. The operator supplies sources and visual assets. URLs are provenance labels and are not fetched or verified. Automated research, equation verification, generative diagrams, presenters and citation fact-checking are not implemented. A local model can turn the supplied evidence into a script with critique, but criticism is not proof.

## Plan contract

```json
{"title":"Original title","segments":[{"id":"B001","narration":"Original grounded narration.","scene_ids":["S00001"],"review_notes":["Check character identity"]}]}
```

All cited scenes must exist. IDs are restricted to safe filename characters. Evidence references are structural links, not automatic proof that the narration is true. Imported plans are explicitly labeled `imported_plan` in run artifacts.

## Durable jobs

```sh
python jobs.py --db jobs.sqlite --output-root runs enqueue job.json
python jobs.py --db jobs.sqlite --output-root runs work --once
python jobs.py --db jobs.sqlite --output-root runs status
python jobs.py --db jobs.sqlite --output-root runs retry JOB_ID
```

Example spec:

```json
{"source":"film.mp4","workflow":"movie","subtitles":"film.srt","model":"YOUR_LOCAL_TEXT_MODEL","vision_model":"YOUR_LOCAL_VISION_MODEL","target_seconds":360,"rights_confirmed":true}
```

Paths resolve relative to the spec file. Identical canonical specifications deduplicate; content changes at the same input path are not automatically distinguished by the queue, although the pipeline records hashes. Use a new input filename/spec for a new source revision. Expired jobs fail rather than being silently replayed. Before retry, inspect any prior process; each retry writes a new attempt directory. The pipeline can reuse hash-verified completed stages with `--resume` and identical input/spec hashes. It does not resume within an individual model/renderer call. The queue retry path deliberately uses a new attempt directory; use the CLI resume explicitly to reuse a prior run.

## Rendering choices and expansion

FFmpeg is the proven baseline for clip/panel assembly and audio export. Remotion is a strong next adapter for reusable typed diagram, caption and educational templates. HeyGen **HyperFrames** (HTML/CSS/GSAP rendering) is distinct from HeyGen's hosted avatar API and is a candidate for HTML-authored motion graphics. The optional `remotion/` adapter and `export_remotion.py` bridge are now implemented as source, with dependency-free manifest tests; Remotion is not installed and its actual render/typecheck are unverified. HyperFrames is considered but not implemented. Hosted avatar/TTS/model providers need separate account, permission, budget and quality testing before use.

We intentionally avoid an agent that can freely publish, retry uploads, spend money or alter production systems. See `ARCHITECTURE.md` for worker contracts and gates.

## Review and safety limits

- No scraper, DRM bypass, automatic downloading, publishing, paid calls, or production credentials.
- Only local Ollama networking is supported; source text/images are untrusted data.
- Original source audio is not reused; narration is synthesized/imported separately.
- Captions are proportionally timed, not word-aligned.
- Visual source clips are used in cited scene order; unsupported or short footage is flagged and may freeze-pad. This is not polished cinematic editorial judgment.
- No automatic monetization or copyright clearance claims.
- Generated outputs are drafts; verify characters, sequence, speech, source rights, factual claims and visuals.
- No live source integrations were changed. Existing recap-workbench renderer was copied and reused; the original project remains unchanged.

## Format context and page preparation

`--context context.json` accepts format-specific context: TV `episode`, `prior_continuity`, `spoiler_boundary`; anime `aliases` and `pronunciations`; manhwa `reading_direction`, `order_confirmed`, `chapter`; education `audience`, `learning_objectives`. Context is evidence supplied by the operator, not automatically verified. Pronunciations are recorded for writing/review, not automatically applied to Flite.

```sh
python prepare_pages.py page1.png page2.png --output prepared-chapter --direction ltr --rights-confirmed
python pipeline.py --workflow manhwa --source prepared-chapter/panels.json --model YOUR_LOCAL_TEXT_MODEL --vision-model YOUR_LOCAL_VISION_MODEL --output runs/chapter-001 --rights-confirmed
```

Check `prepared-chapter/segmentation.json` and the panel images before treating reading order as correct. Local output is exclusive; use a fresh directory. Media QA now measures black/silent intervals, peak level, stream existence and duration. These are review signals, not semantic or legal clearance.

## Verified-stage resume

Rerun the identical pipeline command with `--resume`. Source, subtitle, context, plan, model-file and panel/image content hashes must match. Completed index/plan/audio/render stages are reused only if their output hashes still match. Tampering or missing artifacts invalidates that stage and dependent stages. Concurrent use is blocked by an exclusive checkpoint lock; stale locks are never automatically stolen. Inspect a crashed process before manually clearing its lock. Changing the model name or input bytes requires a new run. Model weights behind the same Ollama tag are not independently fingerprinted, so use immutable model versions for reproducibility.

## Optional Remotion bundle export

```sh
python export_remotion.py --run runs/movie-001 --source authorized-film.mp4 --output remotion-bundle
```

This creates `manifest.json` and a `public/` directory with copied source media and narration. Keep that bundle local/private. Read `remotion/README.md` before copying assets into the adapter and installing dependencies. The bridge was smoke-tested with a completed synthetic run; rendering itself has not run because dependencies/browser packages are not installed. Full-paragraph captions in the bridge are a draft layout and need editorial shortening.

## OpenAI Whisper CLI on a machine with cached models

The `openai-whisper` engine supports the installed Python Whisper CLI as an alternative to whisper.cpp. It requires an explicit existing `.pt` file, uses CPU inference with FP16 disabled and four threads, and never accepts a model name that could trigger an automatic download.

```sh
python pipeline.py --workflow movie --source authorized-film.mp4 --asr-engine openai-whisper --asr-model /path/to/existing/base.en.pt --model YOUR_LOCAL_TEXT_MODEL --vision-model YOUR_LOCAL_VISION_MODEL --output runs/movie-asr --rights-confirmed
```

The wrapper extracts a restricted local WAV first, writes SRT exclusively, and preserves input files. Six unit tests cover missing executables/weights, no fallback, overwrite refusal, invocation and validation. Local ASR only supplies dialogue evidence; it does not replace visual understanding or story verification.

Verified on the connected Apple M4 Mac: installed OpenAI Whisper 20250625 and cached base.en.pt transcribed an original 3.19-second speech fixture correctly in 2.80 seconds on CPU. No download/install was needed. This verifies the CLI invocation; full pipeline-on-Mac and long-film accuracy/performance remain untested. For macOS test fixtures, explicitly selecting the installed Samantha voice worked; the default voice returned a nearly empty audio file despite exit 0.
