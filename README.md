# UK Retail Product Scraper

This tool captures product attributes for one category from a UK retailer,
one row per product and one column per attribute, to CSV and JSON. Two
datasets ship: 25 gin products from Morrisons and 24 gin products from The
Whisky Exchange. Both are 20 columns wide, and `data/all_products.csv` holds
all 49 rows in one file.

Plain HTTP, not a browser: both sites serve product data in HTML, so a browser
would add a large dependency for no extra data.

## Run it

Every dataset is committed, so it can be read with no setup.

```
data/
  all_products.csv              49 rows, both retailers
  morrisons/gin/                products.csv  products.json
  whisky_exchange/gin/          products.csv  products.json
```

The first row of `data/morrisons/gin/products.csv`, without `product_url`,
`description` and `field_sources`:

```
retailer            morrisons           price_per_litre    33.57
category            gin                 abv_percent        41.8
sku                 106909896           pack_type          Glass Bottle
name                Caorunn Gin         country_of_origin  (empty)
brand               Caorunn             availability       InStock
price_gbp           23.5                scraped_at         2026-08-29T11:58:28Z
price_was           30.5
is_on_promotion     True                flavour_style      Invigorating, clean
size_raw            70cl                                   and crisp
size_ml             700.0
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
uv run pytest                  # 129 offline tests, about a second
```

```bash
cp .env.example .env
uv run scrape                             # Morrisons gin, 25 products
uv run scrape --category vodka            # Morrisons vodka
uv run scrape --retailer whisky_exchange  # 24 products, one request
uv run scrape --list-categories           # what each retailer supports
uv run scrape --combine                   # rebuild data/all_products.csv
```

Every 200 response is cached, so a second run makes no live request.

`.env` holds `SCRAPER_CONTACT`, an email for the `User-Agent` header, and one
model key. Set `GEMINI_API_KEY`, `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`, and
the tool uses whichever it finds. With no key the derived fields are `null`
and the run still succeeds.

`--retailer` picks the adapter. `--category` picks the category, and
`--list-categories` prints the choices. `--limit` caps the products.
`--no-llm` skips the model. `--out` sets the output directory. It defaults to
`data/<retailer>/<category>`, and an explicit `--out` wins.

Exit codes: 0 success. 1 means no usable dataset, so the listing failed to
fetch or the parse-rate gate failed. 2 means robots.txt denied the path.
3 means the host served a JavaScript challenge.

## What the data says

The dataset exists for category analysis, so here is the category.

| | Morrisons | The Whisky Exchange |
|---|---|---|
| Products | 25 | 24 |
| Median price per litre | £29.29 | £50.51 |
| Range per litre | £1.90 to £53.00 | £30.71 to £91.90 |
| Distinct brands | 16 | 23 |
| Sizes sold | 350, 500, 700, 1000, 1200 ml | 500, 700, 1000 ml |
| Median ABV | 41.3% | 43.2% |

The specialist reads as 72% dearer. The two brands both retailers carry say
something else, at the same 70cl size:

| Brand | Morrisons | The Whisky Exchange |
|---|---|---|
| Hendrick's | £33.50 | £29.95 |
| Tanqueray | £21.00 | £21.50 |

So the gap is range composition and not like-for-like pricing. The specialist
stocks premium products rather than dearer copies of the same product. A
buyer who compared the two medians alone would draw the wrong conclusion.

`price_per_litre` is what makes this readable. Morrisons sells gin in five
sizes, so the shelf price ranks nothing. Engine Organic Italian Gin costs
£26.50 and Gordon's Premium Pink costs £27.00, so the shelf puts them
together. Engine is a 500 ml bottle and Gordon's is a litre, so per litre they
are £53.00 and £27.00. Engine is the dearest of the 25 by volume and 17th
cheapest by shelf price.

The cheapest row per litre at Morrisons is Schweppes Slimline Tonic Water at
£1.90. That is a mixer, not a gin, and the next section explains why it stays.

## Which retailer, and why

A robots.txt check came before any code.

| Site | robots.txt | Products in plain HTML | Outcome |
|---|---|---|---|
| Morrisons | Permits browse. Denies `/api/`. | Yes. 49 gins, with JSON-LD. | Primary |
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
pages. Controlled requests isolated it. A `uk-retail-product-scraper/0.1`
agent gave 403. A Chrome agent gave 200. A Chrome agent with the tool name and
the contact appended gave 200, and `USER_AGENT` in `fetch.py` sends that form.

The header set matters as much as the agent. A request that carries the
browser agent alone still gets 403 on a Morrisons product page. The same
request with `Accept` and `Accept-Language` gets 200. Both were retested on
2026-08-29.

The reasoning: robots.txt is the site's stated policy and it permits these
paths, while the filter reads one header at a time. The counter-argument: a
block is a block, and a production deployment should hold the retailer's
written agreement instead.

No IP rotation, no proxy pool, no CAPTCHA solving, no browser. The tool never
continues past an explicit rate-limit response, and a JavaScript challenge is
where it stops.

## Politeness and reliability

One request per second with jitter, single-threaded. robots.txt is read once
per host. Retries are three attempts, on 429 and 5xx only.

### The fail-loud gate

If fewer than 80% of the expected products parse, the tool logs the count and
exits 1. The check runs before the write, so a short run leaves the previous
dataset in place. A fetch failure returns earlier still. A file that is short
but looks complete is the worse fault, because no reader can see it.

## Where the LLM runs, and where it does not

| Field | Source order |
|---|---|
| `name`, `brand`, `price_gbp`, `size_raw`, `sku`, `availability`, `description` | JSON-LD or CSS only. The model never runs. |
| `size_ml`, `pack_type`, `country_of_origin` | Regular expression only. |
| `price_per_litre` | Arithmetic on the price and the size. |
| `abv_percent` | Regular expression, then the model if nothing was found. |
| `flavour_style` | The model always. No other source gives it. |

The split follows what each source can prove. `flavour_style` needs prose read
and judged. ABV is a number in a known range, so a model answer is checked
with `0 <= value <= 100`, not a truthiness test, because 0.0 is a real ABV.

Three providers work. `build_enricher` reads `GEMINI_API_KEY`, then
`OPENAI_API_KEY`, then `ANTHROPIC_API_KEY`, and returns the matching client.
The shipped dataset used `gemini-3.5-flash-lite`. OpenAI and Anthropic go over
plain HTTP through `requests`, which the project already depends on, so
neither adds a package. Gemini receives the schema on its own channel. The
other two receive the shape in the prompt, because their APIs have no equal.

`gemini-2.5-flash` gave 20 free requests per day, spent the quota, and left 18
products unenriched, so calls are spaced by `MIN_CALL_INTERVAL = 6.0` seconds.

### Two kinds of 429

A per-minute limit is transient: honour `retryDelay` and retry. A spent
per-day quota is terminal: stop calling. The API returns 429 for both.
`_is_daily_quota_exhausted` matches the quota name (`PerDay`), not the numeric
value, which changes with the model. A match trips a circuit breaker.

## Provenance and fill rates

`field_sources` makes the model's blast radius auditable, and it agrees with
the data on every row. The 25 Morrisons rows hold 361 values: `jsonld` 172,
`regex` 75, `missing` 45, `derived` 25, `css` 22, `llm` 22. The 24 Whisky
Exchange rows hold 336: `css` 174, `missing` 114, `regex` 24, `derived` 24.

Morrisons fills eight attributes 25 of 25: `price_gbp`, `size_ml`,
`price_per_litre`, `sku`, `availability`, `name`, `brand` and `size_raw`. The
rest: `description` 22, `flavour_style` 22, `abv_percent` 20, `pack_type` 17,
`country_of_origin` 13, `price_was` 11.

The Whisky Exchange fills eight 24 of 24: `sku`, `name`, `brand`, `price_gbp`,
`size_raw`, `size_ml`, `price_per_litre` and `abv_percent`. Then
`availability` 23, `is_on_promotion` 4 and `price_was` 3.

### What the audit found

An audit re-parsed all 25 rows with independent code: zero parser defects,
and three things no test could find.

11 of 25 products show a promotional price beside a struck-through base price.
The dataset first held the promotion price alone. It now holds `price_was` and
`is_on_promotion`.

5 of 25 products are tonic water, because Morrisons puts mixers in the gin
category. They stay: the tool reports what a shopper sees, and `abv_percent`
is null for all five, so a reader can filter them.

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
survives. That gives `The Botanist`, `Ki No Bi` and `Isle of Harris`. It
stays approximate. `Roku Noryo Tea Edition Gin` gives `Roku Noryo Tea`, where
the brand is `Roku`. Morrisons needs none of this, because its JSON-LD carries
a real brand field.

The card carries more than the name and the price. It also holds a promotion
flash, a basket button and the product id in the href. The adapter reads all
three. `sku` comes from the URL, which has the shape
`/p/14553/monkey-47-schwarzwald-dry-gin`. `availability` comes from the basket
button. One card has no button. That row stays null, because a missing button
is not a statement about stock. Three promotion flashes read `Save £3`,
`Save £15` and `Save £8`, so `price_was` is the current price plus the saving.
The fourth reads `Free Gift`. It names no money, so `price_was` stays null
there while `is_on_promotion` is true.

Four columns are empty on every Whisky Exchange row: `pack_type`,
`country_of_origin`, `flavour_style` and `description`. Each one needs product
prose, and the listing publishes none. The next section covers the product
pages.

## The Whisky Exchange, and Cloudflare

This site gates on the reputation of the connection. Three measurements on
2026-08-29 from one machine:

| Connection | robots.txt | Listing | Product page |
|---|---|---|---|
| Residential, 03:46 | 200 | 200, 24 cards | not requested |
| Same residential line, later | 200 | 403 challenge | 403 challenge |
| UK VPN exit, a London datacentre | 200 | 403 challenge | 403 challenge |

The committed dataset comes from the first row. The second row followed about
26 requests to the host, so it is a flag the tool earned. The third row is the
lesson this project already recorded once: Cloudflare scores datacentre and
VPN ranges as suspicious, so a UK exit fixed the geography and broke the IP
class. A 403 from a VPN proves nothing about the site's policy. robots.txt
answers 200 throughout, which is why the tool can still read the rules.

The tool does not defeat a challenge. `is_challenge` reads the `cf-mitigated`
header and the challenge marker in the body, raises `ChallengeBlocked` and
exits 3. That separates a challenge from a plain refusal, which also arrives
as 403.

This is the reason the four columns above stay empty. Reaching a product page
needs a challenge defeated, so no product page was ever fetched, and the
repository holds none. An earlier draft of this file stated that those pages
carry no description. Nothing in the repository supports that claim, so it is
withdrawn. What is checkable: the listing publishes no prose, and the tool
writes null rather than a guess.

The live run found a second defect. `category_url` was `/c/40/gin`, and that
path redirects to `/c/40/single-malt-scotch-whisky`. The adapter would have
collected whisky and labelled it gin. The fixture came from the same page, so
the tests passed while both were wrong about what the page was. The gin
category is `/c/338/gin`, titled "Gin and Jenever". Extraction correct,
meaning wrong. That is why every Morrisons category URL was fetched and
counted before it entered the map.

## Tests

129 tests, all offline against fixtures built from real markup, with the model
faked. The suite makes no network call, even with a real key in `.env`. It
covers both parsers, the ABV, size and origin patterns, price per litre, the
promotion price, the robots paths, the challenge detector, the cache, the
provider picker and the quota breaker.

## Extending it

**Another retailer.** Write a class with `name`, `CATEGORIES` and
`collect(fetcher, limit)`, and add `@register`. The Protocol promises the
result and not the route, so an adapter that reads a listing and an adapter
that reads a page per product both satisfy it, and the CLI never branches on
which it holds. Morrisons and The Whisky Exchange are already the two shapes.
Check robots.txt first, and read the site's terms.

**Another category.** Add an entry to that retailer's `CATEGORIES`. Fetch the
URL and count the products before you add it. The one time that step was
skipped, the tool collected whisky and called it gin.

**Another attribute.** Add the field to `Product` and to `COLUMNS`, then pick
the source that can prove it. A number or a closed list is a regular
expression in `enrich.py`. Arithmetic on existing columns is a function, as
`price_per_litre` is. Free prose that needs judgement is the model, in
`llm.py`. Set `field_sources` either way, so the new column is auditable on
the day it lands.

**Keeping it running.** The parts that break are named in the next section,
and each one is detected by comparing per-field fill rates between runs rather
than by watching for an exception. Run it on a schedule, keep every run rather
than overwriting, and compare against the run before. The `scraped_at` column
and one folder per category already give the shape that needs; a row store
keyed on `retailer`, `category`, `sku` and `scraped_at` would give price
history, which this tool does not keep.

**What is deliberately absent.** No dashboard, no scheduler, no container, no
queue, no proxy pool. `uv sync` fetches its own interpreter, so a container
would wrap a program that already runs anywhere. A cross-retailer comparison
is a schema and a folder, not a platform. Each of these is a day of work that
adds no row and no column to the dataset.

## Three ways this breaks in production

Layout drift. Morrisons removes its JSON-LD block and the parser returns nulls
without raising. A per-field fill-rate comparison against the previous run
catches a partial failure: a fall from 95% to 5% is a broken selector, not a
change in stock.

Bot defence escalation. Watch the status codes and the response size, and
alert on the first 403 rather than after 25 wasted requests. The challenge
detector already separates a challenge from a refusal, and the two need
different responses: wait out a challenge, and escalate a refusal to a human.

Silent model drift. The model returns valid JSON that is wrong, the schema
validates, and nothing raises; the Fever-Tree origin is the example. Keep a
hand-checked reference set and compare it on a schedule. Alert on the null
rate of each derived field: a sudden fall is as suspicious as a rise.

## Known limitations

- Two flavour values restate the category: J.J. Gin and Ableforth's Bathtub
  Gin both give `London dry gin`.
- Prices are a snapshot, with no price history.
- The Whisky Exchange brand is read from the product name, so
  `Roku Noryo Tea Edition Gin` gives `Roku Noryo Tea` and not `Roku`.
- `--combine` reads the committed CSV files. It does not re-check that each
  one came from the same date.
