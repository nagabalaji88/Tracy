"""
The instrumented subject: a 4-stage sequential contract-analysis pipeline.

    retrieve -> clause_extract -> risk_assess -> synthesize

Long context, stage accumulation, retries on structured-output failures — the
shape that makes cost and quality trade against each other.

A CONFIG is a declarative set of levers. The same lever vocabulary is what
Module 4's simulator projects over, so a simulated config and a recorded config
are the same object.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

STAGES = ("retrieve", "clause_extract", "risk_assess", "synthesize")

# Per-stage capability of each model tier at the extraction task. These are
# properties of the RECORDING, not of the control plane: the deterministic
# provider uses them to shape recorded runs. The measurement core never sees
# them — it only ever reads what was recorded.
TIER_SKILL = {
    "premium-reasoning": 0.985,
    "workhorse": 0.955,
    "small-fast": 0.760,
    "embedding-small": 1.0,
}

TIER_LATENCY_MS_PER_KTOK = {
    "premium-reasoning": 210.0,
    "workhorse": 95.0,
    "small-fast": 38.0,
    "embedding-small": 6.0,
}


@dataclass
class Config:
    config_id: str
    label: str
    role: str                      # baseline | candidate | ablation
    use_case: str = "contract_analysis"
    prompt_version: str = "cv-2026-06-14"
    model_by_stage: dict[str, str] = field(default_factory=dict)
    prompt_cache: bool = False
    semantic_cache: bool = False
    top_k: int = 12
    output_cap: int = 4000
    batch_stages: tuple[str, ...] = ()
    reasoning: bool = True
    ablated_stage: str | None = None

    def levers(self) -> dict:
        d = asdict(self)
        for k in ("config_id", "label", "role", "use_case", "ablated_stage"):
            d.pop(k)
        d["batch_stages"] = list(self.batch_stages)
        return d

    def stages(self) -> tuple[str, ...]:
        return tuple(s for s in STAGES if s != self.ablated_stage)


BASELINE = Config(
    config_id="baseline_v1",
    label="Baseline",
    role="baseline",
    model_by_stage={
        "retrieve": "embedding-small",
        "clause_extract": "workhorse",
        "risk_assess": "premium-reasoning",
        "synthesize": "workhorse",
    },
    prompt_cache=False,
    semantic_cache=False,
    top_k=12,
    output_cap=4000,
)

# The naive cost-cutting change a well-meaning engineer ships on a Friday:
# "we're sending far too much context and letting the model ramble — cap both,
# and the downstream stages don't need the expensive model." Every one of those
# statements is defensible. Together they cost 31 points of clause recall.
NAIVE_CHEAP = Config(
    config_id="naive_cheap_v1",
    label="Naive-cheap",
    role="candidate",
    model_by_stage={
        "retrieve": "embedding-small",
        "clause_extract": "workhorse",
        "risk_assess": "small-fast",
        "synthesize": "small-fast",
    },
    prompt_cache=False,
    semantic_cache=False,
    top_k=3,            # the saving that quietly costs recall
    output_cap=1200,    # the saving that quietly truncates long documents
    reasoning=False,
)

OPTIMISED = Config(
    config_id="optimised_v1",
    label="Optimised",
    role="candidate",
    model_by_stage={
        "retrieve": "embedding-small",
        "clause_extract": "workhorse",
        "risk_assess": "premium-reasoning",
        "synthesize": "small-fast",
    },
    prompt_cache=True,      # the shared contract preamble is cached across stages
    semantic_cache=True,    # repeat retrievals on re-analysed documents
    top_k=11,
    output_cap=4000,
    # Deliberately NOT batching: the batch lever is offered by the Module 4
    # simulator and gets flagged there for the latency ceiling.
    batch_stages=(),
)

ABLATIONS = [
    Config(
        config_id=f"ablate_{stage}",
        label=f"Baseline minus {stage}",
        role="ablation",
        model_by_stage=dict(BASELINE.model_by_stage),
        prompt_cache=BASELINE.prompt_cache,
        semantic_cache=BASELINE.semantic_cache,
        top_k=BASELINE.top_k,
        output_cap=BASELINE.output_cap,
        ablated_stage=stage,
    )
    for stage in ("retrieve", "risk_assess", "synthesize")
]

EVAL_CONFIGS = [BASELINE, NAIVE_CHEAP, OPTIMISED, *ABLATIONS]

CONFIG_BY_ID = {c.config_id: c for c in EVAL_CONFIGS}

# Prompt-version deploys in the production stream. Every edit is a regime
# change; Module 3 draws a change-point marker at each of these.
PROMPT_DEPLOYS = [
    ("cv-2026-06-14", 0),
    ("cv-2026-06-27", 13),
    ("cv-2026-07-09", 25),
    ("cv-2026-07-21", 37),
]
