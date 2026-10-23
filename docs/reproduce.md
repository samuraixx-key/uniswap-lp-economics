# Reproduce

<p class="lead">Three commands: install, test, and run the whole pipeline (paid BigQuery queries
and an archive RPC). Re-runs reproduce every result file byte for byte (only run timestamps and
commit ids differ).</p>

```bash
uv sync
uv run pytest -q                  # offline; includes the real-data fixture test
uv run ulpe all --confirm-cost    # the whole pipeline: fetch anything missing, build, validate, analyze, lp, figures
```

<div class="admonition info" markdown>
<p class="admonition-title">What you need</p>

- Python 3.13 and [uv](https://docs.astral.sh/uv/).
- A `.env` (copy `.env.example`) with `ETH_RPC_URL` set to an **archive** Ethereum RPC, e.g. the
  Alchemy (the free tier worked for us as of Oct 2026). Keep it private: the URL contains your API
  key. The code never prints or logs the RPC URL; server-supplied error messages are passed through.
- `gcloud auth application-default login` for BigQuery, and `GCP_PROJECT` in `.env` set to your
  project. The free sandbox was enough for sub-projects 1 and 2 (as of Oct 2026); the paid queries
  of sub-project 3 need billing linked to the project.

</div>

<div class="admonition warning" markdown>
<p class="admonition-title">Cost: paid BigQuery queries, once each</p>

Sub-project 3 runs two sets of paid BigQuery queries, once each. The position history scans about
3 TB (dry run 2.98 TB) and is billed once: its first stage writes a BigQuery table that a re-run
reuses for 7 days, and the downloaded files are skipped afterwards. The four builder queries scan
about 676 GB in total. A Google Cloud free-trial credit covered both for us. Without
`--confirm-cost`, `ulpe all` issues no billable BigQuery query: it runs every step whose data is
already on disk, and stops with a message at the first BigQuery step whose output is missing (pool
logs, blocks, history or builder tables). `ulpe fetch-history` on its own also refuses to query
without `--confirm-cost`; it first prints the size from a free dry run.

</div>

<details class="info" markdown>
<summary>What the tests cover</summary>

`uv run pytest` needs no network or credentials: tests that touch the network are marked `live` and
skipped by default. The fixture test replays the first 400 real pool events of the window against a
matching slice of the on-chain tick book and runs checks C1 and C2 on them. An end-to-end test runs
the whole analysis (checks A1–A6 and every table) on the same events, with synthetic Binance prices
and bot data, and another runs `ulpe lp`'s analysis (checks L1–L7) on a small synthetic pool with a
position opened before the window, an NFT position, a JIT position and a flash loan. The figure
tests render every figure in the light theme, from a small fixture `results/` directory and check
that a second render gives the same bytes.

</details>

## Step by step

`ulpe all` can also be run one step at a time, in the order below. Each fetch step skips what is
already on disk.

=== "Data foundation"

    ```bash
    uv run ulpe fetch-logs --start 2026-07-01 --end 2026-10-01 --confirm-cost   # paid BigQuery pool logs (--dry-run reports bytes scanned)
    uv run ulpe fetch-snapshot                                   # tick book at the snapshot block (RPC)
    uv run ulpe fetch-samples                                    # on-chain state at 500 random blocks (RPC)
    uv run ulpe fetch-cex                                        # Binance ETHUSDC trades and ETHUSDT 1s candles
    uv run ulpe build                                            # raw files -> interim tables
    uv run ulpe validate                                         # checks C1-C6, writes data_validation/validation_report.{md,json}
    ```

=== "Markouts"

    ```bash
    uv run ulpe fetch-blocks --confirm-cost   # paid BigQuery: block fee recipients and base fees; logs in top-bot transactions
    uv run ulpe fetch-transfers   # Alchemy: internal ETH transfers sent by the top bot contracts
    uv run ulpe analyze           # checks A1-A6, then results/: tables, figure data, summary.json
    ```

=== "LP P&L"

    ```bash
    uv run ulpe fetch-chain-state                  # RPC: fee state at the snapshot and the 500 sample blocks
    uv run ulpe fetch-history --dry-run            # free: prints the size of the paid history query
    uv run ulpe fetch-history --confirm-cost       # BigQuery, paid: pool and position-manager history since 2021
    uv run ulpe fetch-chain-state                  # again: position state at both ends of the window, LP code (RPC)
    uv run ulpe fetch-price-history                # Binance ETHUSDT 1-minute candles since 2021
    uv run ulpe fetch-builders --dry-run          # free: prints the size of the four paid builder queries
    uv run ulpe fetch-builders --confirm-cost     # BigQuery, paid (about 676 GB): builder revenue and payments
    uv run ulpe fetch-payout-code                  # RPC: code of payout recipients (wallet, EIP-7702 wallet, contract)
    uv run ulpe fetch-relays                       # relay data APIs: 1,000 sampled blocks, the two 600-block holdouts
    uv run ulpe fetch-relays                       # again: one retry pass of the seed-45 holdout, as its stopping rule says
    uv run ulpe fetch-timing                       # relay data APIs: winning-bid times for the same blocks
    uv run ulpe fetch-paths                        # RPC: where each seed-45 paid/payout block's payment ends up
    uv run ulpe lp                                 # checks L1-L7, then results/: tables, figure data, summary.json["lp"]
    ```

=== "Strategy"

    ```bash
    uv run ulpe fetch-futures   # Binance USD-M ETHUSDC funding rates and 1-minute klines (hedge)
    uv run ulpe strategy        # first run: checks S1-S2, then July only -> results/strategy_freeze.json
    uv run ulpe strategy        # second run: August-September from the freeze -> results/strategy_*, summary.json["strategy"]
    ```

=== "Figures"

    ```bash
    uv run ulpe figures   # results/ -> results/figures: every figure in light SVG, the GIF and the social card
    ```

=== "This website"

    ```bash
    uv sync --group docs
    uv run mkdocs serve          # preview at http://127.0.0.1:8000
    uv run mkdocs build --strict # what CI runs
    ```

<details class="note" markdown>
<summary>Notes: data foundation</summary>

`validate` (and `all`) exit non-zero if any check fails. Downloaded and built data goes under
`DATA_DIR` (default `./data`) and is git-ignored.

</details>

<details class="note" markdown>
<summary>Notes: markouts</summary>

`fetch-logs` and `fetch-blocks` run billable queries only with `--confirm-cost`; `--dry-run`
reports bytes scanned for free. `fetch-transfers` calls `alchemy_getAssetTransfers`, so for that
step `ETH_RPC_URL` must be an Alchemy endpoint; it caches one file per bot contract and skips
contracts already fetched. `analyze` refuses to run unless validation passed on exactly the
interim files now on disk; if a gated check (A1–A4) fails it exits non-zero and writes no
results. Its per-swap and per-block working tables go to `DATA_DIR/processed` (git-ignored).

</details>

<details class="note" markdown>
<summary>Notes: LP P&L</summary>

`fetch-chain-state` runs twice because its position part needs the history. `fetch-builders`
refuses to query without `--confirm-cost` and stops before querying if a dry run exceeds its
700 GB cap. `fetch-relays` is resumable and skips a relay after three consecutive failed blocks.
Once `fetch-builders` has run it draws each holdout and writes it to disk before any of its relay
calls (a copy of the relay file is kept first); the next run retries, once, the seed-45 blocks a
relay never answered (`ulpe all` runs `fetch-relays` twice for this). Rows of the earlier rounds are never re-queried or
changed: a write that would change them is refused. The first `lp` after the retry pass, once every
seed-45 block has a relay row and a payment path, freezes the proposer-split decision. `lp` refuses to run unless
validation passed on the interim files on disk, the latest `analyze` passed its checks and its
outputs exist; if a check L1–L7 fails it writes the checks file and no results.

</details>

<details class="note" markdown>
<summary>Notes: strategy</summary>

`strategy` refuses to run unless the latest `lp` passed its checks and wrote its results. Checks
S1 and S2 run first; if one
fails it writes `results/strategy_checks.md` and no results. With no freeze file it computes July
only and writes the freeze; commit it (here: tagged `strategy-preregistered`) before the second
run. The second run reads every July value from the freeze, stops if any input file it hashed
has changed, and never rewrites it; to re-run July, delete the file by hand, which shows in git.

`ulpe all` runs `strategy` once. With the committed freeze it runs the report period. Without
one, the first `ulpe all` writes the July freeze and then stops at `figures`, which asks for
`ulpe strategy` (the report results do not exist yet); commit and tag the freeze, then run
`ulpe strategy` (or `ulpe all`) again. The report run checks the freeze's input hashes; a fresh
`ulpe analyze` and `ulpe lp` rewrite the hashed processed files byte-identically (verified
2026-10-22), so re-running the pipeline keeps matching the committed freeze. The package pins
polars to 16 threads (the file layout follows the thread count) and hashes the tracked label
file with LF line endings, so this holds on any machine with the locked dependencies. `ulpe analyze`
keeps `summary.json`'s `lp` and `strategy` results only when its own results are unchanged (run
timestamps aside); otherwise it drops them, so `ulpe strategy` and `ulpe figures` refuse to run
until `ulpe lp` and `ulpe strategy` run again. The fee runs use 4 worker processes by default
(about 1.35 GB of memory each).

</details>

<details class="note" markdown>
<summary>Notes: figures</summary>

`figures` reads only `results/` (it needs no data download), refuses unless the analysis, LP and
strategy checks all passed, and takes seconds.
`results/figures/00_hero.png` is the repository's social preview image, set by hand under
Settings → General → Social preview.

</details>

<details class="note" markdown>
<summary>Notes: this website</summary>

The pages are the Markdown under `docs/`; figures and fonts are served from `results/figures/`
and `assets/fonts/` by `scripts/mkdocs_hooks.py`.

</details>

<details class="note" markdown>
<summary>Repo map</summary>

```
src/uniswap_lp_economics/
  abi.py            keccak, event topics and 32-byte word encoding
  config.py         pool constants, study window and settings from .env
  events.py         decode raw pool logs into typed values
  v3math.py         Uniswap V3 tick/price math and USDC/WETH price conversions
  tickbook.py       replayable per-tick liquidity state and active liquidity
  rpc.py            JSON-RPC client with retries, Multicall3 batching, pool call codecs
  snapshot.py       read the tick book and sampled state from chain
  io.py             parquet read/write for exact integers (Int128 in memory, Decimal(38,0) on disk)
  data/
    bigquery.py     download pool logs from BigQuery, one file per month
    binance.py      checksum-verified Binance downloads and parsing
    blocks.py       block fee recipients and base fees, and logs in top-bot transactions (BigQuery)
    transfers.py    top-bot internal ETH transfers (Alchemy), one cached file per contract
    history.py      pool and position-manager history since 2021: one paid, two-stage BigQuery fetch
    chain_state.py  fee and position state at the snapshot, sample and end blocks; LP code (RPC)
    builders.py     builder revenue, proposer payment and per-transaction payments (BigQuery aggregates)
    relays.py       relay-reported proposer payments for a block sample, with a circuit breaker
    block_timing.py winning-bid times from the relays that keep bid history
    futures.py      Binance USD-M perpetual funding rates and 1-minute klines (the hedge)
  build.py          raw downloads -> interim tables (events, swaps, CEX prices)
  validate.py       checks C1-C6 and the validation report
  replay.py         public event replay: pool state after every event and at every block start
  v3swap.py         exact-integer V3 swap simulation and optimal arbitrage against a CEX price
  flows.py          flow labels from labels/addresses.csv, size buckets, top-bot selection
  align.py          as-of Binance reference prices and their age at each markout horizon
  markouts.py       per-swap markouts, grouped tables, day bootstrap, stale-reference filter
  arbprofit.py      gas, priority fees and coinbase payments per swap; gross vs kept per top bot
  discovery.py      per-block series, basis, gap episodes, lead-lag, AR(1), available arbitrage
  checks.py         analysis checks A1-A6
  report.py         results tables (CSV and markdown), summary.json, the limitation text
  analyze.py        `ulpe analyze`: validated data -> checks -> results/
  lp/               sub-projects 3 and 4: LP P&L, where LVR goes, reference robustness
    swapfees.py     exact per-swap LP and protocol fees from the step-by-step re-simulation
    state.py        fee-growth accumulators as the contract keeps them, plus USD-fee and LVR accumulators
    positions.py    positions from the full history: NFT matching, direct-key episodes, LPs
    engine.py       window replay: every swap step and liquidity event through the accumulators
    ledger.py       contract mirror (what the chain stores) and attribution per position
    pnl.py          window P&L per position and by group, gas, time-weighted value, bootstrap
    theory.py       theoretical LVR, P_trade, volatility regimes
    lifetime.py     lifetime P&L against holding
    destination.py  where LVR goes: fees, gas, builder margin, proposer payment, kept
    checks.py       checks L1-L7 and the reported checks R1-R6
    robustness.py   LP fees - LVR by reference and t0 offset, with a paired day bootstrap
    figdata.py      the stale-pool episode and the JIT block picked for the figures
    analyze.py      `ulpe lp`: validated data -> checks -> results/ and summary.json["lp"]
  strategy/         Phase 5: counterfactual LP strategies
    params.py       every pre-registered value (grids, fees, tolerances, margins)
    ranges.py       price-taker attribution per swap step, rebalancing rules, gas and trade costs
    cfpool.py       the carried-forward counterfactual pool: simulated arbitrage, fee rules
    checks.py       checks S1-S3, the replaced swaps, the sandwich count, the minimum profit
    stats.py        paired day bootstrap, pre-registered verdicts, break-even, protocol cut
    hedge.py        perpetual delta hedge: rules, funding, taker fees
    analyze.py      `ulpe strategy`: gates, the July freeze, then August-September -> results/
  viz/              `ulpe figures`: house style (style.py), results loader (data.py), registry
                    (render.py) and one module per report chapter
  cli.py            `ulpe` command-line entry point (`ulpe all` runs every step in order)
scripts/
  make_fixture.py   cut the small real-data test fixture
  mkdocs_hooks.py   serve results/figures and assets/fonts on the website
tests/              unit tests, the real-data fixture test and the end-to-end analysis test
  fixtures/         real pool events and tick book for the offline fixture test
labels/             curated address labels (addresses.csv) and LP vaults (lp_addresses.csv), with a source link per address
results/            committed results: tables (.md, .csv), figure_data/, figures/, summary.json, analysis, LP and strategy checks, the strategy freeze
assets/fonts/       Inter (SIL Open Font License), the figures' and the website's font
data_validation/    committed validation report (.md and .json)
docs/               the website's pages (index.md, report/, how/, reproduce.md), the roadmap and the design specs
mkdocs.yml          the website's configuration
```

</details>
