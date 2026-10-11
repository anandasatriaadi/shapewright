# shapewright

**An [MCP](https://modelcontextprotocol.io) server that makes parametric 3D design
easy for AI agents.** It wraps [build123d](https://build123d.readthedocs.io) in a set of
high-level, stateful tools an agent can actually use to design parts for 3D printing.

Raw build123d is hard for agents: the API is huge, edge/face selection is fiddly,
there's no picture of what you built, and nothing tells you whether a part is
printable. `shapewright` fixes each of those.

## What it gives an agent

| Pain point | shapewright's answer |
|------------|----------------------|
| Huge API surface | ~45 focused tools (`create_box`, `fillet_edges`, `shell`, `pattern_polar`, …) |
| Juggling geometry objects | a **stateful scene** of named solids — you just name things |
| `ShapeList` gymnastics | a **selector string** language: `parallel:Z & at:zmax`, `type:circle & radius>2`, `concave`, `normal:Z+`, `near:(0,0,10)` |
| "Is it right?" | `render_views` returns a **PNG** you can look at |
| "Will it print?" | `printability` → overhang area, support needed, bed fit, grams of filament |
| "I need to edit it later" | `export_script` → a **runnable build123d `.py`**; `export_part` → STL/STEP |
| Mistakes | `undo` |

Everything is in millimetres. Primitives are centred on the origin; call
`place_on_bed` when you want a part sitting on the print bed.

## Requirements

* Python **3.12+**
* [uv](https://docs.astral.sh/uv/) (recommended) or pip

build123d pulls in OpenCASCADE, so the first install is a chunky download.

## Install & run

```bash
git clone https://github.com/<you>/shapewright.git
cd shapewright
uv sync                       # creates .venv with shapewright-mcp + build123d
.venv/bin/shapewright-mcp     # starts the stdio MCP server
```

Prefer a global command? `uv tool install .` puts `shapewright-mcp` on your `PATH`.

## Wire it into an MCP client

Any stdio MCP client works — point it at the `shapewright-mcp` executable.

**opencode** (`opencode.jsonc`) — note servers live under `mcp.servers` in V2:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "shapewright": {
        "type": "local",
        "command": ["/path/to/shapewright/.venv/bin/shapewright-mcp"]
      }
    }
  }
}
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "shapewright": { "command": "/path/to/shapewright/.venv/bin/shapewright-mcp" }
  }
}
```

Use an **absolute** path to the executable — relative commands can fail to spawn
depending on the client's working directory.

Outputs (STL / STEP / render PNG / generated script) are written to
`./shapewright_out`; override with the `SHAPEWRIGHT_OUT` environment variable.

## Tool map

```
SCENE     reset · undo · list_objects · object_info · duplicate_object · delete_object

PRIMITIVES (mm, centred on origin; place with at / rotation)
  create_box(name, length, width, height, corner=?)
  create_cylinder(name, radius, height, corner=?)
  create_cone(name, bottom_radius, top_radius, height)
  create_sphere(name, radius) · create_torus(name, major_radius, minor_radius)
  create_prism(name, sides, radius, height, twist=?, fillet=?)   # hex handle… or twisted

PROFILES → SOLIDS
  profile_rect / profile_circle / profile_polygon (plane='XY'|'XZ'|'YZ')
  curve_polyline · curve_helix
  extrude(name, profile, amount, both, taper) · revolve(name, profile, axis, angle)
  loft(name, [profiles…]) · sweep(name, profile, path)

BOOLEANS  union(name, [parts]) · subtract(name, [tools]) · intersect(name, a, b)

MODIFY
  fillet_edges(name, radius, select) · chamfer_edges(name, length, select)
  shell(name, thickness, open_faces) · transform(name, translate, rotate, scale)
  mirror_object · split_object · pattern_linear · pattern_polar
  place_on_bed(name) · align_to(name, reference, face, gap)

INSPECT   get_edges / get_faces (name, select) · distance · interference
          printability(name, max_overhang, bed, material)

OUTPUT    render_views(names, views, size)  → image you can see
          export_part(name, 'stl'|'step') · export_all · export_script
```

### Selector cheat-sheet (edges / faces)

```
parallel:Z            runs along Z (sign-agnostic)
normal:Z+             face whose normal points +Z        (sign matters)
at:zmax / at:xmin     the extreme group along an axis
type:circle | line | plane | cylinder …
radius>2   length<10   area>50        metric filters
concave / convex      edges by dihedral convexity
near:(x,y,z)          the single closest element
first / last / index:2 / longest
&  AND    |  OR       e.g.  "type:circle & at:zmax | normal:Z+"
```

## A 30-second example

What an agent does (as tool calls):

```
create_box(name="plate", length=60, width=40, height=10, corner=4)
create_cylinder(name="bore", radius=6, height=40)
subtract(name="plate", tools=["bore"])
fillet_edges(name="plate", radius=2, select="type:circle & at:zmax")
printability(name="plate", bed=[220, 220, 250])
render_views(names=["plate"], views=["iso", "top"])
export_part(name="plate", format="step")
```

`examples/tool_session.py` runs exactly this through the MCP `call_tool`
interface — how the agent sees it:

```bash
python examples/tool_session.py     # writes ./shapewright_out/
```

## How it's built

```
shapewright/
  scene.py     stateful scene of named solids + build123d ops + script log
  select.py    the edge/face selector language
  render.py    tiny numpy+Pillow software renderer (no GPU / no OCC viewer)
  printer.py   overhang / bed-fit / filament analysis
  script.py    op-log -> runnable build123d script
  server.py    MCP tool surface (mcp 2.x MCPServer, stdio)
tests/         unit tests
examples/      a scripted agent session
```

## Tests

```bash
python -m unittest discover -s tests      # 118 tests
python -m coverage run --source=shapewright -m unittest discover -s tests
python -m coverage report                 # ~95% line coverage
```

| suite | tests | covers |
|-------|-------|--------|
| `test_scene_ops.py` | 52 | one focused test per geometry operation (volumes, bboxes, single-solid checks, error paths) |
| `test_selectors.py` | 23 | the whole selector language — signed normals, kinds, metrics, error cases |
| `test_server.py` | 12 | server behaviour + **tool-coverage guard** + error surfacing |
| `test_printer_render.py` | 8 | printability analysis + renderer |
| `test_basics.py` | 23 | original smoke coverage |

**Tool-coverage guard:** `test_server.py::test_every_tool_is_covered` introspects
the live MCP tool list and fails if any registered tool is missing from the smoke
sequence — so adding a tool without a test breaks the build. Invalid inputs raise
a readable `ToolError` (e.g. `ValueError: unknown selector 'wat'`).

The ~5% not covered is defensive `except` branches and the `__main__` guard line.

## Known limits / roadmap

* `printability` reports overhang **area**, not support **volume** or print time.
* No thread library yet — make threads with `curve_helix` + `sweep`.
* No 3MF export (build123d ships STL/STEP/OBJ/GLTF).
* The scene is a single global session (one agent at a time).
* Planned: fillet-radius auto-max, a min-wall-thickness probe, and a recipe
  library (threaded lid, snap fit, living hinge).

## Contributing

Issues and PRs welcome. Please run the test suite before opening a PR, and add a
test for any new tool (the coverage guard will remind you).

## License

[MIT](LICENSE) © 2026 Ananda Satria
