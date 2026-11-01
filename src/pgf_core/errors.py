"""Exception hierarchy used across PaperGalFlow."""

from __future__ import annotations


class PgfError(Exception):
    """Base class for every error raised by PaperGalFlow itself."""


class GraphError(PgfError, ValueError):
    """A flow graph is internally inconsistent and cannot be rendered."""


class AdapterError(PgfError):
    """An engine adapter could not complete a requested operation."""


class PipelineError(PgfError):
    """The degradation chain ran out of usable sources."""
