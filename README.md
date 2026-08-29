# UK Retail Product Scraper

Captures product attributes for one category from a UK retailer, one row per
product and one column per attribute, to CSV and JSON.

Morrisons gin is the answer to the brief: 25 products, 20 columns. Five more
datasets ship with it, so the same tool covers three categories on two
retailers. `data/all_products.csv` holds all 147 rows in one file.

```
data/
  all_products.csv            147 rows, 2 retailers, 3 categories
  morrisons/         gin/ vodka/ rum/     25 products each
  whisky_exchange/   gin/ vodka/ rum/     24 products each
```

## What the data shows

The specialist looks far dearer in all three categories:

| Median price per litre | Morrisons | The Whisky Exchange | Gap |
|---|---|---|---|
| Gin | £29.29 | £50.51 | +72% |
| Vodka | £23.75 | £45.36 | +91% |
| Rum | £27.86 | £68.18 | +145% |

Four bottles are the same product at the same size on both sites. They say
something else:

| Bottle, 70cl | Morrisons | The Whisky Exchange |
|---|---|---|
| Hendrick's Gin | £33.50 | £29.95 |
| Tanqueray London Dry | £21.00 | £21.50 |
| Grey Goose Vodka | £42.50 | £39.95 |
| Kraken Black Spiced Rum | £21.00 | £28.95 |

The specialist is cheaper on two, level on one and 38% dearer on one. So the
median gap is range composition and not a price difference on the same
product. The specialist stocks premium products rather than dearer copies. A
buyer who read the medians alone would reach the wrong conclusion. A buyer who
read the four bottles alone would reach a different wrong one.

Brand counts need care. Morrisons publishes 16 brand strings for 15 gin
brands, because `Fever Tree` and `Fever-Tree` are one company. The tool
records what the retailer publishes and does not normalise, so a count of
distinct brands has to normalise first.

<details>
<summary>Why the dataset needs a price per litre column</summary>

Morrisons sells gin in five sizes, so the shelf price ranks nothing. Engine
Organic Italian Gin costs £26.50 and Gordon's Premium Pink costs £27.00, so
the shelf puts them together. Engine is a 500 ml bottle and Gordon's is a
litre. Per litre they are £53.00 and £27.00. Engine is the dearest of the 25
by volume and the 17th cheapest by shelf price.

`price_per_litre` is arithmetic on two columns already present. No model runs,
and a missing price or size gives a null.

</details>

## How to run it

`uv` is the only thing to install. It fetches its own Python.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh          # macOS, Linux
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows

git clone https://github.com/jadrianports/uk-retail-product-scraper
cd uk-retail-product-scraper
uv sync                                   # 8 seconds, pinned by uv.lock
uv run pytest                             # 138 passed
uv run scrape --limit 5 --out out/try1    # a live run, no setup needed
```

That last command pulls live data from Morrisons. No API key is needed, and
`flavour_style` is the only column that stays empty without one.

```bash
cp .env.example .env                      # then set one model key
uv run scrape                             # 25 products, about 4 minutes
uv run scrape --list-categories
uv run scrape --category vodka --limit 5 --out out/vodka
uv run scrape --retailer whisky_exchange --out out/twe
```

Set `GEMINI_API_KEY`, `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`. The tool reads
them in that order and uses the first one it finds.

Leave `--out` off and the run writes to `data/<retailer>/<category>` and
replaces what is there. A shorter run says so before it does.

| Exit | Meaning |
|---|---|
| 0 | Success |
| 1 | No usable dataset. The listing failed, or the parse-rate gate failed. |
| 2 | robots.txt denied the path. |
| 3 | The host served a JavaScript challenge. |

<details>
<summary>Python versions, caching, and the second retailer</summary>

The project needs Python 3.11 or later. The suite was run on 3.11.15, 3.12.10,
3.13.13 and 3.14.5. All four pass. `uv` downloads any that is missing, so no
system Python is needed.

Every 200 response is cached under `.cache/`, so a second run makes no live
request. Delete that folder to force fresh data.

The Whisky Exchange may answer with a Cloudflare challenge. That is expected
and it is not a defect:

```
ERROR www.thewhiskyexchange.com served a JavaScript challenge. This tool does
      not defeat a challenge. Retry from a different network, or use the
      committed dataset.
```

The committed datasets were captured from a residential connection outside the
UK. A UK residential line is the least suspicious traffic a UK retailer sees. This
step is more likely to succeed from one than it was here.

</details>

## My approach

Plain HTTP, not a browser. Both sites serve product data in HTML, so a browser
would add a large dependency for no extra data.

The two retailers need different routes. Morrisons publishes JSON-LD on every
product page, so that adapter reads the listing and then one page per product.
The Whisky Exchange publishes none on its listing. Its cards carry the size,
the strength and the promotion instead, which Morrisons does not. Its detail
pages then hold a JSON-LD schema and a labelled facts list of their own.

So one adapter takes everything from the detail page. The other takes the
cheap fields from the listing, then the brand, the description and the country
from the detail page. Both cost about 25 requests.

Both meet at `collect(fetcher, limit) -> tuple[list[Product], int]`. The
Protocol promises the result and not the route, so the CLI never branches on
which adapter it holds. A test asserts that both satisfy it.

<details>
<summary>What each adapter reads, and where the brand comes from</summary>

The Whisky Exchange listing publishes no brand, so an earlier version read
words from the start of the name. It stayed approximate: `Roku Noryo Tea
Edition Gin` gave `Roku Noryo Tea`, where the brand is `Roku`. The detail page
carries a real brand field, so that guess is gone and 9 of 24 brand values
changed. `Hendrick's Orbium Gin` is now branded `Hendrick's` rather than
`Hendrick's Orbium`. That is also why the distinct brand count for this
retailer fell from 23 to 21.

The card holds more than the name and the price. `sku` comes from the URL,
which has the shape `/p/14553/monkey-47-schwarzwald-dry-gin`. `availability`
comes from the basket button. One card has no button, and that row stays null,
because a missing button is not a statement about stock. Three promotion
flashes read `Save £3`, `Save £15` and `Save £8`, so `price_was` is the
current price plus the saving. The fourth reads `Free Gift`, which names no
money, so `price_was` stays null while `is_on_promotion` is true.

</details>

## How I handled missing data

A missing value is `null` and never a placeholder. Every value also carries its
source in a `field_sources` column: `jsonld`, `css`, `regex`, `llm`, `derived`
or `missing`. That makes the model's blast radius auditable, and it is how a
wrong value was caught rather than shipped.

Morrisons fills eight attributes 25 of 25. The rest are partial:
`description` 22, `flavour_style` 22, `abv_percent` 20, `pack_type` 17,
`country_of_origin` 13, `price_was` 11.

One column is empty on every Whisky Exchange row. That site publishes no
packaging field anywhere on a product page, so `pack_type` holds a null. Its
`country_of_origin` fills 23 of 24, from a labelled facts list on the detail
page.

The harder attributes are the partial ones. None of them sits in a clean field.
`abv_percent`, `pack_type` and `country_of_origin` are parsed out of visible
page text, which is why the origin pattern once read `United Kingdom Brand J`.

<details>
<summary>Full provenance counts, and what an audit found</summary>

The 25 Morrisons gin rows hold 361 values: `jsonld` 172, `regex` 75,
`missing` 45, `derived` 25, `css` 22, `llm` 22. The 24 Whisky Exchange gin
rows hold 359: `css` 174, `missing` 71, `jsonld` 46, `derived` 24, `regex` 24,
`llm` 20.

An audit re-parsed all 25 Morrisons rows with independent code. Zero parser
defects, and three things no test could find.

11 of 25 products show a promotional price beside a struck-through base price.
The dataset first held the promotion price alone. It now holds `price_was` and
`is_on_promotion`.

5 of 25 products are tonic water, because Morrisons puts mixers in the gin
category. They stay: the tool reports what a shopper sees, and `abv_percent`
is null for all five, so a reader can filter them.

Fever-Tree Refreshingly Light Indian Tonic Water recorded `Democratic Republic
of Congo` for `country_of_origin`, because its description mentions quinine
sourced there. A stop-word list now ends the capture at the next label, and the
model no longer fills that field. The column went from 4 values to 13, so the
pattern was the real gain.

</details>

## Unreliable pages

If fewer than 80% of the expected products parse, the tool logs the count and
exits 1. The check runs before the write, so a short run leaves the previous
dataset in place. A file that is short but looks complete is the worse fault,
because no reader can see it.

One product that fails to parse is skipped and logged. It does not stop the
run. Retries are three attempts, on 429 and 5xx only.

One live defect is worth naming. The Whisky Exchange category URL was
`/c/40/gin`, and that path redirects to single malt scotch whisky. The fixture
came from the same page, so 91 tests passed while the code and the fixture were
both wrong about what the page was. Extraction correct, meaning wrong.

## Anti-bot and rate limiting

robots.txt was read before any code was written. Morrisons permits browse and
denies `/api/`. The denied API is easier to parse than the HTML, and the tool
never calls it. Sites with unreadable rules were rejected.

One request per second with jitter, single-threaded. robots.txt is read once
per host. `Retry-After` is honoured and capped at 120 seconds.

Morrisons returns 403 to an honest agent on every product page. The tool sends
a browser agent with its own name and a contact address appended. robots.txt
permits those paths, and the filter reads one header at a time.
The counter-argument is that a block is a block, and a production deployment
should hold the retailer's written agreement instead.

The line is not "no browser". Rendering a page a shopper can see is ordinary
work. Defeating a control that a site put up to say no is a different act. An
undetected automation framework and a CAPTCHA solving service both sit on that
side of the line. Neither is in this tool, and neither is planned.

When a host says no: lower the rate, then retry later, because the score
decays. If it still says no, the next step is commercial and not technical. A
scraper that wins an evasion race still loses the relationship.

<details>
<summary>The Cloudflare measurements, and which sites were rejected</summary>

The Whisky Exchange gates on the reputation of the connection, not the path.
Four measurements on 2026-08-29 from one machine:

| Connection | robots.txt | Listing | Product page |
|---|---|---|---|
| Residential, outside the UK, 03:46 | 200 | 200, 24 cards | not requested |
| The same line, after about 26 requests | 200 | 403 challenge | 403 challenge |
| A VPN exit, London datacentre | 200 | 403 challenge | 403 challenge |
| The residential line again, VPN off | 200 | 200 | 200 |
| The same line, after about 75 requests | 200 | 403 challenge | not requested |
| The same line, 15 minutes later | 200 | 200 | 200 |

Rows two and five are flags the tool earned. Row three is the lesson. A VPN
exit is a datacentre IP, and Cloudflare scores those badly. The geography
improved and the IP class got worse, so a 403 from a VPN proves nothing about
the site's policy. Rows four and six are the score decaying. The second decay
took about fifteen minutes.

Row four also corrected this file. Every earlier version said the detail pages
held no product data, and that the site published no JSON-LD. It also said the
words Country and Distillery on those pages belonged to the navigation. All
three claims came from the listing page alone, because every attempt at a
detail page had met a challenge.

The detail page holds a JSON-LD Product schema with a brand and a description,
and a labelled facts list that states the country. Three empty columns filled
and nine brand values were corrected.

The lesson is the one this project keeps relearning. A claim about what a page
does not contain needs a fetch of that page. Until then it is an assumption,
and an assumption in a README reads exactly like a measurement.

Site selection:

| Site | robots.txt | Products in plain HTML | Outcome |
|---|---|---|---|
| Morrisons | Permits browse. Denies `/api/`. | Yes, with JSON-LD. | Primary |
| The Whisky Exchange | Permits browse. | Yes, no JSON-LD. | Second |
| Asda | `Content-Signal: ai-train=no`. | No. Client-rendered. | Rejected |
| Ocado | Unreadable. Holds a WAF challenge. | | Rejected |
| Tesco, Sainsbury's, Co-op, Iceland | 403 on robots.txt. | | Rejected |
| Waitrose | Connection refused. | | Rejected |
| Booths | Permits everything. | No catalogue. | Rejected |

Asda states `ai-train=no`, and this pipeline sends page text to a model.
Unreadable rules mean no scraping.

</details>

## Where I used an LLM, and why

| Field | Source |
|---|---|
| `name`, `brand`, `price_gbp`, `size_raw`, `sku`, `availability`, `description` | JSON-LD or CSS. The model never runs. |
| `size_ml`, `pack_type`, `country_of_origin` | Regular expression only. |
| `price_per_litre` | Arithmetic. |
| `abv_percent` | Regular expression, then the model if nothing was found. |
| `flavour_style` | The model always. No other source gives it. |

The split follows what each source can prove. `flavour_style` needs prose read
and judged. It fills 22 of 25 at Morrisons and 20 of 24 at The Whisky
Exchange. ABV is a number in a known range, so a model
answer is checked against `0 <= value <= 100` and not a truthiness test,
because 0.0 is a real ABV.

The model is deliberately barred from `country_of_origin`. It read a sentence
about where quinine comes from and reported that country as a tonic water's
origin.

<details>
<summary>Providers, and two kinds of 429</summary>

Three providers work. `build_enricher` reads `GEMINI_API_KEY`, then
`OPENAI_API_KEY`, then `ANTHROPIC_API_KEY`. The shipped dataset used
`gemini-3.5-flash-lite`. OpenAI and Anthropic go over plain HTTP through
`requests`, so neither adds a package.

A per-minute limit is transient: honour `retryDelay` and retry. A spent daily
quota is terminal: stop calling. The API returns 429 for both.
`_is_daily_quota_exhausted` matches the quota name (`PerDay`) and not the
numeric value, which changes with the model. A match trips a circuit breaker.
An earlier model gave 20 free requests per day, spent the quota, and left 18
products unenriched.

</details>

## Tests

138 tests, offline, about one second. The suite makes no network call, even
with a real key in `.env`. It covers both parsers and every extraction pattern.
It also covers the robots paths, the challenge detector, the cache, the
provider picker and the quota breaker.

A test proves the parser did what it was told. It cannot prove the result means
what the column says, because the fixture agrees with the code that made it.
`scripts/audit.py` runs ten checks against real output instead:

```bash
uv run python scripts/audit.py            # the committed datasets
uv run python scripts/audit.py out/try1   # any run
```

It checks eleven things. A listing mostly named as another category. A
strength, a size or a price per litre outside range. A derived value that no
longer matches its inputs. An over-captured text field. A duplicate product. A
promotion cheaper than the current price. A brand this tool guessed that is
absent from the name. One brand under two spellings. And the CSV disagreeing
with the JSON beside it.

A note and a defect are separated. Two spellings of one brand is true of the
retailer's own data, so it is reported and does not fail. Only a defect exits
1.

It ran over all 147 shipped rows and raised no defect. It raised four notes.
Two brands carry a second spelling. Two listings hold one product named as
another category, such as a rum finished in whisky casks.

It also found two errors in this work. The brand count in this file read 16
where the retailer publishes 16 strings for 15 brands. A stale CSV also sat beside a fresh
JSON once. A copy of one file failed while its pair succeeded, so the two
shipped formats disagreed. Each file read as correct on
its own.

All six Morrisons categories were pulled live and checked the same way. 36
rows across gin, vodka, whisky, rum, brandy and tequila raised no defect.

## Extending it to more retailers and more attributes

**Another retailer.** Write a class with `name`, `CATEGORIES` and
`collect(fetcher, limit)`, then add `@register`. Morrisons and The Whisky
Exchange are already the two shapes. Check robots.txt first.

**Another category.** Add an entry to that retailer's `CATEGORIES`. Fetch the
URL and count the products before you add it. The one time that step was
skipped, the tool collected whisky and called it gin.

**Another attribute.** Add the field to `Product` and `COLUMNS`, then pick the
source that can prove it. A number or a closed list is a regular expression.
Arithmetic on existing columns is a function. Free prose that needs judgement
is the model. Set `field_sources` either way.

**Many at once.** Scaling needs an orchestration layer, and the scheduler is
the least interesting part of it. One job per retailer and category is the
unit, and cron, Airflow or Cloud Scheduler all run that shape. The constraint
that bites is politeness: `Fetcher` holds the one-second delay on the instance,
so the limit is per process and not per host. Ten concurrent jobs against
Morrisons send ten requests a second, and the scheduler breaks the promise the
code makes. A shared rate budget per host has to sit above the jobs. Fan out
across retailers, never within one.

## Keeping it running over time

A broken scraper does not raise. It returns nulls, and a null column reaches a
client as a statement about the category. The goal is to know what broke before
the client does.

Run each retailer as its own scheduled job, so one failure does not stop the
rest. Write each run to its own dated folder instead of overwriting, so any two
runs compare and any run rolls back.

| Signal | What it means | Action |
|---|---|---|
| A field's fill rate falls from 95% to 5% | A selector broke | Page a human. The dataset is wrong, not empty. |
| The newest row is older than the schedule | A run never started | Page a human. A comparison cannot see a run that did not happen. |
| The median price moves by an order of magnitude | Extraction correct, meaning wrong | Page a human. This is the whisky-labelled-as-gin failure. |
| A 403 or a challenge on the first request | Bot defence changed | Warn, and stop before 25 requests are spent. |

Alerts go wherever the team already reads. An alert that nobody sees is not
monitoring.

<details>
<summary>Hosting, and why a model should not repair a run</summary>

A scheduled container job is the natural host, so Cloud Run Jobs with Cloud
Scheduler, or the equivalent. One caveat comes out of the measurements above.
Serverless egress is a datacentre IP range, and a London datacentre address met
a Cloudflare challenge where a residential line got 200. A scheduled cloud job
will meet more challenges than a laptop does. Plan the egress before the
compute.

A model can shorten the triage of a failed parse. Two retained versions of the
same markup let it name the selector that moved, as a proposed change for a
person to approve.

It should not repair the run. A selector a model invents cannot be checked
without the correct result, and the failure destroyed that. This project has
the failure twice. A country was read from a sentence about an ingredient. A
redirect served whisky where the code expected gin. Both are valid output
with wrong meaning, and both would pass a self-repair that only asks whether
products were found.

</details>

## Three ways this breaks, and how I would detect it

**Layout drift.** Morrisons removes its JSON-LD block and the parser returns
nulls without raising. A per-field fill-rate comparison against the previous run
catches it: a fall from 95% to 5% is a broken selector, not a change in stock.
Keep the raw page for every failed parse. The cache already writes every 200
response to disk, so a diff of old markup against new names what moved.

**Bot defence escalation.** Watch the status codes and the response size, and
alert on the first 403 rather than after 25 wasted requests. The challenge
detector separates a challenge from a refusal, and the two need different
responses.

**Silent model drift.** The model returns valid JSON that is wrong, the schema
validates, and nothing raises. The Fever-Tree origin is the example. Keep a
hand-checked reference set and compare it on a schedule. Alert on the null rate
of each derived field: a sudden fall is as suspicious as a rise.

## What I did not build

No dashboard, no scheduler, no container, no queue, no proxy pool, no price
history. `uv sync` fetches its own interpreter, so a container would wrap a
program that already runs anywhere. A cross-retailer comparison is a schema and
a folder, not a platform.

Three known limits in the shipped data. Two flavour values restate the
category, so J.J. Gin and Ableforth's Bathtub Gin both give `London dry gin`.
Brand strings are not normalised, so counting distinct brands needs a
normalising step first. Prices are a snapshot.
