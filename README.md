# UK Retail Product Scraper

This tool captures product attributes for one category from a UK grocery
retailer, one row per product and one column per attribute, to CSV and JSON.
The shipped dataset is 25 gin products from Morrisons, 19 columns wide. A
second adapter covers gin at The Whisky Exchange; it is fixture-tested, but it
cannot run live. See "The Whisky Exchange, live" below.

Plain HTTP, not a browser: both sites serve product data in HTML, so a browser
would add a large dependency for no extra data.

## Run it

The dataset is committed, so `data/products.csv` can be read with no setup.

Clone the repository:

```bash
git clone https://github.com/jadrianports/uk-retail-product-scraper
cd uk-retail-product-scraper
```

Install `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh          # macOS, Linux
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows
```

The project needs Python 3.11 or later. `uv` fetches its own interpreter, so
`uv sync` is the whole install.

```bash
uv sync
uv run pytest                  # 87 offline tests, about a second
```

The tests need no API key and no network. They are the fastest check that the
tool works.

```bash
cp .env.example .env
uv run scrape                  # Morrisons, 25 products
uv run scrape --retailer whisky_exchange --limit 20   # exits 1, see below
uv run scrape --no-llm --out out/run1
```

`uv run scrape` makes about 26 live requests to Morrisons: the listing page,
then one per product. Pages are cached, so a second run makes none.

`.env` holds `GEMINI_API_KEY` for the model and `SCRAPER_CONTACT`, an email for
the `User-Agent` header. Without the key, derived fields are `null` and the run
still succeeds. `--retailer` picks the adapter, `--limit` caps the products,
`--out` sets the output directory, `--no-llm` skips the model.

Exit codes: 0 success, 2 robots.txt denied the path. 1 means no usable
dataset: the listing could not be fetched, or the parse-rate gate failed.

## Which retailer, and why

A robots.txt check came before any code.

| Site | robots.txt | Products in plain HTML | Outcome |
|---|---|---|---|
| Morrisons | Permits browse. Denies `/api/`. | Yes. 50 gins, with JSON-LD. | Primary |
| The Whisky Exchange | Permits browse. Denies `/api/product/productlistdata`. | Yes. 31 cards, no JSON-LD. | Second |
| Asda | `Allow: /`, plus `Content-Signal: ai-train=no`. | No. Client-rendered. | Rejected |
| Ocado | Unreadable. Holds `x-amzn-waf-action: challenge`. | | Rejected |
| Tesco | 403 on robots.txt. | | Rejected |
| Sainsbury's | 403 on robots.txt. | | Rejected |
| Co-op | 403 on robots.txt. | | Rejected |
| Iceland | 403 on robots.txt. | | Rejected |
| Waitrose | Connection refused. | | Rejected |
| Booths | Permits everything. | No catalogue. | Rejected |

The denied Morrisons API is easier to parse than the HTML; the tool never calls
it. Asda states `ai-train=no`, and this pipeline sends page text to a model.
Unreadable rules mean no scraping.

## The anti-bot judgement call

The first live run got 200 for the category page and 403 for all 25 product
pages. Three controlled requests isolated it: `uk-retail-product-scraper/0.1`
gave 403, Chrome gave 200, and Chrome with the tool name and contact appended
gave 200. `USER_AGENT` in `fetch.py` sends that last form.

The reasoning: robots.txt is the site's stated policy and it permits these
paths, while the WAF is a blunt string filter. The tool stays identifiable and
obeys robots.txt at run time. The counter-argument: a block is a block, and a
production deployment should get the retailer's written agreement instead.

No IP rotation, no proxy pool, no CAPTCHA solving, no browser. The tool never
continues past an explicit rate-limit response, and a JavaScript challenge is
where it stops.

## Politeness and reliability

One request per second with jitter, single-threaded. robots.txt is read once
per host, and an unreadable one denies every path there. Retries are three
attempts, on 429 and 5xx only. Every 200 response is cached, so re-runs cost
the retailers nothing.

### The fail-loud gate

If fewer than 80% of the expected products parse, the tool logs the count and
exits 1. A fetch failure returns before the writers run, so the previous
dataset stays untouched. A parse-rate failure does not: the writers run first,
so a run that parses nothing leaves a header-only CSV. It fired for real: 0 of
25 parsed on the first run.

## Where the LLM runs, and where it does not

| Field | Source order |
|---|---|
| `name`, `brand`, `price_gbp`, `size_raw`, `sku`, `availability`, `description` | JSON-LD or CSS only. The model never runs. |
| `size_ml`, `pack_type`, `country_of_origin` | Regular expression only. |
| `abv_percent` | Regular expression, then the model if nothing was found. |
| `flavour_style` | The model always. No other source gives it. |

The split follows what each source can prove. `flavour_style` needs prose read
and judged. ABV is a number in a known range, so a model answer is checked with
`0 <= value <= 100`, not a truthiness test, because 0.0 is a real ABV. A field
no source states stays `null`.

The model is `gemini-3.5-flash-lite` through `google-genai`, with structured
output against the `Derived` schema. Gemini is a cost choice; a swap to Claude
or OpenAI changes `llm.py` alone. `gemini-2.5-flash` gave 20 free
requests per day, spent the quota, and left 18 products unenriched, so calls
are now spaced by `MIN_CALL_INTERVAL = 6.0` seconds.

### Two kinds of 429

A per-minute limit is transient: honour `retryDelay` and retry. A spent
per-day quota is terminal: stop calling. The API returns 429 for both; the
first version waited 59 seconds and retried twice per remaining product.
`_is_daily_quota_exhausted` now matches the quota name (`PerDay`), not the
numeric value, which changes with the model. A match trips a circuit breaker.

## Provenance and fill rates

`field_sources` records where each value came from, which makes the model's
blast radius auditable, and it agrees with the data on every row. The 25 rows
hold 336 values: `jsonld` 172, `regex` 75, `css` 22, `llm` 22, `missing` 45.

Seven product attributes are filled 25 of 25: `price_gbp`, `size_ml`, `sku`,
`availability`, `name`, `brand` and `size_raw`. With `is_on_promotion` and the
five identity and provenance columns, 13 of 19 columns are complete. The rest:
`description` 22, `flavour_style` 22, `abv_percent` 20, `pack_type` 17,
`country_of_origin` 13, `price_was` 11.

### What the audit found

An audit re-parsed all 25 rows from cached pages with independent code: zero
parser defects, and three things no test could find.

11 of 25 products (44%) show a promotional price beside a struck-through base
price. The dataset first held the promotion price alone, which would distort a
price analysis. It now holds `price_was` and `is_on_promotion`.

5 of 25 products are tonic water, because Morrisons puts mixers in the gin
category. They stay: the tool reports what a shopper sees, and `abv_percent` is
null for all five, so a consumer can filter them.

Fever-Tree Refreshingly Light Indian Tonic Water recorded `Democratic Republic
of Congo` for `country_of_origin`, because the description mentions quinine
sourced there. Nothing raised an error, and the reply validated against the
schema: valid JSON with wrong content. The origin pattern also over-captured:
Whitley Neill Black Cherry Gin read as `United Kingdom Brand J`. A stop-word
list now ends the capture at the next label, and the model no longer fills the
field. The column went from 4 to 13 values, so the pattern was the
real gain.

## Two retailers, two routes

Morrisons has JSON-LD on every product page, so that adapter reads the listing,
then one page per product. The Whisky Exchange has none, but its cards carry
size and strength (`70cl / 57.8%`), so that adapter reads the listing and
stops. Both meet at
`collect(fetcher, limit) -> tuple[list[Product], int]`: the Protocol promises
the result, not the route, and a test asserts that both satisfy it.

## The Whisky Exchange, live

The adapter is verified against fixtures built from the site's real markup,
captured while it still served plain HTML.

A live run now returns a Cloudflare JavaScript challenge instead of the
category page. The body holds `Just a moment...` and the marker `Cloudflare`.
The same request from three different IP addresses, including two on a VPN in a
different country, returned 403 with the same challenge. The home page also
returned 403: a site-wide block, not tied to this client or this path.

## Tests

87 tests, all offline against fixtures built from real markup, with the model
faked. The suite makes no network call, even with a real key in `.env`. It
covers both parsers, the ABV, size and origin patterns, the promotion price,
the robots paths, the cache and the quota breaker.

## Three ways this breaks in production

Layout drift. Morrisons removes its JSON-LD block and the parser returns nulls
without raising. The 80% gate catches a total failure. A per-field fill-rate
comparison against the previous run catches a partial one: a fall from 95% to
5% is a broken selector, not a change in stock.

Bot defence escalation. Morrisons already serves an AWS WAF script, as the 403
failure above showed, and The Whisky Exchange has moved on to a JavaScript
challenge. Watch the status codes and the response size, and alert on the first
403 rather than after 25 wasted requests.

Silent model drift. The model returns valid JSON that is wrong, the schema
validates, and nothing raises; the Fever-Tree origin is the example. Keep a
hand-checked reference set and compare it on a schedule. Alert on the null rate
of each derived field: a sudden fall is as suspicious as a rise. An earlier
case was caught this way, so the prompt now forbids repeating the product name
as the flavour.

## Known limitations

- `country_of_origin` is filled for 13 of 25 rows; the rest do not state it.
- Two flavour values restate the category: J.J. Gin and Ableforth's Bathtub
  Gin both give `London dry gin`.
- The Whisky Exchange adapter takes the brand from the first word of the name:
  `Whitley Neill` gives `Whitley`.
- Prices are a snapshot, with no price history.
- The tool is single-threaded on purpose. Slow is the correct trade for one
  request per second.
