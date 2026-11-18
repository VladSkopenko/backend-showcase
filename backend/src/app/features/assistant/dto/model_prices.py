from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ModelPrices:
    input_per_million_usd: Decimal
    cached_input_per_million_usd: Decimal
    output_per_million_usd: Decimal
