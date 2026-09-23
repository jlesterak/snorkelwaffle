"""Find stretches of near-identical audio between two chromaprint fingerprints.

Approach (the classic seed-and-extend used by most fingerprint matchers):

1. Seeds: fingerprint values that occur exactly in both arrays. Values that
   repeat a lot (silence, tones) are dropped because they seed everything.
2. Each seed votes for a diagonal ``d = i_a - i_b`` (a time offset between the
   two files). Offsets that collect enough votes are candidates.
3. Along each candidate diagonal the per-item bit error (popcount of XOR) is
   computed, smoothed, and thresholded. Runs that stay under the threshold for
   long enough are matches.

Everything is vectorised numpy, so comparing two one-hour episodes (~29k
values each) takes a few milliseconds.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class Match:
    a_start: int
    a_end: int  # exclusive
    b_start: int
    b_end: int  # exclusive
    ber: float  # mean bit error rate over the match, 0..1

    @property
    def length(self):
        return self.a_end - self.a_start

    @property
    def offset(self):
        return self.a_start - self.b_start


@dataclass
class MatchParams:
    min_items: int = 60        # ~7.4 s
    max_bits: float = 9.0      # mean differing bits (of 32) allowed along a match
    window: int = 16           # smoothing window, items
    gap_items: int = 10        # bridge dropouts up to ~1.2 s inside a match
    min_seeds: int = 4         # exact-hash hits needed before a diagonal is examined
    max_dup: int = 6           # skip values that repeat more than this (silence, tones)
    max_diagonals: int = 64


def popcount(x):
    return np.bitwise_count(x)


class Prepared:
    """A fingerprint with its sort index precomputed, for matching many queries."""

    __slots__ = ("arr", "order", "sorted")

    def __init__(self, arr):
        self.arr = np.asarray(arr, dtype=np.uint32)
        self.order = np.argsort(self.arr, kind="stable")
        self.sorted = self.arr[self.order]

    def __len__(self):
        return len(self.arr)


def _seeds(a, b, max_dup):
    """Return index arrays (ia, ib) of positions where a[ia] == b.arr[ib]."""
    if len(a) == 0 or len(b) == 0:
        return np.empty(0, np.int64), np.empty(0, np.int64)
    _, inv_a, cnt_a = np.unique(a, return_inverse=True, return_counts=True)
    a_ok = cnt_a[inv_a] <= max_dup
    order, bs = b.order, b.sorted
    lo = np.searchsorted(bs, a, "left")
    hi = np.searchsorted(bs, a, "right")
    cnt = hi - lo
    keep = a_ok & (cnt > 0) & (cnt <= max_dup)
    ia = np.nonzero(keep)[0]
    if len(ia) == 0:
        return np.empty(0, np.int64), np.empty(0, np.int64)
    c = cnt[ia]
    total = int(c.sum())
    rep_ia = np.repeat(ia, c)
    offs = np.arange(total) - np.repeat(np.cumsum(c) - c, c)
    ib = order[np.repeat(lo[ia], c) + offs]
    return rep_ia.astype(np.int64), ib.astype(np.int64)


def _diag_errors(a, b, d):
    """Bit errors along diagonal d for every a index; 32 where b has no partner.

    Takes the min over d-1, d, d+1 so that a sub-item misalignment between two
    encodes of the same audio doesn't inflate the error.
    """
    la, lb = len(a), len(b)
    best = np.full(la, 32, dtype=np.int64)
    idx = np.arange(la)
    for dd in (d - 1, d, d + 1):
        j = idx - dd
        ok = (j >= 0) & (j < lb)
        e = np.full(la, 32, dtype=np.int64)
        e[ok] = popcount(a[ok] ^ b[j[ok]])
        np.minimum(best, e, out=best)
    return best


def _runs(mask):
    """Return (starts, ends) of True runs in a boolean array."""
    padded = np.concatenate(([False], mask, [False]))
    diff = np.diff(padded.astype(np.int8))
    return np.nonzero(diff == 1)[0], np.nonzero(diff == -1)[0]


def _runs_on_diagonal(a, b, d, p):
    err = _diag_errors(a, b, d)
    w = max(1, p.window)
    kernel = np.ones(w) / w
    smooth = np.convolve(err, kernel, mode="same")
    starts, ends = _runs(smooth <= p.max_bits)
    merged = []
    for s, e in zip(starts.tolist(), ends.tolist()):
        if merged and s - merged[-1][1] <= p.gap_items:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    out = []
    for s, e in merged:
        while s < e and err[s] > p.max_bits:
            s += 1
        while e > s and err[e - 1] > p.max_bits:
            e -= 1
        if e - s < p.min_items:
            continue
        ber = float(err[s:e].mean()) / 32.0
        out.append(Match(s, e, s - d, e - d, ber))
    return out


def _overlap(s1, e1, s2, e2):
    return max(0, min(e1, e2) - max(s1, s2))


def find_matches(a, b, params=None):
    """Return non-overlapping Matches between fingerprints ``a`` and ``b``.

    ``b`` may be a :class:`Prepared` to reuse its sort index across calls.
    """
    p = params or MatchParams()
    a = np.asarray(a, dtype=np.uint32)
    bp = b if isinstance(b, Prepared) else Prepared(b)
    b = bp.arr
    if len(a) < p.min_items or len(b) < p.min_items:
        return []
    ia, ib = _seeds(a, bp, p.max_dup)
    if len(ia) == 0:
        return []
    diags, counts = np.unique(ia - ib, return_counts=True)
    cand = diags[counts >= p.min_seeds]
    if len(cand) == 0:
        return []
    cand_counts = counts[counts >= p.min_seeds]
    cand = cand[np.argsort(-cand_counts, kind="stable")][: p.max_diagonals]

    found = []
    for d in cand.tolist():
        found.extend(_runs_on_diagonal(a, b, int(d), p))

    # Keep the longest/cleanest match wherever neighbouring diagonals found the
    # same stretch of audio.
    found.sort(key=lambda m: (-m.length, m.ber))
    kept = []
    for m in found:
        dup = False
        for k in kept:
            oa = _overlap(m.a_start, m.a_end, k.a_start, k.a_end)
            ob = _overlap(m.b_start, m.b_end, k.b_start, k.b_end)
            if oa > 0.5 * m.length and ob > 0.5 * m.length:
                dup = True
                break
        if not dup:
            kept.append(m)
    kept.sort(key=lambda m: m.a_start)
    return kept


def union_ranges(ranges, gap=0):
    """Merge [start, end) ranges that overlap or sit within ``gap`` of each other."""
    out = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def subtract_ranges(ranges, holes):
    """Return parts of ``ranges`` not covered by ``holes`` (both lists of (s, e))."""
    holes = union_ranges(holes)
    out = []
    for s, e in ranges:
        cur = s
        for hs, he in holes:
            if he <= cur or hs >= e:
                continue
            if hs > cur:
                out.append((cur, hs))
            cur = max(cur, he)
        if cur < e:
            out.append((cur, e))
    return out
