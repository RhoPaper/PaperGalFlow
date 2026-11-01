# Changelog

All notable changes to PaperGalFlow are documented here.  The project follows
[Semantic Versioning](https://semver.org/) and every module or feature bump
gets its own version so the history stays traceable.

## [Unreleased]

## [0.0.11] - 2026-11-01

### Added

- `pgf-core`: adapter protocol, entry-point registry (`pgf.adapters`), core
  degradation chains for story/style/entry, the end-to-end pipeline and the
  `pgf` CLI (`adapters`, `detect`, `inspect`, `build`, `install`, `uninstall`,
  `status`, `preview`).
- `pgf-adapter-renpy`: adapter facade implementing the protocol with a single
  session cache, Ren'Py log metadata reading, preset graph fallback and manifest
  status reporting.
- Development launcher `pgf.py`, fake-adapter tests for the fallback chains and
  CLI tests.

## [0.0.10] - 2026-11-01

### Added

- `pgf-adapter-renpy`: entry hook generator.  When a game ships `quick_menu`
  source, the original screen is copied under a private name and a wrapper is
  installed at a late init priority with an appended button.  For compiled-only
  games the fallback draws a companion button next to the original quick menu
  using positions extracted from the screen AST.  A hotkey screen is always
  installed.
- `pgf-adapter-renpy`: transactional installer with marker checks, atomic
  writes, SHA-256 manifest, verification, uninstall (including Ren'Py's
  compiled `.rpyc` companions) and static generated-code checks.
- Tests for both entry modes, placement, install/verify/uninstall and the
  file-safety rules.

## [0.0.9] - 2026-11-01

### Added

- `pgf-adapter-renpy`: full flowchart screen generator.  Emits a standalone
  `pgf_flowchart_screen.rpy` containing the embedded runtime state kernel,
  precomputed nodes/edges/labels, the six state palettes, title bar, legend,
  zoom controls, draggable viewport and scroll buttons.  The screen never falls
  back to the game's default GUI images, which many commercial games exclude.
- `pgf-core`: offline HTML/SVG previewer that renders the exact layout and
  style tokens for review without starting Ren'Py.
- Tests for generated code structure, condition-label hiding, determinism and
  end-to-end analyse → layout → emit.

## [0.0.8] - 2026-11-01

### Added

- `pgf-adapter-renpy`: dependency free PNG decoder (8/16 bit, greyscale, RGB,
  palette, grey+alpha, RGBA) and colour sampler for UI assets stored in
  `.rpa` archives, with row-limited decoding for large backgrounds.
- `pgf-adapter-renpy`: style probe reading `gui.*` defines, style blocks,
  screen language trees and screen size (`gui.init`), sampling the game's own
  quick menu icons / option buttons / textbox / menu background, and
  extracting quick menu button positions into a placement helper.
- Tests with synthetic PNGs, a synthetic source game and both real games.

## [0.0.7] - 2026-11-01

### Added

- `pgf-style`: engine independent style tokens (colours, typography, spacing,
  per-state node palettes), colour parsing/interpolation/contrast helpers,
  dark/light presets, evidence blending with per-field fallbacks and
  translation of tokens into Ren'Py style blocks and a serialisable theme
  dictionary.
- Tests for colour parsing, token round trips, evidence blending and theme
  generation.

## [0.0.6] - 2026-11-01

### Added

- `pgf-adapter-renpy`: story graph analyzer.  Walks labels, dialogue, menus
  and if/elif/else chains; creates scene, choice, condition and ending nodes;
  follows jumps, treats calls as side edges, resolves local labels, handles
  fall through, collapses router labels and trivial conditions, prunes
  unreachable labels, and turns jumps to engine labels such as
  ``splashscreen``/``quit`` into special ending nodes.
- Deterministic output and diagnostics (`warnings` / `notes`).
- Tests against a synthetic branching script and both installed test games.

## [0.0.5] - 2026-11-01

### Added

- `pgf-adapter-renpy`: `GameArchive` virtual file system for a Ren'Py `game/`
  directory, merging disk files and `.rpa` archives with Ren'Py precedence
  rules (disk over archive, `.rpy` over `.rpyc`, `tl/` excluded), cached
  script parsing, screen source lookup and non-fatal warnings for broken
  files.
- Tests for mixed disk/archive trees, translations, broken scripts and the
  installed test game.

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
