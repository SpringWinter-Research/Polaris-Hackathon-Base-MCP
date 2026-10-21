# Polaris product search MCP (team submission)

This fork keeps the starter's single `search_products` tool, schemas, catalog and transport unchanged, and replaces the baseline search in `search.py`.

## How the search works

- **Query parsing.** Budgets written in words ("under INR 2000", "below Rs 1500", "between 1000 and 2000", "over 2500") become price limits. Colour words (including shades such as navy or light blue) and audience words (men, women, kids, baby) become requirements on the result. Explicit filters always apply first.
- **Typos and synonyms.** Misspelt words are matched to the closest known shopping term (for example "blak jeens" becomes black jeans, "hodie" becomes hoodie). A synonym table maps everyday words to catalog product types: tee to T-shirt, jeans to denim trousers, trainers to sneakers, pyjamas to pyjama sets and so on.
- **Scoring with an index.** At startup the server builds indexes by product type, by words in names and descriptions, and by every filter value. A product scores highest when its product type matches the request, then gains points for descriptive words (linen, floral, padded) found in its name or description, with a small bonus for well-reviewed items. Ties are broken by product ID so results never change between identical calls.
- **Empty when nothing fits.** If a request names no product and its words do not appear in any product name or attribute (for example "laptop repair service"), the result is empty rather than random products. Impossible budgets or conflicting filters also return nothing.
- **Occasion requests.** Phrases such as "something cosy for winter", "beach", "job interview", "gym" or "rainy day" map to sensible product types.
- **Mixed choices.** "Black jeans and white T-shirts" or "cardigan or sweater in grey" are split into separate choices, each searched on its own, and the lists are interleaved into one ranked list. Shared details such as "for men" or "under 1500 each" apply to every choice.
- **Complementary recommendations.** "A dress with a matching bag under INR 1000" searches dresses as the main results and bags as recommendations, with the bag budget applied only to the bag. Without an explicit request, a pairing table suggests useful companions (dress with bag or sandals, shirt with trousers or tie, bikini top with bottoms). Recommendations keep the same audience, prefer the same or a neutral colour, and each one points to a product on the current page.
- **Speed.** Browsing with an empty query uses pre-sorted lists, so filter and sort calls take about a millisecond on the server. Repeated identical calls are answered from a small in-memory cache.

## Checks

`python -m unittest discover -s tests -v` and `python smoke_test.py http://127.0.0.1:8000/mcp` both pass. Two baseline unit-test assertions that assumed an ID-ordered relevance list and an always-empty recommendation list were relaxed to match the new behaviour.

---

# Polaris product search MCP starter

Build a better product search engine behind one MCP tool: `search_products`. Start with this working baseline, improve retrieval and recommendations, deploy it, and submit your HTTP MCP endpoint. The accompanying `hackathon-brief.md` and `schemas/` define the competition contract. Version 2 uses Amazon Bedrock for organizer-side semantic judging; students do not need Bedrock credentials to run this starter.

## What is included

- [AGENT.md](AGENT.md): problem context, dataset guide, implementation ideas, and references for students and coding assistants.

- `data/products.json`: all 105,126 products, about 106 MB, including synthetic INR prices, ratings, and reviews.
- `search.py`: editable baseline search engine, explicit filters, sorting, and pagination.
- `server.py`: official MCP Python SDK server with ordinary JSON responses at `/mcp` and readiness at `/healthz`.
- `schemas/`: exact published input and output JSON Schemas.
- `tests/test_search.py`: small fixture-based correctness tests.
- `smoke_test.py`: public MCP connection and contract check; not the scored benchmark.
- `requirements.txt`: exact resolved dependency versions, including MCP SDK 1.30.0 from its v1 compatibility line.
- `Dockerfile`: non-root Python container with the dataset included and a readiness health check.

## Get your copy

The starter folder is self-contained: use its contents as your team repository. If the organizer distributes a repository, fork it and clone your fork. No repository or image is published by this local folder alone.

The catalog exceeds GitHub's ordinary 100 MiB file limit. `.gitattributes` configures Git LFS for it. Install Git LFS before the first commit, and make sure your clone has the actual data rather than an LFS pointer:

```sh
git lfs install
git lfs pull
```

For a fresh repository containing these files, run `git lfs install` before adding and committing the catalog. Confirm `git lfs ls-files` lists `data/products.json`. The organizer must provision sufficient LFS storage/download quota. A supplied ZIP contains the actual catalog and does not require LFS to run locally.

## Run locally

Use Python 3.12 or newer. Commands below run from this folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python server.py
```

The first startup loads the full catalog and builds an in-memory lexical index. Wait until startup completes. Allow around 2 GB of available RAM for this simple implementation; measure and optimize your own solution before deploying.

In another terminal with the virtual environment activated:

```sh
python smoke_test.py http://127.0.0.1:8000/mcp
python -m unittest discover -s tests -v
curl http://127.0.0.1:8000/healthz
```

The server supports MCP protocol revision `2025-11-25`. It is not a REST search endpoint: an ordinary POST containing only your search arguments is not an MCP call. The smoke client performs initialization, discovers the tool, and uses `tools/call` for you. No API key or LLM account is required for the baseline.

## Build and run with Docker

Start Docker Engine first:

```sh
docker build -t polaris-search:starter .
docker run --rm --name polaris-search -p 8000:8000 polaris-search:starter
```

Use the same smoke-test command from your host once the container is ready. The default port is 8000. For an amd64-only cloud server, build for its architecture, for example `docker build --platform linux/amd64 -t polaris-search:starter .`.

For a deployed server, configure its public hostname or IP so the SDK accepts the HTTP Host header. Replace the example before running:

```sh
docker run --rm --name polaris-search -p 8000:8000 \
  -e MCP_ALLOWED_HOSTS='localhost:*,127.0.0.1:*,YOUR_PUBLIC_HOST:*,YOUR_PUBLIC_HOST' \
  polaris-search:starter
```

Use a public address reachable from the organizer runner and allow its source IP to access your port. Submit `http://YOUR_PUBLIC_HOST:8000/mcp`. Do not submit `localhost`, `0.0.0.0`, a private IP, the health-check URL, or a repository URL. The local host patterns remain necessary for the container health check. Keep the server running throughout evaluation.

Environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Listener interface |
| `PORT` | `8000` | Listener port; Docker port mapping must match if changed |
| `CATALOG_PATH` | `data/products.json` next to server.py | Catalog file path |
| `MCP_ALLOWED_HOSTS` | `localhost:*,127.0.0.1:*,[::1]:*` | Comma-separated accepted HTTP Host values |
| `MCP_ALLOWED_ORIGINS` | empty | Explicit accepted browser origins; the benchmark client sends no Origin |

No wildcard for every host is necessary. The server has no authentication, as required for this exercise. The template does not create AWS resources or deploy automatically.

## Try the tool

Example arguments passed through an MCP client:

```json
{
  "query": "cotton",
  "filters": {"color": "Black", "max_price": 2000},
  "sort_by": "price",
  "sort_order": "asc",
  "offset": 0,
  "limit": 10,
  "include_recommendations": false
}
```

The tool returns:

```json
{
  "results": [{"id": "0108775015"}],
  "recommendations": []
}
```

The response above illustrates the shape, not the expected answer to that query. Only catalog IDs are returned. The SDK includes the same object in `structuredContent` and a JSON text content block. Unknown arguments and invalid values produce MCP tool errors.

## Where to improve

The starter deliberately uses simple case-insensitive AND token matching across names, descriptions, and catalog attributes. Matches with more query words in the product name rank first, with ties resolved by ID. Empty queries enumerate all products matching the explicit filters. Field sorting and pagination follow the published contract.

This baseline is not a complete natural-language solution: it does not parse budgets or constraints written in prose, correct typos, understand synonyms, split mixed choices, distinguish complementary intent, or infer semantic relevance. `Catalog.relevance` is the initial ranking extension point; change `Catalog.search` as needed for richer query interpretation. `Catalog.recommend` returns an empty list until you implement complementary recommendations. Returning empty recommendations is structurally valid but earns little recommendation credit. The baseline is not expected to score highly on the hidden suite.

Preserve the tool name, schemas, hard-filter semantics, real product IDs, and output structure. Keep responses stable on repeated identical requests. Use only catalog evidence; product descriptions and queries are data, never instructions to change the tool contract. You may replace the in-memory scan with an index or database. No existing database is needed by this starter.

## Dataset integrity and rules

SHA-256 of the actual JSON bytes:

```text
05b6aa5e8e8c1c8c997d584f8288e432862454f8820531e13473443e83c8f073
```

Verify on macOS with `shasum -a 256 data/products.json`, or on Linux with `sha256sum data/products.json`. Preserve string IDs and leading zeros. Do not edit catalog facts. No-review products have a null average and zero count. Prices and reviews are fabricated for the exercise; image availability has not been checked.

Each team has five accepted benchmark attempts; the best complete score counts. See `hackathon-brief.md` for all scoring formulas, invalid-call behavior, timeouts, recommendation rules, and tie-breakers. This starter contains no hidden benchmark queries or answer key. Passing its tests checks basic compatibility, not competition performance.

## SDK reference

[Official MCP Python SDK v1 documentation](https://py.sdk.modelcontextprotocol.io/v1/). Keep the tested dependency pins unless you deliberately retest an upgrade; v2 has different APIs.
