"""Local-only OCR, heuristic panel segmentation, and whisper.cpp ASR workers.

These adapters never install software, download models, or use remote fallbacks.
Extracted source text is evidence, not executable instructions.
"""
from __future__ import annotations

import csv
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps


def _run(command: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Local worker timed out after {timeout}s: {Path(command[0]).name}") from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to run local worker {Path(command[0]).name}: {exc}") from exc
    if result.returncode:
        raise RuntimeError(f"Local worker {Path(command[0]).name} failed ({result.returncode}): {result.stderr.strip()[-2000:]}")
    return result


def ocr_image(path: Path, language: str = "eng") -> dict:
    """Run installed Tesseract; return word evidence in image pixel coordinates.

    confidence is Tesseract's uncalibrated 0–100 score, not a probability.
    Text order follows Tesseract output and is not a verified reading order.
    """
    path = Path(path).resolve(strict=True)
    executable = shutil.which("tesseract")
    if not executable:
        raise RuntimeError("Tesseract is not installed. Install it separately to enable local OCR.")
    if not language or not all(c.isalnum() or c in "_+-" for c in language) or language.startswith("-"):
        raise ValueError("Invalid Tesseract language identifier")
    with Image.open(path) as image:
        width, height = image.size
    result = _run([executable, str(path), "stdout", "-l", language, "tsv"])
    words = []
    lines = {}
    for row in csv.DictReader(io.StringIO(result.stdout), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (row.get("text") or "").strip()
        if row.get("level") != "5" or not text:
            continue
        try:
            left, top, w, h = [int(row[k]) for k in ("left", "top", "width", "height")]
            confidence = float(row["conf"])
            if not (0 <= confidence <= 100) or min(left, top, w, h) < 0:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        key = tuple(row.get(k, "") for k in ("page_num", "block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append(text)
        words.append({"id": f"word-{len(words)+1:04d}", "text": text,
                      "bbox": [left, top, left + w, top + h], "confidence": confidence,
                      "line_id": ":".join(key), "uncertain": confidence < 70})
    warnings = ["OCR may misread stylized text. Reading order is not verified; manually compare evidence with the source image."]
    if not words:
        warnings.append("No words detected. This is not evidence that the image contains no text.")
    if any(word["uncertain"] for word in words):
        warnings.append("Low-confidence words require review (Tesseract confidence below 70).")
    return {"source": str(path), "engine": "tesseract", "language": language,
            "width": width, "height": height, "bbox_format": "xyxy_pixels",
            "confidence_scale": "uncalibrated 0-100", "words": words,
            "text": "\n".join(" ".join(line) for line in lines.values()), "warnings": warnings}


def _bands(values: list[bool], minimum: int) -> list[tuple[int, int]]:
    result = []
    start = None
    for i, blank in enumerate(values + [False]):
        if blank and start is None:
            start = i
        elif not blank and start is not None:
            if i - start >= minimum:
                result.append((start, i))
            start = None
    return result


def _split_bounds(blank: list[bool], min_gutter: int, min_panel: int) -> list[tuple[int, int]]:
    length = len(blank)
    splits = []
    previous = 0
    for start, end in _bands(blank, min_gutter):
        # Ignore margins; split only substantial regions on both sides.
        middle = (start + end) // 2
        if start >= min_panel and length - end >= min_panel and middle - previous >= min_panel:
            splits.append(middle)
            previous = middle
    edges = [0] + splits + [length]
    return list(zip(edges, edges[1:]))


def segment_page(path: Path, output_dir: Path, direction: str = "ltr") -> dict:
    """Split near-white horizontal gutters, then vertical gutters within each row.

    This intentionally simple heuristic assumes rectangular white-gutter layouts.
    It can split speech bubbles or miss irregular panels. Coordinates and output
    order are proposals only. Input orientation follows EXIF display orientation.
    """
    if direction not in {"ltr", "rtl"}:
        raise ValueError("direction must explicitly be 'ltr' or 'rtl'")
    path = Path(path).resolve(strict=True)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    width, height = image.size
    gray = image.convert("L")
    # Analyze a bounded thumbnail, preserving original coordinates for crops.
    gray.thumbnail((1000, 1000))
    w, h = gray.size
    pixels = gray.load()
    rows = [sum(pixels[x, y] >= 245 for x in range(w)) / w >= .995 for y in range(h)]
    row_bounds = _split_bounds(rows, max(3, h // 150), max(12, h // 15))
    panels = []
    for y0, y1 in row_bounds:
        columns = [sum(pixels[x, y] >= 245 for y in range(y0, y1)) / (y1-y0) >= .995 for x in range(w)]
        bounds = _split_bounds(columns, max(3, w // 150), max(12, w // 15))
        if direction == "rtl":
            bounds.reverse()
        for x0, x1 in bounds:
            box = [round(x0 * width / w), round(y0 * height / h), round(x1 * width / w), round(y1 * height / h)]
            panel_id = f"panel-{len(panels)+1:04d}"
            target = output_dir / f"{panel_id}.png"
            image.crop(box).save(target)
            panels.append({"id": panel_id, "order": len(panels)+1, "bbox": box,
                           "image": str(target), "uncertain": True,
                           "review_notes": ["Heuristic panel boundary and reading order are unverified."]})
    warnings = ["White-gutter heuristic only; panel boundaries and reading order are not verified.",
                "Assumes top-to-bottom rows, then " + ("left-to-right" if direction == "ltr" else "right-to-left") + " panels. Irregular, overlapping, borderless, or non-white panels need manual review."]
    if len(panels) == 1:
        warnings.append("No reliable interior gutter split found; the entire page is retained as one candidate panel.")
    return {"source": str(path), "direction": direction, "method": "white_gutter_heuristic",
            "bbox_format": "xyxy_pixels_exif_oriented", "width": width, "height": height,
            "reading_order_verified": False, "panels": panels, "warnings": warnings}


def transcribe_video(path: Path, out: Path, model_path: Path) -> Path:
    """Transcribe via installed whisper.cpp CLI and a caller-supplied local model.

    out is the desired SRT filename ('.srt' is appended if absent). Audio is
    extracted with installed ffmpeg to a temporary 16-kHz mono WAV. No model
    download or remote ASR fallback is attempted. Returns the written SRT path.
    """
    path = Path(path).resolve(strict=True)
    model_path = Path(model_path).expanduser()
    if not model_path.is_file():
        raise FileNotFoundError("A local whisper.cpp model file is required; models are never downloaded automatically.")
    model_path = model_path.resolve()
    executable = shutil.which("whisper-cli") or shutil.which("whisper-cpp")
    if not executable:
        raise RuntimeError("Local whisper.cpp CLI is unavailable (expected whisper-cli or whisper-cpp). No remote fallback or installation was attempted.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Local ffmpeg is required to extract audio; no installation was attempted.")
    out = Path(out)
    if out.suffix.lower() != ".srt":
        out = Path(str(out) + ".srt")
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite existing transcript: {out}")
    with tempfile.TemporaryDirectory(prefix="recap-asr-") as temporary:
        wav = Path(temporary) / "audio.wav"
        prefix = Path(temporary) / "transcript"
        _run([ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-i", str(path), "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)], timeout=600)
        _run([executable, "-m", str(model_path), "-f", str(wav), "-osrt", "-of", str(prefix)], timeout=3600)
        generated = prefix.with_suffix(".srt")
        if not generated.is_file() or not generated.read_text(encoding="utf-8").strip():
            raise RuntimeError("Local whisper.cpp produced no nonempty SRT transcript. Review the source audio and local model compatibility.")
        # Exclusive creation prevents a late-arriving file being overwritten.
        with out.open("x", encoding="utf-8") as destination:
            destination.write(generated.read_text(encoding="utf-8"))
    return out
