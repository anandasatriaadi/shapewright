"""shapewright - an MCP server that makes parametric 3D design easy for agents.

    python -m shapewright            # runs the stdio MCP server

The server keeps a small stateful scene of named solids and exposes high-level
build123d operations plus rendering, printability and export.
"""

from .scene import Scene, SceneError

__all__ = ["Scene", "SceneError"]
__version__ = "0.1.0"
