"""Utilities for deterministic file hashing."""

import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    """
    Compute SHA-256 hash of a file.
    """

    digest = hashlib.sha256()

    with path.open("rb") as f:
        while chunk := f.read(8192):
            digest.update(chunk)

    return digest.hexdigest()