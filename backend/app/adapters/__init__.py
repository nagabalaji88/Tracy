from app.adapters.base import (  # noqa: F401
    CostMeter,
    Scorer,
    get_cost_meter,
    get_scorer,
    register_cost_meter,
    register_scorer,
    registered,
)
from app.adapters.contract_analysis import register_all
from app.adapters.atlas import register as register_atlas

register_all()
register_atlas()
