"""Shared path/integrity checks for private Hard reporting helpers. No model calls."""
import hashlib
import json
from pathlib import Path
import re

OPS = Path(__file__).resolve().parent
REPO = OPS.parent.parent
ARMS = ('rules', 'glimmer', 'spark', 'wonder', 'glimmer_to_spark', 'glimmer_to_wonder')
PROJECT = 'servedoctor-hard15-20261102'
RENTAL_PROJECT = 'servedoctor-hard-20261102'
LABEL = 'ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)'
IDS = tuple(f'hard-{i:02d}' for i in range(1, 16))
FROZEN_IDS = tuple(f'hard-{i:02d}' for i in range(1, 17))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def regular(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected a regular evidence file')
    return path


def load(path):
    return json.loads(regular(path).read_text())


def hard_ids(root):
    cases = [s['id'] for s in load(Path(root) / 'scenarios.json')['scenarios'] if s['split'] == 'hard']
    if sorted(cases) != list(FROZEN_IDS):
        raise ValueError('Original sixteen public Hard scenario IDs must remain unchanged')
    return IDS


def approved_root(value, repo=REPO):
    repo = Path(repo).resolve()
    path = Path(value)
    if not path.is_absolute():
        path = repo / path
    relative = path.relative_to(repo).as_posix()
    if relative != 'runs/sd-hard-partial-attempt1':
        raise ValueError('Use the Hard study or an explicitly reasoned fresh attempt')
    if path.is_symlink() or path.resolve() != path:
        raise ValueError('Study path cannot traverse symlinks')
    return path


def evaluation_gate(root, repo=REPO):
    # The trusted integrity verifier hashes opaque answer/runtime bytes; no labels
    # or model payloads are returned by this wrapper.
    import hard_partial_integrity
    root, repo = Path(root), Path(repo)
    marker = load(root / 'hard-partial-validation-dispatch.json')
    folder = Path(marker['dispatch']['path']).parent.resolve()
    if not folder.is_relative_to((repo / 'runs/servedoctor-hard15-ops-20261102').resolve()):
        raise ValueError('Validation evidence must belong to the Hard operations directory')
    proof = hard_partial_integrity.verify_evaluation(root, folder, repo)
    if (proof.get('evaluation_ready') is not True or proof.get('total') != 15
            or proof.get('label') != LABEL or proof.get('project') != PROJECT):
        raise ValueError('Complete labelled fifteen-case validation proof required')
    return proof


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
