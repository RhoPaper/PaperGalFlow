# Changelog

All notable changes to PaperGalFlow are documented here.  The project follows
[Semantic Versioning](https://semver.org/) and every module or feature bump
gets its own version so the history stays traceable.

## [Unreleased]

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
