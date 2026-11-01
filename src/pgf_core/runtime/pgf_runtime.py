# pgf_runtime.py -- PaperGalFlow runtime state kernel.
#
# This file is copied verbatim into the generated Ren'Py screen file (indented
# under an ``init python`` block), so it must stay self contained: no imports,
# no ``from __future__`` and no references to PaperGalFlow modules.
#
# It is also imported by pgf-core for tests, which keeps the state machine that
# runs inside the game and the one tested on the host in sync.

PGF_RUNTIME_VERSION = 1


class PGFStore(object):
    """Adapt a Ren'Py persistent object (or any object) to a tiny mapping API."""

    def __init__(self, target):
        self.target = target

    def get(self, key, default=None):
        try:
            return getattr(self.target, key, default)
        except Exception:
            return default

    def set(self, key, value):
        setattr(self.target, key, value)


class PGFDictStore(object):
    """Mapping backed store, used by tests and by the command line tool."""

    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


class PGFKernel(object):
    """Tracks which story nodes the player has seen.

    The kernel is deliberately small.  The generated Ren'Py screen creates one
    when it is shown and asks it for the state of every node; the label
    callback creates one when a label is entered and reports the visit.
    """

    STATE_LOCKED = "locked"
    STATE_UNREAD = "unread"
    STATE_READ = "read"
    STATE_ENDING_LOCKED = "ending_locked"
    STATE_ENDING_READ = "ending_read"

    def __init__(
        self,
        store,
        entry,
        node_ids,
        endings,
        edges,
        label_map=None,
        key="pgf_progress",
        version=PGF_RUNTIME_VERSION,
    ):
        self.store = store
        self.entry = entry
        self.node_ids = tuple(node_ids)
        self.endings = frozenset(endings)
        self.key = key
        self.version = version

        # Only primary edges (flow / choice / condition / end) make a node
        # reachable.  "call" edges point at side scenes the player returns from.
        preds = {}
        for source, target, kind in edges:
            if kind == "call":
                continue
            preds.setdefault(target, []).append(source)
        self._preds = preds

        # Map a Ren'Py label name to every node that label provides.
        self.label_map = dict(label_map or {})
        self._node_set = frozenset(self.node_ids)

    # -- persistence ---------------------------------------------------------
    def _load(self):
        data = self.store.get(self.key, None)
        if not isinstance(data, dict):
            data = {}
        try:
            version = int(data.get("v", 0))
        except Exception:
            version = 0
        if version != self.version:
            data = {}
        seen = data.get("seen", [])
        chosen = data.get("chosen", [])
        if not isinstance(seen, (list, tuple)):
            seen = []
        if not isinstance(chosen, (list, tuple)):
            chosen = []
        return {
            "v": self.version,
            "seen": [str(x) for x in seen],
            "chosen": [str(x) for x in chosen],
        }

    def _save(self, data):
        self.store.set(self.key, data)

    def _seen_set(self):
        return set(self._load()["seen"])

    # -- mutation ------------------------------------------------------------
    def mark_seen(self, node_id):
        """Record that ``node_id`` (usually a label name) was visited."""

        targets = self.label_map.get(node_id)
        if targets is None:
            targets = (node_id,)
        data = self._load()
        seen = set(data["seen"])
        changed = False
        for target in targets:
            if target in self._node_set and target not in seen:
                seen.add(target)
                changed = True
        if changed:
            # Keep a stable order so persistent data diffs nicely.
            data["seen"] = sorted(seen)
            self._save(data)
        return changed

    def mark_chosen(self, source, target):
        """Record that the player took the edge ``source -> target``."""

        edge = source + "\x1f" + target
        data = self._load()
        chosen = set(data["chosen"])
        if edge in chosen:
            return False
        chosen.add(edge)
        data["chosen"] = sorted(chosen)
        self._save(data)
        return True

    def mark_ending(self, node_id):
        return self.mark_seen(node_id)

    def reset(self):
        self._save({"v": self.version, "seen": [], "chosen": []})

    # -- queries -------------------------------------------------------------
    def seen(self, node_id):
        return node_id in self._seen_set()

    def available(self, node_id):
        if node_id == self.entry:
            return True
        if node_id in self._seen_set():
            return True
        for source in self._preds.get(node_id, ()):
            if self.seen(source):
                return True
        return False

    def state(self, node_id):
        seen = self.seen(node_id)
        if node_id in self.endings:
            if seen:
                return self.STATE_ENDING_READ
            return self.STATE_ENDING_LOCKED
        if seen:
            return self.STATE_READ
        if self.available(node_id):
            return self.STATE_UNREAD
        return self.STATE_LOCKED

    def states(self):
        return dict((node_id, self.state(node_id)) for node_id in self.node_ids)

    def summary(self):
        states = self.states()
        result = {
            "seen": 0,
            "unread": 0,
            "locked": 0,
            "ending_reached": 0,
            "ending_total": len(self.endings),
        }
        for value in states.values():
            if value == self.STATE_READ:
                result["seen"] += 1
            elif value == self.STATE_UNREAD:
                result["unread"] += 1
            elif value == self.STATE_LOCKED:
                result["locked"] += 1
            elif value == self.STATE_ENDING_READ:
                result["ending_reached"] += 1
        return result

    def chosen(self):
        result = []
        for item in self._load()["chosen"]:
            parts = str(item).split("\x1f", 1)
            if len(parts) == 2:
                result.append((parts[0], parts[1]))
        return tuple(result)

    def is_chosen(self, source, target):
        return (source + "\x1f" + target) in set(self._load()["chosen"])

    def seen_labels(self):
        return tuple(self._load()["seen"])
