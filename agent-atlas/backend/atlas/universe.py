"""
The coverage universe.

Issuers are FICTIONAL. Tickers, sectors, filing sizes and peer graphs are
invented for this demo, and every financial figure the agent "extracts" is
synthetic. Attaching fabricated fundamentals to a real listed company would
produce a document that looks like research and is not, which is not a thing to
leave lying around in a repo — and the demo needs none of it.

The peer graph is where the interesting behaviour lives. Financials-sector
issuers form a dense, cyclic cluster: NRTH -> HRBR -> STLW -> NRTH. ATLAS walks
it without a visited set (flaw F06).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Issuer:
    ticker: str
    name: str
    sector: str
    filing_pages: int
    figures: int          # tagged financial figures in the filing
    disclosures: int      # disclosure items compliance must catch
    complexity: float     # 0 clean IFRS-standard, 1 pathological
    peers: tuple[str, ...]


UNIVERSE: dict[str, Issuer] = {
    i.ticker: i for i in [
        # --- financials: dense, cyclic peer graph. This is the runaway cluster.
        Issuer("NRTH", "Northgate Financial Group", "Financials", 412, 186, 41, 0.72,
               ("HRBR", "STLW", "MRDN", "CVLT")),
        Issuer("HRBR", "Harbour Union Bancorp", "Financials", 388, 171, 38, 0.68,
               ("NRTH", "STLW", "CVLT")),
        Issuer("STLW", "Stillwater Capital Holdings", "Financials", 356, 158, 35, 0.70,
               ("NRTH", "HRBR", "MRDN")),
        Issuer("MRDN", "Meridian Trust Partners", "Financials", 298, 132, 29, 0.61,
               ("NRTH", "STLW")),
        Issuer("CVLT", "Covalent Insurance Group", "Financials", 344, 149, 33, 0.66,
               ("NRTH", "HRBR")),
        # --- industrials / tech: sparse, acyclic. Terminates fine, which is why
        #     nobody noticed the missing depth cap.
        Issuer("KLDR", "Kilder Industrial Systems", "Industrials", 168, 71, 14, 0.28,
               ("VNTA",)),
        Issuer("VNTA", "Ventra Automation", "Industrials", 142, 63, 12, 0.24, ()),
        Issuer("ORBQ", "Orbiq Semiconductor", "Technology", 96, 44, 9, 0.18, ("TSSL",)),
        Issuer("TSSL", "Tessellate Software", "Technology", 74, 33, 7, 0.12, ()),
        Issuer("GRVN", "Graven Energy Partners", "Energy", 224, 98, 21, 0.44, ("PLMR",)),
        Issuer("PLMR", "Palmara Resources", "Energy", 196, 84, 18, 0.39, ()),
        Issuer("ASTR", "Astera Health Networks", "Healthcare", 258, 112, 26, 0.52, ()),
    ]
}

TOKENS_PER_PAGE = 640

DESKS = ("equity-research", "credit-risk", "ib-coverage")
MANDATES = ("PRIME-A", "PRIME-B", "SELECT-1", "SELECT-2")
ANALYSTS = ("r.okonkwo", "j.arbeláez", "s.nakamura", "d.whitfield")


def issuer(ticker: str) -> Issuer:
    key = ticker.upper().strip()
    if key not in UNIVERSE:
        raise KeyError(f"{key} is not in the coverage universe")
    return UNIVERSE[key]


def tickers() -> list[str]:
    return sorted(UNIVERSE)
