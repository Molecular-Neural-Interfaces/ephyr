# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Content fingerprint of a recording that does not depend on where it lies on disk."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, Tuple

from ephyr.core.manifests import FileFingerprint, Fingerprint

SPARSE_ALGORITHM = "sha256-sparse-v1"
_BLOCK_SIZE = 1024 * 1024


def sparse_file_hash(path: Path) -> str:
    """SHA-256 of the size plus the first, middle and last MiB; small files are hashed whole."""
    size = path.stat().st_size
    digest = hashlib.sha256(str(size).encode("ascii"))
    with open(path, "rb") as file:
        if size <= 3 * _BLOCK_SIZE:
            digest.update(file.read())
        else:
            for offset in (0, size // 2 - _BLOCK_SIZE // 2, size - _BLOCK_SIZE):
                file.seek(offset)
                digest.update(file.read(_BLOCK_SIZE))
    return digest.hexdigest()


def combined_digest(files: Iterable[FileFingerprint]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda entry: (entry.relpath, entry.size, entry.sha256_sparse)):
        digest.update(f"{item.relpath}\0{item.size}\0{item.sha256_sparse}\n".encode("utf-8"))
    return digest.hexdigest()


def compute_fingerprint(files: Iterable[Tuple[str, Path]]) -> Fingerprint:
    """Fingerprint from (relpath inside the canonical root, absolute path) pairs."""
    entries = [
        FileFingerprint(relpath=relpath, size=path.stat().st_size, sha256_sparse=sparse_file_hash(path))
        for relpath, path in files
    ]
    entries.sort(key=lambda entry: entry.relpath)
    return Fingerprint(algorithm=SPARSE_ALGORITHM, digest=combined_digest(entries), files=entries)


def fingerprint_of_ref(ref) -> Fingerprint:
    """Fingerprint of every file a SourceRef reads."""
    return compute_fingerprint((ref.relpath(path), Path(path)) for path in ref.files)


def matches(fingerprint: Fingerprint, other: Fingerprint) -> bool:
    return fingerprint.algorithm == other.algorithm and fingerprint.digest == other.digest
