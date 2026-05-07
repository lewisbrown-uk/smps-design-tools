"""Caching wrapper for metrics callables.

Memoizes ``(values dict) -> (output dict)`` mappings so repeated MC
sweeps over the same component values don't re-run the simulator.
ngspice runs are seconds each; a 1000-sample sweep over 5 candidates
is hours of compute that mostly repeats across design iterations,
spec tweaks, or replays.
"""
import hashlib
import json
import sqlite3
import threading
from pathlib import Path


def _key(values):
    """Stable JSON encoding of a values dict — sorted keys + Python's
    full-precision float repr makes bit-identical inputs produce
    bit-identical keys, which is what we want for cache lookup."""
    return json.dumps(sorted(values.items()), separators=(",", ":"))


def _signature_from(wrapped):
    """If the wrapped callable exposes ``signature()``, use it; else
    fall back to the qualified type name. The signature isolates
    cache entries when multiple backends share a single cache file —
    without it, swapping templates would silently return stale data."""
    sig_fn = getattr(wrapped, "signature", None)
    if callable(sig_fn):
        return str(sig_fn())
    return type(wrapped).__qualname__


class CachedBackend:
    """Memoizing wrapper around any metrics callable.

    Use::

        cached = CachedBackend(
            NgspiceBackend(template=..., outputs=["fc"]),
            path="cache.sqlite",
        )
        report = analyze(metrics=cached, ..., workers=14)
        print(cached.hits, cached.misses)

    Args:
        wrapped: The metrics callable being memoized — typically
            ``NgspiceBackend``, but anything taking ``**values`` and
            returning a dict works.
        path: sqlite file for persistent cache. ``None`` (default) →
            in-memory only, lost on process exit. Persistent caching
            survives across runs and is the headline win — a tweaked
            spec on the same MC samples is then near-instant.
        signature: String namespace within the cache file.
            Auto-derived from ``wrapped.signature()`` if available, else
            the wrapped class name. Override only if you need explicit
            isolation.

    Threading: safe to share across threads. The sqlite connection is
    created with ``check_same_thread=False`` and writes are serialized
    by a single Lock. There is **no in-flight deduplication** — two
    concurrent calls with the same key both compute (the second write
    wins). For our MC use that's harmless and avoids the complexity
    of a per-key lock; samples in one MC run are nearly all distinct.

    Caveats:

    - Cache entries never expire. ``clear()`` is the only way to evict.
    - Failed simulations (NaN outputs) are cached too. If you suspect
      transient ngspice flakiness, ``clear()`` and re-run.
    - Float keys are matched bit-exactly. Two ``analyze`` calls with
      the same seed produce the same samples, so this is fine in
      practice; manually-constructed values that differ in the last bit
      will miss the cache.
    """

    def __init__(self, wrapped, *, path=None, signature=None):
        self.wrapped = wrapped
        self.path = Path(path) if path is not None else None
        self.signature = signature if signature is not None \
                         else _signature_from(wrapped)
        self._mem = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(
                str(self.path), check_same_thread=False
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS cache "
                "(signature TEXT, key TEXT, value TEXT, "
                "PRIMARY KEY (signature, key))"
            )
            self._db.commit()
        else:
            self._db = None

    def __call__(self, **values):
        key = _key(values)

        with self._lock:
            if key in self._mem:
                self.hits += 1
                return self._mem[key]

        if self._db is not None:
            with self._lock:
                row = self._db.execute(
                    "SELECT value FROM cache WHERE signature=? AND key=?",
                    (self.signature, key),
                ).fetchone()
            if row is not None:
                value = json.loads(row[0])
                with self._lock:
                    self._mem[key] = value
                    self.hits += 1
                return value

        # Miss — compute outside the lock so concurrent misses on
        # different keys don't serialize on the simulator wait.
        with self._lock:
            self.misses += 1
        result = self.wrapped(**values)
        with self._lock:
            self._mem[key] = result
            if self._db is not None:
                self._db.execute(
                    "INSERT OR REPLACE INTO cache "
                    "(signature, key, value) VALUES (?, ?, ?)",
                    (self.signature, key, json.dumps(result)),
                )
                self._db.commit()
        return result

    def clear(self):
        """Drop every cached entry for this signature (in-memory and
        on-disk if persistent). Other signatures in the same cache
        file are untouched."""
        with self._lock:
            self._mem.clear()
            if self._db is not None:
                self._db.execute(
                    "DELETE FROM cache WHERE signature=?",
                    (self.signature,),
                )
                self._db.commit()
            self.hits = 0
            self.misses = 0

    def close(self):
        """Close the sqlite connection. Idempotent. After close, calls
        to this backend will fail; create a new instance to resume."""
        if self._db is not None:
            self._db.close()
            self._db = None
