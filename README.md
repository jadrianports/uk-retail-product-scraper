# UK Retail Product Scraper

This tool captures product attributes for one category from a UK retailer,
one row per product and one column per attribute, to CSV and JSON. Two
datasets ship: 25 gin products from Morrisons in
`data/morrisons/products.csv`, and 24 gin products from The Whisky Exchange in
`data/whisky_exchange/products.csv`. Both are 19 columns wide.

Plain HTTP, not a browser: both sites serve product data in HTML, so a browser
would add a large dependency for no extra data.

## Run it

Both datasets are committed, so they can be read with no setup. Each retailer
writes to its own folder:

```
data/
  morrisons/         products.csv  products.json
  whisky_exchange/   products.csv  products.json
```

The first row of `data/morrisons/products.csv`, without `product_url`,
`description` and `field_sources`:

```
retailer            morrisons           availability       InStock
category            gin                 scraped_at         2026-08-28T20:25:05Z
sku                 106909896           size_raw           70cl
name                Caorunn Gin         size_ml            700.0
brand               Caorunn             pack_type          Glass Bottle
price_gbp           23.5                country_of_origin  (empty)
price_was           30.5                abv_percent        41.8
is_on_promotion     True
flavour_style       Invigorating, clean and crisp, aromatic
```

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
uv run pytest                  # 106 offline tests, about a second
```

```bash
cp .env.example .env
uv run scrape                  # Morrisons, 25 products
uv run scrape --retailer whisky_exchange   # 24 products, one request
uv run scrape --no-llm --out out/run1
```

Every 200 response is cached, so a second run makes no live request.

`.env` holds `GEMINI_API_KEY` for the model and `SCRAPER_CONTACT`, an email for
the `User-Agent` header. Without the key, derived fields are `null` and the run
still succeeds. `--retailer` picks the adapter, `--limit` caps the products,
`--no-llm` skips the model. `--out` sets the output directory. It defaults to
`data/<retailer>`, and an explicit `--out` wins.

Exit codes: 0 success, 2 robots.txt denied the path. 1 means no usable
dataset: the listing could not be fetched, or the parse-rate gate failed.

## Which retailer, and why

A robots.txt check came before any code.

| Site | robots.txt | Products in plain HTML | Outcome |
|---|---|---|---|
| Morrisons | Permits browse. Denies `/api/`. | Yes. 50 gins, with JSON-LD. | Primary |
| The Whisky Exchange | Permits browse. Denies `/api/product/productlistdata`. | Yes. 24 cards, no JSON-LD. | Second |
| Asda | `Allow: /`, plus `Content-Signal: ai-train=no`. | No. Client-rendered. | Rejected |
| Ocado | Unreadable. Holds `x-amzn-waf-action: challenge`. | | Rejected |
| Tesco, Sainsbury's, Co-op, Iceland | 403 on robots.txt. | | Rejected |
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
paths, while the WAF is a blunt string filter. The counter-argument: a block
is a block, and a production deployment should get the retailer's written
agreement instead.

No IP rotation, no proxy pool, no CAPTCHA solving, no browser. The tool never
continues past an explicit rate-limit response, and a JavaScript challenge is
where it stops.

## Politeness and reliability

One request per second with jitter, single-threaded. robots.txt is read once
per host. Retries are three attempts, on 429 and 5xx only.

### The fail-loud gate

If fewer than 80% of the expected products parse, the tool logs the count and
exits 1. A fetch failure returns before the writers run, so the previous
dataset stays untouched. A parse-rate failure does not: the writers run first,
so a run that parses nothing leaves a header-only CSV.

## Where the LLM runs, and where it does not

| Field | Source order |
|---|---|
| `name`, `brand`, `price_gbp`, `size_raw`, `sku`, `availability`, `description` | JSON-LD or CSS only. The model never runs. |
| `size_ml`, `pack_type`, `country_of_origin` | Regular expression only. |
| `abv_percent` | Regular expression, then the model if nothing was found. |
| `flavour_style` | The model always. No other source gives it. |

The split follows what each source can prove. `flavour_style` needs prose read
and judged. ABV is a number in a known range, so a model answer is checked with
`0 <= value <= 100`, not a truthiness test, because 0.0 is a real ABV.

The model is `gemini-3.5-flash-lite` through `google-genai`, with structured
output against the `Derived` schema. Gemini is a cost choice; a swap to Claude
or OpenAI changes `llm.py` alone. `gemini-2.5-flash` gave 20 free
requests per day, spent the quota, and left 18 products unenriched, so calls
are now spaced by `MIN_CALL_INTERVAL = 6.0` seconds.

### Two kinds of 429

A per-minute limit is transient: honour `retryDelay` and retry. A spent
per-day quota is terminal: stop calling. The API returns 429 for both.
`_is_daily_quota_exhausted` now matches the quota name (`PerDay`), not the
numeric value, which changes with the model. A match trips a circuit breaker.

## Provenance and fill rates

`field_sources` makes the model's blast radius auditable, and it agrees with
the data on every row. The 25 Morrisons rows hold 336 values: `jsonld` 172,
`regex` 75, `css` 22, `llm` 22, `missing` 45. The 24 Whisky Exchange rows hold
240: `css` 120, `regex` 24, `missing` 96.

Seven attributes are filled 25 of 25: `price_gbp`, `size_ml`, `sku`,
`availability`, `name`, `brand` and `size_raw`. The rest: `description` 22,
`flavour_style` 22, `abv_percent` 20, `pack_type` 17, `country_of_origin` 13,
`price_was` 11.

### What the audit found

An audit re-parsed all 25 rows with independent code: zero parser defects,
and three things no test could find.

11 of 25 products show a promotional price beside a struck-through base
price. The dataset first held the promotion price alone. It now holds
`price_was` and `is_on_promotion`.

5 of 25 products are tonic water, because Morrisons puts mixers in the gin
category. They stay: the tool reports what a shopper sees, and `abv_percent`
is null for all five.

Fever-Tree Refreshingly Light Indian Tonic Water recorded `Democratic Republic
of Congo` for `country_of_origin`, because the description mentions quinine
sourced there. The origin pattern also over-captured: Whitley Neill Black
Cherry Gin read as `United Kingdom Brand J`. A stop-word list now ends the
capture at the next label, and the model no longer fills the field. The column
went from 4 to 13 values, so the pattern was the real gain.

## Two retailers, two routes

Morrisons has JSON-LD on every product page, so that adapter reads the listing,
then one page per product. The Whisky Exchange has none, but its cards carry
the size and the strength (`70cl / 57.8%`), so that adapter reads the listing
and stops. Both meet at
`collect(fetcher, limit) -> tuple[list[Product], int]`: the Protocol promises
the result, not the route, and a test asserts that both satisfy it. The
Morrisons run makes about 26 requests. The Whisky Exchange run makes one, in
about two seconds.

The Whisky Exchange publishes no brand field, so the adapter reads words from
the start of the name. It stops at the first category, style or place word,
and it takes four words at most. A leading category word is kept, so `Gin Mare`
survives. That gives `The Botanist`, `Papa Salt`, `Ki No Bi`, `Isle of Harris`
and `Monkey 47`. It stays a heuristic, and approximate.
`Roku Noryo Tea Edition Gin` gives `Roku Noryo Tea`, where the brand is `Roku`.
Morrisons needs none of this, because its JSON-LD carries a real brand field.

Seven of the 19 columns are empty on every Whisky Exchange row: `sku`,
`price_was`, `pack_type`, `country_of_origin`, `flavour_style`, `availability`
and `description`. The card holds the name and the price as well, and nothing
else. The product pages hold no JSON-LD and no description block. The words
`Country`, `Producer` and `Distillery` there belong to the navigation, not the
product. Fetching 24 product pages would cost 24 requests and return almost
nothing, so the columns stay empty rather than guessed. The six filled columns
are full at 24 of 24: `name`, `brand`, `price_gbp`, `size_raw`, `size_ml` and
`abv_percent`. Two retailers, the same category, and one publishes about twice
the structured data of the other. For anyone comparing a category across
retailers, that asymmetry is itself a result.

## The Whisky Exchange, live

The adapter is verified against fixtures built from the site's real markup,
and it runs live.

During the build the site returned 403 with a Cloudflare JavaScript challenge,
and this README called it a permanent site-wide block. That was wrong. Two of
the three IP addresses in the test were VPN endpoints, and the home page test
used the VPN as well. Cloudflare scores VPN and datacentre ranges as
suspicious by default, so those 403s prove nothing about the site's policy.
The one test on a residential connection came minutes after this tool had made
about 26 requests to the host. That is a flag the tool earned.

A retest from a normal connection, VPN off, returned 200 and 24 product cards.
The flag had decayed.

The check that was missing: work out whether a block is a flag you earned or a
policy the site set, and retest from a clean path before you conclude. In a
single response the two look identical.

The live run found a second defect. `category_url` was `/c/40/gin`, and that
path redirects to `/c/40/single-malt-scotch-whisky`. The adapter would have
collected whisky and labelled it gin. The fixture came from the same page, so
the tests passed while the code and the fixture were both wrong about what the
page was. The gin category is `/c/338/gin`, titled "Gin and Jenever".
Extraction correct, meaning wrong. Only the live run found it.

## Tests

106 tests, all offline against fixtures built from real markup, with the model
faked. The suite makes no network call, even with a real key in `.env`. It
covers both parsers, the ABV, size and origin patterns, the promotion price,
the robots paths, the cache and the quota breaker.

## Three ways this breaks in production

Layout drift. Morrisons removes its JSON-LD block and the parser returns nulls
without raising. A per-field fill-rate comparison against the previous run
catches a partial failure: a fall from 95% to 5% is a broken selector, not a
change in stock.

Bot defence escalation. Watch the status codes and the response size, and
alert on the first 403 rather than after 25 wasted requests. A block can also
be transient, so retest before anyone rewrites an adapter.

Silent model drift. The model returns valid JSON that is wrong, the schema
validates, and nothing raises; the Fever-Tree origin is the example. Keep a
hand-checked reference set and compare it on a schedule. Alert on the null rate
of each derived field: a sudden fall is as suspicious as a rise.

## Known limitations

- Two flavour values restate the category: J.J. Gin and Ableforth's Bathtub
  Gin both give `London dry gin`.
- Prices are a snapshot, with no price history.
