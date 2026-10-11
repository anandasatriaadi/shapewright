"""
What an agent session looks like.

This drives the server exactly the way an LLM would - by calling MCP tools
with JSON arguments - rather than importing the Scene directly.

    python examples/tool_session.py
"""

from __future__ import annotations

import asyncio

from shapewright.server import mcp


async def call(name: str, args: dict):
    res = await mcp.call_tool(name, args)
    content = res.content if hasattr(res, "content") else res
    for item in content:
        kind = getattr(item, "type", "?")
        if kind == "text":
            print(f"  {name} -> {item.text.strip()[:200]}")
        else:
            print(f"  {name} -> [{kind}]")


async def main() -> None:
    print("designing a small mounting bracket…\n")
    await call("create_box", {"name": "plate", "length": 60, "width": 40,
                              "height": 8, "corner": 4})
    await call("create_cylinder", {"name": "bore", "radius": 5.5, "height": 30})
    await call("subtract", {"name": "plate", "tools": ["bore"]})
    await call("create_cylinder", {"name": "hole_a", "radius": 3.2, "height": 30,
                                   "at": [-22, 0, 0]})
    await call("create_cylinder", {"name": "hole_b", "radius": 3.2, "height": 30,
                                   "at": [22, 0, 0]})
    await call("subtract", {"name": "plate", "tools": ["hole_a", "hole_b"]})
    await call("create_box", {"name": "rib", "length": 40, "width": 4, "height": 20,
                              "at": [0, 0, 12]})
    await call("union", {"name": "plate", "parts": ["plate", "rib"]})
    await call("fillet_edges", {"name": "plate", "radius": 2,
                                "select": "parallel:Y & at:zmax"})
    await call("place_on_bed", {"name": "plate"})
    await call("printability", {"name": "plate", "bed": [220, 220, 250]})
    await call("render_views", {"names": ["plate"], "views": ["iso", "front", "top"]})
    await call("export_part", {"name": "plate", "format": "step"})
    await call("export_script", {})
    print("\ndone - see ./shapewright_out")


if __name__ == "__main__":
    asyncio.run(main())
