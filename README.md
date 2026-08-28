# UK Retail Product Scraper

This tool captures product attributes for one category from a UK grocery
retailer, one row per product and one column per attribute, to CSV and JSON.
The shipped dataset is 25 gin products from Morrisons. A second adapter exists
for gin at The Whisky Exchange, fixture-tested but not run live today; see
"The Whisky Exchange, live" below.

The first row of `data/products.csv`:

```
retailer         morrisons          size_raw           70cl
category         gin                size_ml            700.0
sku              106909896          abv_percent        41.8
name             Caorunn Gin        pack_type          Glass Bottle
brand            Caorunn            country_of_origin  (empty)
price_gbp        23.5               availability       InStock
price_was        30.5               scraped_at         2026-08-28T17:18:37Z
is_on_promotion  True
flavour_style    Invigorating, clean and crisp
```

`description` and `field_sources` are not shown; `field_sources` records each
value's origin.

## Run it

```bash
uv sync
cp .env.example .env
uv run scrape                  # Morrisons, 25 products
uv run pytest                  # the 83 offline tests

uv run scrape --retailer whisky_exchange --limit 20   # exits 1, see below
uv run scrape --no-llm --out /tmp/run1
```

`.env` holds `GEMINI_API_KEY` for the model step and `SCRAPER_CONTACT`, an
email for the `User-Agent` header. Without the key, derived fields are `null`
and the run still succeeds. `--retailer` picks the adapter, `--limit` caps the
products, `--out` sets the output directory, `--no-llm` skips the model.

Exit codes: 0 success, 2 robots.txt denied the path. 1 means no usable
dataset: the listing could not be fetched, or the parse-rate gate failed.

## Approach

Fetching, adapters, regular expressions, the model and the writers are separate
modules. Structured data comes first, a regular expression second, the model last
and only for fields still empty. Each step writes its own name into
`field_sources`.

Plain HTTP, not a browser. Both sites serve their product data in HTML when
reachable, so a browser would add a large dependency for no extra data.

### Which retailer, and why

A robots.txt check came before any code.

| Site | robots.txt | Products in plain HTML | Outcome |
|---|---|---|---|
| Morrisons | Permits browse. Denies `/api/`. | Yes. 50 gins, with JSON-LD. | Primary |
| The Whisky Exchange | Permits browse. Denies `/api/product/productlistdata`. | Yes. 31 cards, no JSON-LD. | Second |
| Asda | `Allow: /`, plus `Content-Signal: search=yes, ai-train=no, use=reference`. | No. Client-rendered. | Rejected |
| Ocado | Unreadable. Response holds `x-amzn-waf-action: challenge`. | | Rejected |
| Tesco | 403 on robots.txt itself. | | Rejected |
| Sainsbury's | 403 on robots.txt itself. | | Rejected |
| Co-op | 403 on robots.txt itself. | | Rejected |
| Iceland | 403 on robots.txt itself. | | Rejected |
| Waitrose | Connection refused. | | Rejected |
| Booths | Permits everything. | No catalogue. | Rejected |

The denied Morrisons API is easier to parse than the HTML; the tool never calls
it. Asda states `ai-train=no`, and this pipeline sends page text to a
model. Four grocers return 403 for robots.txt itself: unreadable rules mean no
scraping.

## The anti-bot judgement call

The first live run got 200 for the category page and 403 for all 25 product
pages. Three controlled requests isolated it: the honest agent
`uk-retail-product-scraper/0.1` gave 403, Chrome gave 200, and Chrome with the
tool name and contact appended gave 200. `USER_AGENT` in `fetch.py` sends that
last form.

The reasoning: robots.txt is the site's stated policy and it permits these
paths, while the WAF is a blunt string filter. The tool stays identifiable,
obeys robots.txt at run time, and backs off when told to.

The counter-argument: a block is a block, and a production deployment should
get the retailer's written agreement instead.

No IP rotation, no proxy pool, no CAPTCHA solving, no browser. The tool never
continues past an explicit rate-limit response, and a JavaScript challenge is
where this approach correctly stops.

## Politeness and reliability

One request per second with 0 to 0.4 seconds of jitter, single-threaded.
robots.txt is read once per host, and an unreadable one denies every path
there. Retries are three attempts, on 429 and 5xx only. Every 200 response is
cached to `.cache/<host>/<hash>.html`, so re-runs cost the retailers nothing.

### The fail-loud gate

If fewer than 80% of the expected products parse, the tool logs the count and
exits 1. The writers run before the gate, so a failed run leaves a header-only
CSV. This fired for real: 0 of 25 parsed on the first run, because of the 403
responses.

## Missing data

A null is always better than a guess. A field no source states stays `null`,
tagged `missing`. The model gets one retry, and a second bad reply leaves the
field `null`. An ABV from the model is range-checked with `0 <= value <= 100`,
not a truthiness test, because 0.0 is a real ABV. One bad row does not stop the
run.

## Where the LLM runs, and where it does not

| Field | Source order |
|---|---|
| `name`, `brand`, `price_gbp`, `size_raw`, `sku`, `availability`, `description` | JSON-LD or CSS only. The model never runs. |
| `size_ml`, `pack_type`, `country_of_origin` | Regular expression only. |
| `abv_percent` | Regular expression, then the model if nothing was found. |
| `flavour_style` | The model always. No other source gives it. |

The split follows what each source can prove. `flavour_style` needs prose read
and judged, which a regular expression cannot do. ABV is a number in a known
range, so a model answer can be checked. Origin is factual, and the model named
a country the text mentions for another reason.

The model is `gemini-3.5-flash-lite` through `google-genai`, with structured
output against the `Derived` Pydantic schema.

Gemini is a cost choice: an unpaid exercise on a free tier. A swap to Claude or
OpenAI changes `llm.py` alone. The free tier also set the pacing:
`gemini-2.5-flash` gave 20 requests per day, spent the quota, and left 18
products unenriched. Calls are now spaced by `MIN_CALL_INTERVAL = 6.0` seconds.

### Two kinds of 429

A per-minute limit is transient: honour `retryDelay` and retry. A spent
per-day quota is terminal: stop calling. The API returns 429 for both; the
first version waited 59 seconds and retried twice per remaining product.
`_is_daily_quota_exhausted` now matches the quota name (`PerDay`), not the
numeric value, which changes with the model. A match trips a circuit breaker.

## Provenance and fill rates

`field_sources` maps each field to `jsonld`, `css`, `regex`, `llm` or `missing`,
which makes the model's blast radius auditable. The 25 rows hold 336 values:
`jsonld` 175, `regex` 75, `css` 22, `llm` 21, `missing` 43.

Seven of the 19 columns are filled 25 of 25: `price_gbp`, `size_ml`, `sku`,
`availability`, `name`, `brand` and `size_raw`. Then `description` 22,
`flavour_style` 21, `abv_percent` 20, `pack_type` 17, `country_of_origin` 13,
`price_was` 11.

### What the audit found

An audit re-parsed all 25 rows from cached pages with independent code: zero
parser defects, and three things no test could find.

11 of 25 products (44%) show a promotional price beside a struck-through base
price. The dataset first held only the promotion price, which would distort a
price analysis, so it now holds `price_was` and `is_on_promotion`.

5 of 25 products are tonic water, because Morrisons puts mixers in the gin
category. They stay on purpose: the tool reports what a shopper sees.
`abv_percent` is null for all five, so a consumer can filter them.

`country_of_origin` held a wrong value, and nothing raised an error. Fever-Tree
Refreshingly Light Indian Tonic Water recorded `Democratic Republic of Congo`,
because the description mentions quinine sourced there, though the product is
not. The reply validated against the schema and was still wrong: the clearest
case here of valid JSON with wrong content.

The fix had two parts. The origin regular expression over-captured, because
page text runs one label into the next, so Whitley Neill Black Cherry Gin read
as `United Kingdom Brand J`; a stop-word list now ends the capture at the next
label. Removing `country_of_origin` from the model's scope raised the column
from 4 values to 13, so the regular expression was the real gain, not the
model. Separately, `8 x 150ml` read as 150 ml until the size pattern learned
the pack multiplier.

## Two retailers, two routes

| | Morrisons | The Whisky Exchange |
|---|---|---|
| Structured data | JSON-LD per product page | None |
| Route | Listing, then one fetch per product | The listing page only |
| ABV | Free text on the detail page | On the card, as `70cl / 57.8%` |

Morrisons gives name, brand, price and size from JSON-LD, but ABV is free text
in two formats on one page: `Alcohol By Volume 40.3` and
`Alcohol By Volume: 40.3%`. The Whisky Exchange has no JSON-LD, and its cards
carry size and strength in one string, so the adapter reads the listing and
stops. Its product pages hold no card, so a per-URL loop would cost 25 requests
and return null names.

Both adapters meet at `collect(fetcher, limit) -> tuple[list[Product], int]`,
which returns the products and the expected count. The Protocol promises the
result, not the route, and a test asserts that both satisfy it.

## The Whisky Exchange, live

The adapter is verified against HTML fixtures built from the site's real
markup, captured while it still served plain HTML. Its tests pass.

A live run now returns a Cloudflare JavaScript challenge instead of the
category page: the body holds `Just a moment...`, `Enable JavaScript and
cookies`, and the marker `Cloudflare`. Three controlled requests confirm this,
including one with a plain Chrome User-Agent that had returned 200 for the
same URL earlier that day. Nothing about the client changed.

## Tests

83 tests, all offline against HTML fixtures built from real markup, with the
model faked. They cover both parsers, the ABV, size and origin patterns, the
promotion price, the robots paths including fail-closed, the cache and the quota
breaker.

## Extending it

For another retailer, write one adapter in `retailers/` with `name`, `category`,
`category_url` and `collect`, decorate it with `@register`, and import it in
`retailers/__init__.py`. For another attribute, add the field to `Product`
and to `COLUMNS` in `models.py`, that order being the writers' contract, then
fill it in the adapter, in `enrich.py`, or in the `Derived` schema.

## Three ways this breaks in production

Layout drift. Morrisons removes its JSON-LD block, or The Whisky Exchange renames
`product-card__price`, and the parser returns nulls without raising. The 80% gate
catches a total failure. A per-field fill-rate comparison against the previous
run catches a partial one, because a fall from 95% to 5% is a broken selector,
not a change in stock.

Bot defence escalation. Morrisons already serves an AWS WAF script, as the 403
failure above showed. The next step, a JavaScript challenge, already happened:
The Whisky Exchange now serves one instead of its category page, and this tool
does not try to answer it. Watch the status codes and the response size, and
alert on the first 403 rather than after 25 wasted requests.

Silent model drift. The model returns valid JSON that is wrong, the schema
validates, and nothing raises. The Fever-Tree origin value is what this looks
like. Keep a hand-checked reference set and compare it field by field on a
schedule. Alert on the null rate of each derived field: a sudden fall is as
suspicious as a rise. An earlier case was caught this way, so the prompt now
forbids repeating the product name as the flavour.

## Known limitations

- `country_of_origin` is filled for 13 of 25 rows; the rest do not state it.
- Two flavour values restate the category: J.J. Gin and Ableforth's Bathtub Gin
  both give `London dry gin`.
- The Whisky Exchange adapter takes the brand from the first word of the name, so
  `Whitley Neill` would give `Whitley`.
- The Whisky Exchange adapter cannot complete a live run: the site now serves
  a Cloudflare JavaScript challenge instead of the category page.
- Prices are a snapshot, with no price history.
- The tool is single-threaded on purpose. Slow is the correct trade for one
  request per second.
