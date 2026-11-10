"""Content-verified, local checkpoints; never persist raw specs or credentials.

Use ``with checkpoints.lock():`` around a complete resumed pipeline to exclude
other cooperating workers. Mutations also acquire this lock on their own. Locks
are never stolen: after a crash, verify the former worker has stopped before
manually removing ``.checkpoint.lock``. This is a local-filesystem mechanism, not
a distributed lock or protection against hostile filesystem changes.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time


class CheckpointError(ValueError):
    pass


def _digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def signature(spec: dict, inputs: list[Path]) -> str:
    """Hash canonical spec and ordered local input identities/content.

    Only the resulting digest belongs in a checkpoint, never the spec itself.
    Changing an input's bytes at the same path changes this signature. Input
    order and absolute paths are significant, as are all spec values.
    """
    if not isinstance(spec, dict):
        raise CheckpointError('Signature spec must be an object')
    try:
        encoded = json.dumps(spec, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False)
        identities = []
        for item in inputs:
            path = Path(item).resolve(strict=True)
            if not path.is_file():
                raise CheckpointError('Signature input must be a regular local file')
            identities.append({'path': str(path), 'sha256': _digest(path)})
        payload = json.dumps({'spec': encoded, 'inputs': identities}, sort_keys=True,
                             separators=(',', ':'), ensure_ascii=False)
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, CheckpointError):
            raise
        # Avoid embedding a raw spec/secret in errors.
        raise CheckpointError('Cannot hash checkpoint spec or input files') from exc


class Checkpoints:
    def __init__(self, root, signature, resume=False):
        if not isinstance(signature, str) or not signature:
            raise CheckpointError('A nonempty checkpoint signature is required')
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'checkpoint.json'
        self.lock_path = self.root / '.checkpoint.lock'
        self.signature = signature
        self._owner = None
        self._depth = 0
        self._context = None
        with self.lock():
            if resume:
                self._load()
            elif self.path.exists() or self.path.is_symlink():
                raise CheckpointError('Checkpoint already exists; use resume with the same inputs/spec')
            else:
                self._write({'schema_version': 1, 'signature': self.signature, 'stages': {}})

    @contextmanager
    def lock(self):
        """Exclusive local lock, nestable only by this instance's owning thread."""
        owner = threading.get_ident()
        if self._owner == owner:
            self._depth += 1
            try:
                yield self
            finally:
                self._depth -= 1
            return
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise CheckpointError('Checkpoint is locked; locks are never automatically stolen') from exc
        self._owner = owner
        self._depth = 1
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump({'pid': os.getpid(), 'created': time.time()}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            yield self
        finally:
            self._depth = 0
            self._owner = None
            self.lock_path.unlink()

    def __enter__(self):
        # Save the outer context on a stack to allow nested `with checkpoints`.
        context = self.lock()
        context.__enter__()
        if self._context is None:
            self._context = []
        self._context.append(context)
        return self

    def __exit__(self, *exc):
        return self._context.pop().__exit__(*exc)

    def _load(self):
        if self.path.is_symlink():
            raise CheckpointError('Checkpoint manifest cannot be a symlink')
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise CheckpointError('Checkpoint is missing or unreadable') from exc
        if (not isinstance(data, dict) or data.get('schema_version') != 1
                or not isinstance(data.get('stages'), dict)):
            raise CheckpointError('Unsupported or invalid checkpoint manifest')
        if data.get('signature') != self.signature:
            raise CheckpointError('Checkpoint signature differs; inputs/spec must match exactly')
        return data

    def _write(self, data):
        if self.path.is_symlink():
            raise CheckpointError('Checkpoint manifest cannot be a symlink')
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.root,
                                             prefix='.checkpoint-', suffix='.tmp', delete=False) as stream:
                temp_path = Path(stream.name)
                json.dump(data, stream, sort_keys=True, indent=2, allow_nan=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    @staticmethod
    def _stage(stage):
        if not isinstance(stage, str) or not stage.strip() or len(stage) > 128:
            raise CheckpointError('Stage must be a nonempty name up to 128 characters')

    def _artifact(self, value):
        path = Path(value)
        path = (self.root / path).resolve(strict=True)
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise CheckpointError('Checkpoint artifacts must remain inside the output root') from exc
        if not path.is_file():
            raise CheckpointError('Checkpoint artifacts must be regular files')
        if path in (self.path, self.lock_path) or path.name.startswith('.checkpoint-'):
            raise CheckpointError('Checkpoint metadata cannot be an artifact')
        return path, relative.as_posix()

    def valid(self, stage) -> bool:
        self._stage(stage)
        with self.lock():
            data = self._load()
            saved = data['stages'].get(stage)
            if not isinstance(saved, dict) or not saved:
                return False
            try:
                for relative, expected in saved.items():
                    if not isinstance(relative, str) or Path(relative).is_absolute():
                        return False
                    path, normalized = self._artifact(relative)
                    if normalized != relative or not isinstance(expected, str) or _digest(path) != expected:
                        return False
            except (OSError, ValueError, TypeError):
                return False
            return True

    def record(self, stage, paths):
        self._stage(stage)
        with self.lock():
            data = self._load()
            files = {}
            try:
                for item in paths:
                    path, relative = self._artifact(item)
                    files[relative] = _digest(path)
            except (OSError, TypeError) as exc:
                raise CheckpointError('Cannot read checkpoint artifact') from exc
            if not files:
                raise CheckpointError('A stage must have at least one artifact')
            data['stages'][stage] = files
            self._write(data)

    def invalidate(self, stage):
        self._stage(stage)
        with self.lock():
            data = self._load()
            if stage in data['stages']:
                del data['stages'][stage]
                self._write(data)
