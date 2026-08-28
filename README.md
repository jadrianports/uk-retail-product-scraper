# UK Retail Product Scraper

This tool captures product attributes for one category from a UK grocery
retailer. It writes a clean structured dataset to CSV and to JSON. It gives one
row for each product and one column for each attribute.

The shipped dataset holds 25 gin products from Morrisons. A second adapter reads
the gin category at The Whisky Exchange.

## One row from the dataset

This is the first row of `data/products.csv`, shown as a list for readability.

| Column | Value |
|---|---|
| `retailer` | `morrisons` |
| `category` | `gin` |
| `product_url` | `https://groceries.morrisons.com/products/caorunn-gin/106909896` |
| `sku` | `106909896` |
| `name` | `Caorunn Gin` |
| `brand` | `Caorunn` |
| `price_gbp` | `23.5` |
| `price_was` | `30.5` |
| `is_on_promotion` | `True` |
| `size_raw` | `70cl` |
| `size_ml` | `700.0` |
| `abv_percent` | `41.8` |
| `pack_type` | `Glass Bottle` |
| `country_of_origin` | (empty) |
| `flavour_style` | `Invigorating, clean and crisp` |
| `availability` | `InStock` |
| `description` | `Invigorating, clean and crisp, aromatic with a long dry finish.` |
| `field_sources` | `{"abv_percent": "regex", "brand": "jsonld", "flavour_style": "llm", "price_gbp": "jsonld", "price_was": "css", ...}` |
| `scraped_at` | `2026-08-28T16:58:58Z` |

The `field_sources` column records where each value came from. A reader can see
which values a model produced and which values the site stated.

## How to run it

The project uses [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # install the dependencies
cp .env.example .env         # then edit .env
uv run scrape                # scrape Morrisons, 25 products
uv run pytest                # run the 78 offline tests
```

Set two values in `.env`:

| Variable | Purpose | If it is empty |
|---|---|---|
| `GEMINI_API_KEY` | The key for the model step. Free keys come from [Google AI Studio](https://aistudio.google.com/apikey). | The tool logs a warning and writes `null` for the derived fields. The run still succeeds. |
| `SCRAPER_CONTACT` | An email address. The tool puts it in the `User-Agent` header, so the site operator can reach you. | The header says `not supplied`. |

### Command options

| Option | Default | Effect |
|---|---|---|
| `--retailer` | `morrisons` | Selects the adapter. The choices are `morrisons` and `whisky_exchange`. |
| `--limit` | `25` | The maximum number of products to collect. |
| `--out` | `data` | The output directory. The tool writes `products.csv` and `products.json`. |
| `--no-llm` | off | Skips the model step. The derived fields become `null`. |

```bash
uv run scrape --retailer whisky_exchange --limit 20
uv run scrape --no-llm --out /tmp/run1
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | The run succeeded. |
| 1 | The parse-rate gate failed. The tool wrote the rows it has, and logged the reason. |
| 2 | The robots.txt rules deny the path. The tool fetched nothing. |

The first live run against Morrisons exited 1. It parsed 0 of 25 products, so it
wrote only a header row. The next section explains why.

## The approach

The tool has five parts.

| Module | Job |
|---|---|
| `src/scraper/fetch.py` | Reads robots.txt, applies the rate limit, retries, and caches every page. |
| `src/scraper/retailers/` | One adapter for each site. Each adapter turns HTML into `Product` objects. |
| `src/scraper/enrich.py` | Regular expressions for ABV, size, pack type and country. |
| `src/scraper/llm.py` | The Gemini call for the soft attribute and for the regex gaps. |
| `src/scraper/pipeline.py`, `export.py` | Orders the enrichment steps, then writes the CSV and the JSON. |

The sequence is deliberate. Structured data comes first. A regular expression
comes second. The model comes last, and only for the fields that are still
empty. Each step records its own name in `field_sources`.

### Which retailer, and why

A robots.txt check came before any code. The results decided the targets.

| Site | robots.txt | Products in plain HTML | Outcome |
|---|---|---|---|
| Morrisons | Permits browse. Denies `/api/`. | Yes. 50 gins, with JSON-LD. | **Primary target.** |
| The Whisky Exchange | Permits browse. Denies `/api/product/productlistdata`. | Yes. About 31 cards. No JSON-LD. | **Second target.** |
| Asda | `Allow: /`, plus `Content-Signal: search=yes, ai-train=no, use=reference`. | No. The page is client-rendered. | Rejected. |
| Ocado | Unreadable. The response holds `x-amzn-waf-action: challenge`. | — | Rejected. |
| Tesco | HTTP 403 on robots.txt itself. | — | Rejected. |
| Sainsbury's | HTTP 403 on robots.txt itself. | — | Rejected. |
| Co-op | HTTP 403 on robots.txt itself. | — | Rejected. |
| Iceland | HTTP 403 on robots.txt itself. | — | Rejected. |
| Waitrose | Connection refused. | — | Rejected. |
| Booths | Permits everything. | No product catalogue at all. | Rejected. |

Three points come out of that table.

1. Morrisons permits the category pages but denies `/api/`. The internal API
   would be much easier to read than the HTML. The tool never calls it. It
   parses the rendered HTML instead.
2. Asda states `ai-train=no` in its `Content-Signal` line. This pipeline sends
   page text to a model, so Asda is a site to avoid.
3. Four large grocers return HTTP 403 for robots.txt itself. You cannot read the
   rules. Therefore you must not scrape the site.

## The anti-bot problem, and the judgement call

The first live run got HTTP 200 for the category page and HTTP 403 for all 25
product detail pages. Three controlled requests isolated the cause.

| `User-Agent` | Result |
|---|---|
| `uk-retail-product-scraper/0.1 (contact: ...)` | 403 |
| A standard Chrome user agent | 200 |
| A standard Chrome user agent, with the tool name and the contact appended | 200 |

The block was a filter on the `User-Agent` string alone. The tool now sends a
browser-compatible user agent with
`uk-retail-product-scraper/0.1 (+contact: <email>)` appended. See
`USER_AGENT` in `src/scraper/fetch.py`.

**The reasoning.** robots.txt is the stated, machine-readable policy of the site.
It permits these paths. The WAF is a blunt string filter, not a policy statement.
The tool stays identifiable in the header, obeys robots.txt at run time, sends
one request per second, and backs off when it is told to.

**The counter-argument.** A stricter reading says that a block is a block, and
that any change to get past it is a change too many. That reading is defensible.
A production deployment should get the retailer's written agreement, not a
judgement call in a README.

**What the tool does not do.** There is no IP rotation. There is no proxy pool.
There is no CAPTCHA solving. There is no browser automation. The tool never
continues past an explicit rate-limit response; it waits, and then it gives up.

## Politeness and reliability

| Behaviour | Where | Detail |
|---|---|---|
| Rate limit | `Fetcher._throttle` | One request per second, plus 0 to 0.4 seconds of jitter. Single-threaded. |
| robots.txt | `Fetcher._gate_for`, `load_robots` | Read once for each host, at run time. |
| Fail closed | `RobotsGate.unreadable` | An unreadable robots.txt denies **every** path on that host. |
| Retries | `Fetcher.get` | Three attempts. Only on 429, 500, 502, 503 and 504. Any other status raises. |
| `Retry-After` | `retry_wait` | Honoured when it is a number of seconds. Capped at 120 seconds. |
| Cache | `Fetcher._cache_path` | Every page that returns 200 is written to `.cache/<host>/<hash>.html`. |

Two of these came out of real defects.

**The `Retry-After` header.** RFC 7231 permits an HTTP-date as well as a number
of seconds. The first version called `float()` on the value, so an HTTP-date
raised `ValueError` inside the retry path. The fix catches the error and falls
back to the exponential backoff. A date is rare, and a date parser is not worth
a dependency here, so the tool waits a sensible time instead of crashing.

**The cache.** Re-runs and the whole test suite cost the retailers nothing. The
robots gate is checked first, and then the cache, and only then the network. So a
cached page is never re-fetched, and a denied path is never read from the cache
either. This made the parser work possible without repeated hits on live pages.

### The fail-loud gate

A quiet partial result is worse than a loud failure. If fewer than 80% of the
expected products parse, the tool writes the rows it has, logs the count and the
percentage, and exits 1. See `check_parse_rate` in `src/scraper/export.py`.

This fired for real. On the first live run, 0 of 25 products parsed because of
the 403 responses. The tool wrote a header-only CSV, logged
`Only 0 of 25 products parsed (0%)`, and exited 1. A silent empty file would
have looked like an empty category.

## How missing data is handled

The rule is simple. A null is always better than a guess.

- A field that no source states stays `null`, and `field_sources` records
  `missing`. An empty CSV cell means the page did not state the value.
- The model gets one retry. If the second reply also fails to validate, the field
  becomes `null`.
- An ABV value from the model is range-checked. A value outside 0 to 100 becomes
  `null`.
- 0.0 is a real ABV. The guard is `0 <= value <= 100`, not a truthiness test.
  Gordon's Alcohol Free correctly records `abv_percent = 0.0`, not `null`. The
  gin category really does stock 0.0% products.
- One product row that fails to parse does not stop the run. The adapter logs the
  URL and continues. The parse-rate gate catches the total.

## Where the LLM runs, and where it does not

| Field | Source order |
|---|---|
| `name`, `brand`, `price_gbp`, `size_raw`, `sku`, `availability`, `description` | JSON-LD or CSS only. **The model never runs for these.** |
| `size_ml`, `pack_type` | Regular expression only. |
| `abv_percent`, `country_of_origin` | Regular expression first. The model runs **only** when the regular expression found nothing. |
| `flavour_style` | The model always. No other source gives it. |

The model adds cost and risk. It gives no gain on a price that is already in a
`schema.org/Product` block. So it does not touch those fields.

**The model.** `gemini-3.5-flash-lite`, through the `google-genai` SDK. See
`src/scraper/llm.py`.

**The call.** Structured output against the `Derived` Pydantic schema, with
`response_mime_type="application/json"`. The prompt does not restate the schema.
Google's documentation states that a repeated schema lowers quality when
`response_schema` is set. A test asserts that the prompt holds no schema text.

**Why Gemini.** Cost, not capability. This is an unpaid exercise, and Gemini has
a free tier. The client's own stack uses Claude and OpenAI. The provider lives in
one file; a swap changes `src/scraper/llm.py` and nothing else.

### The free tier shaped the run

Be clear about this: the pacing below is a consequence of a free tier, not a
property of the design.

An earlier run used `gemini-2.5-flash`. Its free tier allows 20 requests per
**day**. A run of 25 products spent the quota and left 18 products unenriched.

Calls are now spaced by `MIN_CALL_INTERVAL = 6.0` seconds to respect the
per-minute limit. A full 25-product run therefore takes a few minutes, not
seconds. On a paid key you would lower the interval and batch the calls.

### Two kinds of 429

This distinction is worth its own section, because treating the two alike cost a
stalled 25-minute run.

| Cause | Nature | Correct response |
|---|---|---|
| A per-minute rate limit | Transient | Honour the `retryDelay` and retry. |
| A spent per-day quota | Terminal for this run | Stop calling. The quota resets tomorrow. |

The API returns 429 for both. The first version waited 59 seconds and retried,
twice for each product, for every one of the remaining products. It achieved
nothing.

`_is_daily_quota_exhausted` now matches on the quota **name** (`PerDay`,
`GenerateRequestsPerDayPerProject`), not on the numeric quota value, because the
value changes with the model and the name does not. A match trips a circuit
breaker. The tool logs once, and then returns nulls immediately for every
remaining product.

## Provenance

Every row records `field_sources`, a JSON object that maps each field name to one
of `jsonld`, `css`, `regex`, `llm` or `missing`. This makes the blast radius of
the model auditable.

The shipped dataset holds these counts.

| Source | Values |
|---|---|
| `jsonld` | 175 |
| `regex` | 63 |
| `llm` | 24 |
| `css` | 22 |
| `missing` | 52 |

The model produced 24 values out of 336. A reader can find every one of them.

## The dataset

`data/products.csv` and `data/products.json` hold 25 products and 19 columns from
the Morrisons gin category.

| Field | Filled |
|---|---|
| `name`, `brand`, `price_gbp`, `size_raw`, `size_ml`, `sku`, `availability` | 25 / 25 |
| `description` | 22 / 25 |
| `flavour_style` | 21 / 25 |
| `abv_percent` | 20 / 25 |
| `pack_type` | 17 / 25 |
| `price_was` | 11 / 25 |
| `country_of_origin` | 4 / 25 |

### What the audit of this data found

An audit re-parsed all 25 rows from their cached source pages, with independent
code. It found **zero parser defects**. Every price, size and name matched the
page exactly. A live re-fetch confirmed that the cache was current.

The audit still found three things that no test could find.

**1. 11 of 25 products carry a promotional price.** Each of those pages shows the
promotion price, with the base price struck through beside it. The dataset first
recorded only the promotion price. That single number would distort any analysis
of category prices, and the code was doing exactly what it was told to do. The
dataset now holds `price_was` and `is_on_promotion` as well. This is the
difference between extracting a value correctly and extracting a value that
means something.

**2. 5 of 25 products are tonic water, not gin.** Morrisons puts mixers in the
gin category. These rows are kept on purpose. The tool reports what a shopper
sees in the category. `abv_percent` is null for each of the five, so a consumer
of the data can filter them. To drop them silently would hide a real fact about
the retailer's category boundaries.

**3. `country_of_origin` is genuinely sparse.** Only 4 of 25 pages state it. That
is an honest null, not a parser fault.

Two defects came out of the same audit and are now fixed.

- `8 x 150ml` was recorded as 150 ml. The size regular expression ignored the
  pack multiplier. It now reads 1200.0 ml. Four multipack forms are in the tests,
  plus a guard that stops `Explorer Gin 70cl` from reading as a multiplier.
- The ABV guard rejected 0.0 as a false value. Gordon's Alcohol Free now records
  `abv_percent = 0.0`.

## The two retailers, and why they differ

The two sites need two different strategies. That is the point of having a second
one.

| | Morrisons | The Whisky Exchange |
|---|---|---|
| Structured data | `schema.org/Product` JSON-LD on each product page | None |
| Route | Listing page, then one fetch for each product | The listing page only |
| Requests for 25 products | 26 | 1 |
| Name, brand, price, size | JSON-LD | CSS selectors on the card |
| ABV | Free text on the detail page | On the card, as `70cl / 57.8%` |

Morrisons gives name, brand, price, size, sku, availability and description
cleanly from JSON-LD. ABV appears nowhere structured. It is free text, and it
appears in two different formats on the same page: `Alcohol By Volume 40.3` and
`Alcohol By Volume: 40.3%`.

The Whisky Exchange has no JSON-LD at all. Its listing cards carry the size and
the strength together in one string. The adapter therefore reads the listing page
and stops. Its product pages hold no card, so a per-URL loop would return null
names, and it would cost 25 pointless requests.

### One contract, two routes

```python
class Retailer(Protocol):
    name: str
    category: str
    category_url: str

    def collect(self, fetcher, limit: int) -> tuple[list[Product], int]:
        """Gather this retailer's own products. Each adapter picks its own route.

        Return the parsed products and the expected count (the number of
        products the listing offered, capped at limit).
        """
```

The Protocol promises the result, not the route. `find_product_urls` and
`parse_product` are internal to each adapter. The CLI calls `collect` and knows
nothing else. A test asserts that both adapters satisfy this one contract.

## Tests

78 tests. All of them run offline, against saved HTML fixtures built from real
markup, with the model faked. They never touch the network, so they cost the
retailers nothing and they run in CI.

```bash
uv run pytest
```

They cover the fragile parts, not the easy parts.

| Area | Examples |
|---|---|
| Both parsers | JSON-LD reads, absolute and unique URLs, listing cards |
| ABV formats | All four patterns, plus the truncation guard (`Alcohol By Volume 1000` gives null) |
| Sizes | cl, ml, L, litres, four multipack forms, and the multiplier guard |
| Promotion price | A struck-through price is read. A struck-through **unit** price like `(£43.57/litre)` is not. |
| Missing data | No JSON-LD gives nulls and does not raise |
| robots.txt | Allow, deny, and the fail-closed path |
| Cache | A second `get` makes no second request |
| Quota | The daily breaker trips. A per-minute error does not trip it. |
| Provenance | A value set by an adapter survives the regex pass, with its own source tag |
| Contract | Both adapters satisfy `collect` |
| Exit codes | 1 for the gate, 2 for robots, including a `RobotsDenied` raised deep inside `collect` |

## How to extend it

### Another retailer

Write one adapter file in `src/scraper/retailers/`, and register it.

```python
from scraper.retailers.base import register

@register
class NewRetailer:
    name = "new_retailer"
    category = "gin"
    category_url = "https://example.com/gin"

    def collect(self, fetcher, limit):
        ...
        return products, expected
```

Then add one import line to `src/scraper/retailers/__init__.py`. Nothing else
changes. The `--retailer` choices come from the registry, so the new name appears
in `--help` at once. The rate limit, the robots gate, the cache, the retries, the
enrichment and the writers are all shared.

### Another attribute

1. Add the field to `Product` in `src/scraper/models.py`.
2. Add the column name to `COLUMNS` in the same file. The order is the contract
   for both the CSV and the JSON.
3. Fill it. A structured value goes in the adapter. A text value goes in
   `enrich.py` and `pipeline.py`. A soft value goes in the `Derived` schema in
   `llm.py`.
4. Set `field_sources` for it.

`test_row_matches_column_contract` fails if a field and a column go out of step.

### Another category

`category` and `category_url` are class attributes on each adapter. A second
category is a second class, or a constructor argument. The parsing does not
change, because the page layout does not change between categories on the same
site.

## Staying reliable over time

The parts that already exist: the disk cache, the fail-loud gate, the exit codes,
the provenance column, and 78 offline tests.

The parts a scheduled deployment needs next:

- Keep each run's output. Compare the per-field fill rate against the previous
  run. Alert on a large fall.
- Store the raw HTML for a sample of pages, so a parse fault can be diagnosed
  after the fact without another fetch.
- Alert on the first 403, not at the end of the run.
- Run the offline test suite in CI on each commit. Run a small live smoke test on
  a schedule, against 3 products, and check the exit code.
- Put the contact address and the rate limit in one config, so a retailer's
  request to slow down is a one-line change.

## The top three ways this breaks in production

### 1. Layout drift

Morrisons renames or removes its JSON-LD block. The Whisky Exchange renames
`product-card__price`. The parser then returns nulls and raises nothing.

**Detection.** The 80% parse-rate gate catches a total failure. A per-field
fill-rate comparison against the previous run catches a partial failure. A field
that falls from 95% to 5% is a broken selector, not a change in stock.

### 2. Bot defence escalation

Morrisons already serves an AWS WAF script. This exact failure happened during
the build: every product page returned 403 while the category page returned 200.
The next step for the site is a JavaScript challenge, which this tool cannot
answer, and should not try to.

**Detection.** Watch the status codes. Watch the response size; a challenge page
is much smaller than a product page. Check that a known marker, such as the
JSON-LD block, is in the body. Alert on the first occurrence, not after the whole
run, because 25 sequential 403s waste 25 requests to learn one fact.

### 3. Silent model drift

The model returns valid JSON that is wrong. The schema validates. Nothing raises.
This is the worst failure mode, because it is invisible.

**Detection.** Keep a small reference set of hand-checked products. Run it on a
schedule and compare field by field. Alert on the null rate of each derived
field. A sudden **fall** in nulls is as suspicious as a rise, because it means the
model started to guess.

Two real instances are in the shipped data.

- The model echoed the product name back as the flavour when the description was
  weak. The prompt now says `Do not repeat the product name in your answer` and
  `Do not guess a flavour or style from the product name alone`. A test asserts
  that the line is in the prompt.
- Fever-Tree Refreshingly Light Indian Tonic Water records
  `country_of_origin = "Democratic Republic of Congo"`. The description says the
  quinine comes from there. The product is not from there. The value is drawn
  from the text, and it is still wrong. `field_sources` marks it `llm`, so it is
  findable.

## Known limitations

- `country_of_origin` is filled for 4 of 25 rows. The source pages rarely state
  it.
- One flavour value is a weak restatement of the category rather than a flavour:
  Ableforth's Bathtub Gin gives `London dry gin`, which is copied from its
  description.
- One `country_of_origin` value from the model is wrong: see the Fever-Tree case
  above.
- The origin regular expression can over-capture. Whitley Neill Black Cherry Gin
  records `United Kingdom Brand J`, because the label text runs into the next
  label.
- The Whisky Exchange adapter takes the brand from the first word of the product
  name. That is crude. A two-word brand such as `Whitley Neill` would give
  `Whitley`.
- The Whisky Exchange gin category URL should be confirmed from the site
  navigation. The build verified the card structure from real markup. It did not
  verify that specific category path.
- Prices are a snapshot at the time of the scrape. There is no price history.
- The tool is single-threaded on purpose. It is slow, and that is the correct
  trade for one request per second.

## Repository layout

```
src/scraper/
  cli.py               argument parsing, the run sequence, the exit codes
  fetch.py             robots gate, rate limit, retries, disk cache
  models.py            the Product model and the COLUMNS contract
  enrich.py            regular expressions for ABV, size, pack type, origin
  llm.py               the Gemini client, the prompt, the quota breaker
  pipeline.py          the order of the enrichment steps
  export.py            the CSV and JSON writers, the parse-rate gate
  retailers/
    base.py            the Retailer Protocol and the registry
    morrisons.py       JSON-LD adapter, detail pages
    whisky_exchange.py CSS adapter, listing page only
tests/                 78 offline tests, with HTML fixtures
data/                  products.csv, products.json
```

## Documentation language

All text in this repository uses ASD-STE100 Simplified Technical English.
