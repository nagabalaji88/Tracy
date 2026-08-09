"""
The golden set.

Deliberately oversampled on the hard tail: the longest documents and the
non-standard structures. Aggregate quality metrics hide exactly the failures
that matter, so a golden set weighted like production traffic is a golden set
that will not catch the regression you care about.

Tiers
  standard      — well-formed MSAs, predictable clause headings
  long          — 90-260 page agreements with schedules and annexes
  non_standard  — scanned/handwritten amendments, tables-as-clauses, foreign law
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class GoldenDoc:
    doc_id: str
    tier: str
    pages: int
    doc_tokens: int
    clause_count: int          # size of the gold clause set
    structure_penalty: float   # 0 = clean headings, 1 = pathological
    gold_clause_ids: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def _clause_ids(doc_id: str, n: int) -> tuple[str, ...]:
    return tuple(f"{doc_id}::C{i:03d}" for i in range(1, n + 1))


def _jitter(seed_key: str, lo: float, hi: float) -> float:
    h = int(hashlib.sha256(seed_key.encode()).hexdigest()[:12], 16)
    return lo + (h % 10_000) / 10_000.0 * (hi - lo)


# (count, tier, page range, structure penalty range)
_TIER_SPEC = [
    (8, "standard", (14, 40), (0.00, 0.10)),
    (8, "long", (95, 260), (0.10, 0.30)),
    (8, "non_standard", (22, 120), (0.45, 0.85)),
]

_TOKENS_PER_PAGE = 620
_CLAUSES_PER_PAGE = 0.55


def build_golden_set() -> list[GoldenDoc]:
    docs: list[GoldenDoc] = []
    idx = 0
    for count, tier, (p_lo, p_hi), (s_lo, s_hi) in _TIER_SPEC:
        for i in range(count):
            idx += 1
            doc_id = f"DOC-{idx:03d}"
            pages = int(p_lo + _jitter(f"{doc_id}/pages", 0, 1) * (p_hi - p_lo))
            clause_count = max(8, int(pages * _CLAUSES_PER_PAGE * _jitter(f"{doc_id}/cl", 0.7, 1.25)))
            docs.append(
                GoldenDoc(
                    doc_id=doc_id,
                    tier=tier,
                    pages=pages,
                    doc_tokens=pages * _TOKENS_PER_PAGE,
                    clause_count=clause_count,
                    structure_penalty=round(_jitter(f"{doc_id}/struct", s_lo, s_hi), 4),
                    gold_clause_ids=_clause_ids(doc_id, clause_count),
                )
            )
    return docs


GOLDEN_SET = build_golden_set()
