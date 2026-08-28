import json

from pydantic import BaseModel, Field

# The column order is a contract. The CSV and the JSON both use it.
COLUMNS = [
    "retailer",
    "category",
    "product_url",
    "sku",
    "name",
    "brand",
    "price_gbp",
    "size_raw",
    "size_ml",
    "abv_percent",
    "pack_type",
    "country_of_origin",
    "flavour_style",
    "availability",
    "description",
    "field_sources",
    "scraped_at",
]


class Product(BaseModel):
    retailer: str
    category: str
    product_url: str
    scraped_at: str

    sku: str | None = None
    name: str | None = None
    brand: str | None = None
    price_gbp: float | None = None
    size_raw: str | None = None
    size_ml: float | None = None
    abv_percent: float | None = None
    pack_type: str | None = None
    country_of_origin: str | None = None
    flavour_style: str | None = None
    availability: str | None = None
    description: str | None = None

    # Records where each value came from: jsonld, css, regex, llm or missing.
    field_sources: dict[str, str] = Field(default_factory=dict)

    # Visible page text. The extractors read it. It never reaches the output.
    detail_text: str = ""

    def to_row(self) -> dict[str, object]:
        data = self.model_dump()
        data["field_sources"] = json.dumps(self.field_sources, sort_keys=True)
        return {name: data[name] for name in COLUMNS}
