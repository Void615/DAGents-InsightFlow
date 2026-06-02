"""Runtime node execution has moved to app.core.runtime.

This module intentionally contains no node closures. Business nodes are now
declared through NodeSpec in app.core.competitive_template and executed by
NodeRunner + ControlGate.
"""

from app.core.runtime.node_runner import NodeRunner, sanitize_for_json

__all__ = ["NodeRunner", "sanitize_for_json"]
