"""Offline research ingestion and conservative extractive claim grounding.

No fetches, model calls, installs, or external side effects. Source content is
untrusted evidence, never instructions. A grounded quote is not a verified fact.
Run: python research.py ingest sources.json corpus.json
     python research.py validate corpus.json claims.json report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

MAX_BYTES = 10 * 1024 * 1024


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _date(value: str, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    date.fromisoformat(value)
    return value


def _url(value: str) -> str:
    if not isinstance(value, str) or any(c.isspace() for c in value):
        raise ValueError("provenance URL must be an HTTP(S) URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("provenance URL must be HTTP(S), with a host and no credentials")
    return value


class _HTMLText(HTMLParser):
    """Ignore non-content elements; never resolve links or execute scripts."""
    excluded = {"script", "style", "template", "noscript", "head"}
    blocks = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.excluded:
            self.hidden.append(tag)
        elif not self.hidden and tag in self.blocks:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if not self.hidden and tag in self.blocks:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.hidden:
            self.hidden = self.hidden[:self.hidden.index(tag)]
        elif not self.hidden and tag in self.blocks:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _normalize(text: str) -> str:
    return "\n".join(line for line in (re.sub(r"\s+", " ", x).strip() for x in text.splitlines()) if line)


def _sentences(text: str):
    # Intentionally heuristic: abbreviations may split. Offsets refer to the
    # normalized extraction, never raw HTML bytes or PDF coordinates.
    for match in re.finditer(r'[^\n]+', text):
        for sentence in re.finditer(r'.+?(?:[.!?](?=\s|$)|$)', match.group()):
            raw = sentence.group()
            if raw.strip():
                start = match.start() + sentence.start() + len(raw) - len(raw.lstrip())
                end = match.start() + sentence.end() - (len(raw) - len(raw.rstrip()))
                yield start, end, text[start:end]


def _evidence(source: dict) -> list[dict]:
    result = []
    for unit in source['units']:
        for start, end, text in _sentences(unit['text']):
            basis = [source['id'], unit['locator'], start, end, text]
            result.append({'id': 'ev-' + _hash(_canonical(basis)), 'source_id': source['id'],
                           'locator': unit['locator'], 'start': start, 'end': end, 'text': text})
    return result


def ingest_source(path: str | Path, *, url: str, accessed_on: str,
                  title: str = '', published_on: str | None = None) -> dict:
    """Read an explicitly supplied UTF-8 .txt/.md/.html/.htm/.json file.

    JSON document extracts: {"text": "..."} or
    {"pages": [{"page": 1, "text": "..."}, ...]}. PDF/DOCX extraction is
    deliberately upstream. Provenance URL/dates are caller assertions, not fetched.
    """
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('Source must be a regular file no larger than 10 MiB')
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError('Source grew beyond 10 MiB')
    text = raw.decode('utf-8-sig', errors='strict')
    extension = path.suffix.lower()
    units = []
    if extension in {'.html', '.htm'}:
        parser = _HTMLText()
        parser.feed(text)
        parser.close()
        units = [{'locator': 'document', 'text': _normalize(''.join(parser.parts))}]
    elif extension in {'.txt', '.md'}:
        units = [{'locator': 'document', 'text': _normalize(text)}]
    elif extension == '.json':
        document = json.loads(text)
        if not isinstance(document, dict):
            raise ValueError('Document extract must be an object')
        if 'pages' in document:
            pages = document['pages']
            if not isinstance(pages, list) or not pages:
                raise ValueError('pages must be a nonempty list')
            seen = set()
            for page in pages:
                if not isinstance(page, dict) or type(page.get('page')) is not int or page['page'] < 1 or not isinstance(page.get('text'), str):
                    raise ValueError('Each page needs a positive integer page and string text')
                if page['page'] in seen:
                    raise ValueError('Duplicate page number')
                seen.add(page['page'])
                units.append({'locator': f"page:{page['page']}", 'text': _normalize(page['text'])})
        elif isinstance(document.get('text'), str):
            units = [{'locator': 'document', 'text': _normalize(document['text'])}]
        else:
            raise ValueError('Document extract requires text or pages')
    else:
        raise ValueError('Supported input extensions: .html .htm .txt .md .json')
    if not any(unit['text'] for unit in units):
        raise ValueError('No usable source text extracted')
    if not isinstance(title, str):
        raise ValueError('title must be a string')
    source = {'url': _url(url), 'accessed_on': _date(accessed_on, 'accessed_on'),
              'published_on': _date(published_on, 'published_on') if published_on is not None else None,
              'title': title, 'local_path': str(path), 'content_sha256': _hash(raw),
              'extracted_sha256': _hash(_canonical(units)), 'units': units}
    source['id'] = 'source-' + _hash(_canonical(source))
    source['evidence'] = _evidence(source)
    return source


def ingest_sources(specs: list[dict]) -> dict:
    if not isinstance(specs, list) or not specs:
        raise ValueError('Provide a nonempty array of explicit source specifications')
    sources = [ingest_source(**spec) for spec in specs]
    if len({source['id'] for source in sources}) != len(sources):
        raise ValueError('Duplicate source specification')
    return {'schema_version': 1, 'sources': sources,
            'limitations': ['Provenance metadata is supplied, not independently verified.',
                           'Sentence segmentation is heuristic; inspect original context.',
                           'Extractive support does not establish truth, currency, or source reliability.',
                           'HTML extraction does not implement browser visibility or remove every navigation element.']}


def verify_corpus(corpus: dict, *, recheck_files: bool = False) -> dict[str, dict]:
    """Check internal consistency; optional original-byte check detects local edits.

    Hashes are integrity checks, not signatures or proof of publisher authenticity.
    """
    if corpus.get('schema_version') != 1 or not isinstance(corpus.get('sources'), list) or not corpus['sources']:
        raise ValueError('Unsupported or empty corpus')
    evidence = {}
    source_ids = set()
    for source in corpus['sources']:
        base = {k: v for k, v in source.items() if k not in {'id', 'evidence'}}
        if source['id'] != 'source-' + _hash(_canonical(base)) or source['id'] in source_ids:
            raise ValueError('Source identity mismatch or duplicate')
        source_ids.add(source['id'])
        if source['extracted_sha256'] != _hash(_canonical(source['units'])) or source['evidence'] != _evidence(source):
            raise ValueError('Source evidence integrity mismatch')
        if recheck_files and _hash(Path(source['local_path']).read_bytes()) != source['content_sha256']:
            raise ValueError('Original local source content changed')
        for item in source['evidence']:
            evidence[item['id']] = {**item, 'url': source['url'], 'accessed_on': source['accessed_on'], 'published_on': source['published_on']}
    return evidence


def validate_claims(corpus: dict, claims: list[dict], *, recheck_files: bool = False) -> dict:
    """Only exact whole-sentence quotes pass automatically.

    Claims: [{"id": "card-1", "text": "Exact sentence.", "evidence_ids": [...]}].
    Unsupported paraphrases need human review, even when citations exist. This
    intentionally avoids misleading lexical-overlap or model-based truth scores.
    """
    evidence = verify_corpus(corpus, recheck_files=recheck_files)
    if not isinstance(claims, list) or not claims:
        raise ValueError('claims must be a nonempty list')
    results, seen = [], set()
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get('id'), str) or not claim['id'] or claim['id'] in seen:
            raise ValueError('Claims need unique nonempty string IDs')
        seen.add(claim['id'])
        text, ids = claim.get('text'), claim.get('evidence_ids')
        if not isinstance(text, str) or not text.strip() or not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
            raise ValueError('Claims require nonempty text and a string evidence_ids list')
        missing = [key for key in ids if key not in evidence]
        citations = [evidence[key] for key in dict.fromkeys(ids) if key in evidence]
        if not ids:
            status = 'missing_evidence'
        elif missing:
            status = 'unknown_evidence'
        elif len(ids) != len(set(ids)):
            status = 'duplicate_evidence'
        elif _normalize(text) == _normalize(' '.join(item['text'] for item in citations)):
            status = 'extractive_supported'
        else:
            status = 'needs_review'
        results.append({'id': claim['id'], 'status': status, 'missing_ids': missing, 'citations': citations})
    return {'ok': all(item['status'] == 'extractive_supported' for item in results),
            'scope': 'Exact cited text support only; not independent factual verification.', 'claims': results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    ingest = sub.add_parser('ingest')
    ingest.add_argument('specifications', type=Path)
    ingest.add_argument('output', type=Path)
    validate = sub.add_parser('validate')
    validate.add_argument('corpus', type=Path)
    validate.add_argument('claims', type=Path)
    validate.add_argument('output', type=Path)
    validate.add_argument('--recheck-files', action='store_true')
    args = parser.parse_args()
    if args.command == 'ingest':
        specs = json.loads(args.specifications.read_text(encoding='utf-8'))
        # Resolve relative paths next to the explicit source list, not arbitrary CWD.
        if not isinstance(specs, list):
            raise ValueError('Source specifications must be a list')
        specs = [{**spec, 'path': str(args.specifications.resolve().parent / spec['path'])} for spec in specs]
        result = ingest_sources(specs)
    else:
        result = validate_claims(json.loads(args.corpus.read_text(encoding='utf-8')),
                                 json.loads(args.claims.read_text(encoding='utf-8')), recheck_files=args.recheck_files)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    if args.command == 'validate' and not result['ok']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
