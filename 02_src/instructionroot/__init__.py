"""P028 InstructionRoot Resolve — package root.

T002 owns ``paths.py`` and ``snapshot.py`` in this package.
Other modules (``profiles/*``, ``resolver.py``, ``git.py``, ``trust.py``,
``imports.py``, ``receipt.py``) belong to later tasks and are not imported
here, so this package has no dependency on them.
"""

from instructionroot.paths import (
    CanonicalPath,
    canonicalize,
    detect_escape,
    is_within_root,
    lexical_canonical,
    redact_home,
)
from instructionroot.snapshot import (
    FilesystemSnapshot,
    PathEntry,
    SnapshotError,
    build_snapshot,
)

__all__ = [
    "CanonicalPath",
    "FilesystemSnapshot",
    "PathEntry",
    "SnapshotError",
    "build_snapshot",
    "canonicalize",
    "detect_escape",
    "is_within_root",
    "lexical_canonical",
    "redact_home",
]

__version__ = "0.1.0-t002"
