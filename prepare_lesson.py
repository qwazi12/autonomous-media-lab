#!/usr/bin/env python3
"""Turn offline research evidence and operator-authored cards into a lesson manifest.

Usage: python prepare_lesson.py corpus.json cards.json --output lesson.json
Cards input: {"cards": [{"image": "diagram.png", "description": "Operator's
visual description", "evidence_ids": ["ev-..."]}]}. Image paths resolve relative
to cards.json. Sources are rehashed from their original absolute local paths.
No fetching, generation, or factual certification occurs. Run pipeline.py with
--workflow educational --source lesson.json and its normal rights/review gates.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image
from research import verify_corpus

MAX_IMAGE_BYTES = 50 * 1024 * 1024


def prepare_lesson(corpus: dict, cards: list[dict], *, image_base: str | Path) -> dict:
    """Verify source integrity, resolve references, and build pipeline cards.

    All original research files must still exist and match their recorded hashes.
    One source per card is mandatory because the pipeline assigns one URL/date
    to each card. Split multi-source cards explicitly rather than merging labels.
    `as_of` uses publication date if supplied, otherwise access date; the basis
    remains explicit in provenance and neither means the claim is currently true.
    Image hashes bind this preparation snapshot; downstream edits require rerun.
    """
    evidence = verify_corpus(corpus, recheck_files=True)
    if not isinstance(cards, list) or not 1 <= len(cards) <= 1000:
        raise ValueError('Supply 1–1000 operator-authored cards')
    sources = {source['id']: source for source in corpus['sources']}
    base = Path(image_base).resolve(strict=True)
    if not base.is_dir():
        raise ValueError('image_base must be a directory')
    result = []
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            raise ValueError(f'Card {index + 1} must be an object')
        image, description, ids = card.get('image'), card.get('description'), card.get('evidence_ids')
        if not isinstance(image, str) or not image.strip():
            raise ValueError(f'Card {index + 1} requires a local image path')
        if '://' in image or image.startswith('data:'):
            raise ValueError('Images must be supplied local files, never URLs')
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f'Card {index + 1} requires an operator-authored description')
        if not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids):
            raise ValueError(f'Card {index + 1} requires nonempty evidence_ids')
        if len(set(ids)) != len(ids):
            raise ValueError(f'Card {index + 1} repeats an evidence ID')
        if any(item not in evidence for item in ids):
            raise ValueError(f'Card {index + 1} contains an unknown evidence ID')
        quotes = [evidence[item] for item in ids]
        source_ids = {item['source_id'] for item in quotes}
        if len(source_ids) != 1:
            raise ValueError(f'Card {index + 1} cites multiple sources; split it into separate cards explicitly')
        source = sources[next(iter(source_ids))]
        path = (base / image).resolve(strict=True)
        if not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError('Image must be a regular file no larger than 50 MiB')
        raw = path.read_bytes()
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError('Image grew beyond 50 MiB')
        # Decode from the same bytes that are hashed, not a second read.
        with Image.open(io.BytesIO(raw)) as picture:
            if picture.format not in {'PNG', 'JPEG', 'WEBP'}:
                raise ValueError('Use a PNG, JPEG, or WebP image')
            width, height = picture.size
            if width * height > 40_000_000:
                raise ValueError('Image exceeds 40 megapixels')
            if getattr(picture, 'n_frames', 1) != 1:
                raise ValueError('Use a still image, not an animated image')
            picture.verify()
        date_field = 'published_on' if source['published_on'] else 'accessed_on'
        result.append({'image': str(path), 'description': description,
                       'evidence': [item['text'] for item in quotes],
                       'source_url': source['url'], 'as_of': source[date_field],
                       'evidence_ids': list(ids), 'image_sha256': hashlib.sha256(raw).hexdigest(),
                       'image_dimensions': [width, height],
                       'provenance': {'source_id': source['id'], 'source_title': source['title'],
                                      'content_sha256': source['content_sha256'],
                                      'extracted_sha256': source['extracted_sha256'],
                                      'published_on': source['published_on'],
                                      'accessed_on': source['accessed_on'], 'as_of_basis': date_field,
                                      'quotes': [{'id': item['id'], 'locator': item['locator'],
                                                  'start': item['start'], 'end': item['end']} for item in quotes]}})
    return {'schema_version': 1, 'workflow': 'educational', 'cards': result,
            'research_corpus_sha256': hashlib.sha256(json.dumps(corpus, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest(),
            'warnings': ['Source files matched their recorded hashes during preparation; this does not authenticate publishers or verify truth.',
                         'Descriptions and image content are operator supplied and not automatically grounded or fact checked.',
                         'as_of is the supplied publication date, or supplied access date when publication date is unknown; it is not a freshness guarantee.',
                         'Review quotes in original context and verify source quality, dates, visual accuracy, and usage rights.',
                         'Research IDs and hashes remain in this manifest; the current pipeline assigns its own scene evidence IDs.',
                         'Rerun preparation after changing research files or images.']}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('corpus', type=Path)
    parser.add_argument('cards', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text(encoding='utf-8'))
    authored = json.loads(args.cards.read_text(encoding='utf-8'))
    if not isinstance(authored, dict):
        raise ValueError('Cards input must be an object containing cards')
    manifest = prepare_lesson(corpus, authored.get('cards'), image_base=args.cards.resolve().parent)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(args.output.resolve())


if __name__ == '__main__':
    main()
