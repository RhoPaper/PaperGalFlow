# Changelog

All notable changes to PaperGalFlow are documented here.  The project follows
[Semantic Versioning](https://semver.org/) and every module or feature bump
gets its own version so the history stays traceable.

## [Unreleased]

## [0.4.2] - 2026-11-01

### Added

- **JSON theme files.**  `--theme theme.json` can now be passed to `inspect`,
  `build`, `install` and `preview`.  Themes override colours, typography,
  layout, edges, per-state palettes and nine-patch geometry; they can either
  build on the game's extracted style or start from a preset.  Unknown keys,
  invalid colours and malformed JSON fail with a readable error instead of
  generating broken code.
- **`pgf theme` template generator.**  `pgf theme --preset paper_light --out
  theme.json` writes a complete, editable document; without `--out` it prints
  JSON to stdout.
- The offline preview honours the theme's corner radius, border width and a
  soft-shadow SVG filter, and the HTML page uses the themed radius.

### Changed

- Theme application is recorded as a `theme` step in the style chain and as a
  note in `pgf inspect --json`; `PGF_STYLE`/`PGF_UI` and the generated assets
  all follow the themed tokens.

## [0.4.1] - 2026-11-01

### Added

- **Region-aware UI sampling.**  `analyze_png()` reports the centre colour,
  edge colour, top/bottom gradient bands, opacity/coverage, rounded-corner
  alpha and estimated nine-patch insets instead of only a whole-image average.
  Translucent and gradient panels are now recognised from the asset itself.
- **Archive panel discovery.**  When no panel asset is referenced by readable
  GUI/screen source, `GameArchive.find_assets()` scans disk and `.rpa`
  archives (including `images.rpa`) for choice/dialog/frame/panel art, so
  compiled-only games still contribute colours, border colour and nine-patch
  geometry.
- `pgf-style` applies the sampled centre colour, border colour, corner radius
  and border width to the tokens, and records gradient/translucency/insets in
  the style notes and JSON evidence.

### Changed

- Panel sampling uses the centre region (and reports the gradient endpoints)
  rather than the average of the whole image, which previously biased colours
  towards borders, shadows and transparent padding.
- `UiSample` carries `center`, `edge`, `insets`, `border_width`,
  `corner_radius`, `gradient*`, `coverage` and `opacity`; `pgf inspect --json`
  exposes them.

## [0.4.0] - 2026-11-01

### Added

- **Nine-patch rounded UI assets.**  `pgf-adapter-renpy` now renders its own
  anti-aliased PNG assets with a pure-Python encoder: six node palettes (plus
  hover), legend swatches, a soft drop shadow, top/bottom panel bars, edge
  labels and chrome buttons.  The generated screen uses Ren'Py `Frame` with
  per-asset slice sizes, so every node and panel has genuine rounded corners
  instead of four `Solid` border strips.  Assets live in `game/pgf_ui/` and
  carry a `Software=PaperGalFlow` PNG text marker.
- **Soft shadows.**  Nodes and the title bar get blurred alpha shadows instead
  of hard offset rectangles.
- `pgf-style`: `corner_radius` / `border_width` geometry tokens, serialised in
  the theme dictionary and honoured by the asset generator.
- Binary generated artifacts: the installer, uninstaller, verifier, manifest
  and `pgf build` now handle PNG payloads and nested `pgf_ui/` paths with the
  same ownership, hash and atomic-write rules as `.rpy` files.

### Changed

- The generated `pgf_flowchart_screen.rpy` embeds `PGF_UI` and references
  `Frame(...)` displayables for node/panel/button backgrounds; the quick-menu
  entry button uses the same rounded accent asset.
- `pgf build` prints paths relative to the output directory.

## [0.3.0] - 2026-11-01

### Changed

- **Node jumps reuse the game's HISTORY rollback.**  Clicking a node with a
  checkpoint in the current save's `_history_list` shows the same `Confirm`
  dialog as the HISTORY jump-back buttons and calls
  `RollbackToIdentifier(identifier)`.  History becomes "the target and
  everything before it", and Ren'Py restores variables and branch state.
- Nodes without a usable checkpoint are labelled `无历史` and are not
  clickable; no synthetic history, replay menus or game-state writes are
  generated.

## [0.2.0] - 2026-11-01

### Changed

- **Only scene labels are jump targets.**  Clicking a scene/ending node calls
  exactly one thing: `renpy.jump_out_of_context(label)` for a label that exists
  in the game.  Choice and condition nodes are informational ("仅展示"); the
  generated replay menus and all synthesized choice logic are removed.
- **Node state now comes from Ren'Py itself.**  The generated screen reads
  `renpy.seen_label`; it no longer embeds a state kernel, registers
  `config.label_callbacks` or writes `persistent.pgf_progress`.  This also
  means previously played progress is reflected immediately, and PaperGalFlow
  has no runtime state of its own to clean up.

### Removed

- Choice-node replay labels and the option metadata used to build them.
- The embedded `PGFKernel` runtime and the label-callback hook.

### Fixed

- Reinstall no longer parses its own `pgf_*` files as game source.
- Installing a new `.rpy` removes the stale `.rpyc` companion.

## [0.1.1] - 2026-11-01

### Fixed

- **Choice nodes jumped to the start of their scene.**  A menu inside a label
  has no label of its own, so the chart only knew the containing label.  The
  generator now emits a replay `label` per choice node that reopens the same
  menu (caption + options, using the game's own choice UI) and jumps to the
  selected branch.  Condition nodes are no longer clickable because their
  evaluation cannot be replayed safely.
- **Reinstalling could parse the tool's own generated files as game source.**
  This turned the previous `quick_menu` hook into a self-referential patch and
  could raise `Screen 'pgf_hotkey' is not known`.  Generated `pgf_*` files are
  now excluded from the virtual game archive.
- Installing a new `.rpy` now removes the stale `.rpyc` so Ren'Py recompiles
  the updated screen immediately.

### Added

- Regression tests for choice replay labels, generated-file exclusion,
  reinstall safety and compiled-file cleanup.

## [0.1.0] - 2026-11-01

First usable release.

### Added

- Complete end-to-end pipeline: parse a Ren'Py game, build the story graph,
  explain the degradation chains, compute layout, probe game style, generate
  the flowchart screen and the entry hook, install atomically and roll back.
- Documentation set: architecture, usage, limitations and roadmap.
- Real-game verification on both provided Ren'Py 8.6 titles (Linux): parsing,
  generation, Ren'Py lint, in-game opening, node jump, close, zoom, scroll and
  uninstall, plus quick-menu source patch mode tested with a source fixture.

### Fixed

- Generated chrome widgets no longer depend on the game's default GUI images,
  which many commercial builds omit.
- `pgf uninstall` removes Ren'Py's compiled `.rpyc` companions so reverting
  really reverts.
- The offline preview starts centred on the entry node instead of an empty
  corner of the canvas.

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
