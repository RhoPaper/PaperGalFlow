# Changelog

All notable changes to PaperGalFlow are documented here.  The project follows
[Semantic Versioning](https://semver.org/) and every module or feature bump
gets its own version so the history stays traceable.

## [Unreleased]

## [0.0.4] - 2026-11-01

### Added

- `pgf-adapter-renpy`: `.rpy` source parser producing the same normalized
  statement model as the compiled reader.  Supports labels (including local
  labels), dialogue, menus with captions/conditions, if/elif/else, jumps,
  calls, returns, defines, defaults, styles, python blocks, screens (source
  plus a light element tree) and skips translation blocks.
- Tests for source parsing, comments inside strings, triple quoted dialogue,
  menus, style/define extraction and screen element parsing.

## [0.0.3] - 2026-11-01

### Added

- `pgf-adapter-renpy`: compiled script (`.rpyc`) reader.  Handles RPYC2
  containers (slots 1/2) and the legacy zlib format, unpickles into inert stub
  classes so third party games cannot execute code, and normalises labels,
  dialogue, menus, `if` branches, jumps/calls/returns, defines, styles and
  screen language trees (including screen `use` and element positioning).
- `pgf-adapter-renpy`: `script_model` shared by all future source formats.
- Tests covering synthetic containers, malicious pickles and both installed
  test games.

## [0.0.2] - 2026-11-01

### Added

- `pgf-adapter-renpy`: standard-library only RPA archive reader supporting
  `RPA-3.0`, `RPA-3.2` and `RPA-2.0`, including literal prefixes and
  multi-part entries.
- Secure archive index unpickling: only plain containers are accepted, so a
  malicious game archive cannot execute code while being inspected.
- Tests for synthetic archives (round trip, prefixes, truncation, malicious
  pickles) and an integration test against the installed test game.

## [0.0.1] - 2026-11-01

### Added

- `pgf-core` story graph model (`FlowGraph`, `FlowNode`, `FlowEdge`,
  `NodeKind`, `EdgeKind`) with validation, reachability pruning and JSON
  (de)serialisation.
- Engine independent node state machine with `locked` / `unread` / `read` /
  `ending_locked` / `ending_read`, embedded runtime kernel shared by host
  tests and generated game code.
- Deterministic layered layout engine with cycle breaking, virtual nodes,
  barycenter crossing reduction and orthogonal edge routing.
- Initial test suite and repository scaffolding.
