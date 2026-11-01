"""pgf-core -- the engine independent heart of PaperGalFlow.

The core knows about story graphs, node states, layout and the orchestration
of degradation chains.  It deliberately knows nothing about Ren'Py (or any
other engine): rendering, script parsing and file patching are adapter jobs.

Public entry points are re-exported here so adapters only need to import
:mod:`pgf_core`.
"""

from __future__ import annotations

from .errors import AdapterError, GraphError, PgfError, PipelineError
from .layout import Layout, LayoutConfig, Point, Rect, RoutedEdge, compute_layout
from .model import EdgeKind, FlowEdge, FlowGraph, FlowNode, NodeKind
from .state import NodeState, ProgressState, RuntimeStateKernel, runtime_kernel_source
from .version import __version__

__all__ = [
    "__version__",
    "AdapterError",
    "GraphError",
    "PgfError",
    "PipelineError",
    "EdgeKind",
    "FlowEdge",
    "FlowGraph",
    "FlowNode",
    "NodeKind",
    "NodeState",
    "ProgressState",
    "RuntimeStateKernel",
    "runtime_kernel_source",
    "Layout",
    "LayoutConfig",
    "Point",
    "Rect",
    "RoutedEdge",
    "compute_layout",
]
