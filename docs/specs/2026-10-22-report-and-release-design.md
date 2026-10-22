# Phase 6: report, GitHub Pages and v1.0 — design

## Intent

The project is finished as research; Phase 6 turns it into something a reader at a trading firm
can take in quickly. The target reader is a hiring manager for **quant and trading roles in
crypto** (prop shops, market makers, crypto funds). They already know markouts, adverse
selection, lead-lag and execution costs; they may not know Uniswap. A DeFi researcher is a
second reader who should find every number they would check one click away.

After two minutes the trading reader should believe three things: the author takes a real
market-structure question down to raw data and comes back with a number; the numbers can be
trusted because every one says what would make it wrong; and the author thinks about who captures
value on each trade.

**Anti-goal:** reading like "a student who built a strategy that backtests well." Anything that
oversells a result, hides a failed check, or makes the strategy section look like the point fails
Phase 6 even if every file builds.

## Goals

1. `README.md` becomes a short landing page (also the GitHub Pages front page).
2. `REPORT.md` holds the full story as a trading narrative, with the long chapters cut.
3. `docs/methodology.md` opens with a "Why these choices" section and holds the full limitations.
4. The hero figure drops its −$1.1M side stat.
5. `ulpe analyze` stops deleting downstream keys from `summary.json`.
6. A full-history secret scan passes before anything goes public.
7. GitHub Pages serves the repo from `main`; a `v1.0` tag and release with a `CITATION.cff`.

## Non-goals

- No new analysis, no changed numbers. Every number on the landing page and in the report is
  already in the current README, methodology or `results/*.md`.
- No Zenodo DOI (a published record is close to permanent; can be turned on later, from `v1.1`).
- No custom site build (no static-site generator other than GitHub's built-in Jekyll, no CI
  deploy job, no second copy of the text).
- No "about me" block on the landing page.
- Project 2 (funding-rate basis backtester) is not part of Phase 6. The roadmap moves it ahead of
  further polish here once Pages is live.

## Constraints

- **Pre-registration is sacred.** Never edit `results/strategy_freeze.json`, the frozen holdout
  decisions in `data/raw/`, or the tags `holdout-preregistered`, `forwarder-preregistered`,
  `strategy-preregistered`. The S1 tolerance (`S1_REL_TOL = 1e-9`) stays as registered.
- **Reruns stay byte-identical.** `ulpe analyze`/`lp`/`strategy` reproduce their outputs byte for
  byte; the summary-key fix must keep that. New float group sums use `io.ordered_group_by`.
- **Public actions are the user's.** The user changes the repo's visibility. Tagging `v1.0`,
  publishing the release and turning on Pages happen only when the user says so. Routine commits
  go to the private repo without asking.
- No AI attribution in commits, release notes or PR text.
- The repo is private and on a free plan: Pages needs it public first.

## Part 1: landing page (`README.md`)

Order, top to bottom (agreed with the user on a mockup, "layout A"):

1. **Title and question in trading terms:** "Who makes money trading against a Uniswap pool? A
   trade-by-trade study of $7.05B of flow, measured against Binance." Pool, window
   (2026-07-01 to 2026-10-01) and 534,377 swaps in the line below.
2. **CI badge only.** Drop the Python and licence badges and the status block.
3. **One-line trading glossary:** LP = passive market maker · LVR = adverse-selection cost of
   quoting stale prices · searchers = arbitrage bots · builder/proposer payments = what bots pay
   to get their trades into the block.
4. **Hero chart** (`results/figures/00_hero.svg`, after Part 4's change).
5. **Three findings**, each one bold sentence, the number, and its caveat in plain words:
   - *Binance sets the price.* The pool catches up one block later (correlation 0.59 at
     +1 block, 0.06 in the same block). Caveat: block resolution (12 s), so this shows when the
     pool reacts, not who discovers the price within a block.
   - *Bots +2.86 bp, router flow −10.66 bp* per swap, notional-weighted, after the 5 bp fee.
     Caveat: measured against Binance's last trade at the block time; the bots' edge is 1.80 bp
     if prices are read 2 s earlier.
   - *LP fees fall $1.06M short of adverse selection; most of the bots' edge goes to block
     producers.* Bots keep nothing measurable at block time (−$0.20M, an upper bound). Caveat:
     most of the $1.06M is the protocol's quarter of the fees; before that cut, fees fall short by
     $0.18M and the interval includes zero.
6. **"Why you can trust it (overfitting controls)":**
   - Strategy tests and their pass/fail rules were frozen with a git tag before the strategy
     tests were run: `strategy-preregistered`.
   - A check that failed, reported as failed: the first proposer-split test
     (`holdout-preregistered`). A new check, written down before a fresh holdout
     (`forwarder-preregistered`), passed 290 of 290; the first decision stays on file.
   - "August–September is out of sample for every parameter, but not for me: I'd seen the
     window's totals when I wrote the test."
   - The range test was inconclusive; the fee model is labelled model-only after failing its
     July calibration (model LVR 1.38× measured).
   - Data checks gate the analysis; re-runs reproduce every result file byte for byte (only the
     run timestamp in `summary.json`, `generated_utc`, differs). Match this wording to what the
     rerun check in methodology section 21 item 7 actually compares.
   **Tag links.** Each bullet links the pre-registered file twice: on `main`, and the same file at
   its tag as proof (`https://github.com/<owner>/<repo>/blob/<tag>/<path>`). The files:
   `strategy-preregistered` → `results/strategy_freeze.json` and the strategy-experiment spec;
   `holdout-preregistered` → the proposer-payments spec; `forwarder-preregistered` → the
   forwarder-recipient-check spec (the tag commit holds only that file). At-tag links use the
   path as it was at the tag (`docs/superpowers/specs/…`); `main` links use the new path
   (Part 6). The `main` copy can differ from the tagged one (the proposer-payments spec has
   changed by a few lines since its tag), which is why the at-tag link is the proof. **Never link
   `/tree/<tag>`**: the tree at each tag still holds the old plans.
7. **"Would I trade it?"** "No. Passive LP in this pool doesn't pay after the protocol's cut. An
   hourly hedge cuts a full-range position's daily P&L spread from $16.4k to $160 per $1M, which
   changes the risk, not the edge."
8. **Links:** Full report (`REPORT.md`) · Why these choices (methodology section 0) ·
   Methodology · Limitations (methodology) · Reproduce (`REPORT.md#reproduce`).
9. Licence and disclaimer line, kept short.

Every number must match the current README exactly (they were checked against it during design).
Use "proposers", never "validators", throughout README, REPORT and methodology (README.md:1009
currently says "validator").

## Part 2: full report (`REPORT.md`)

Built from the current README chapters ("What is LVR?" through "Can an LP do better?"). No TL;DR;
it opens with one short paragraph of the question and the trading glossary, then chapter 1.

Each chapter follows: **question → chart → finding with its interval → caveat → its own
limitation**. Step-by-step detail moves out to `docs/methodology.md` and `results/*.md`, which
stay linked and render on Pages. Language follows the landing page: DeFi words translated into
trading words on first use, trading ideas not simplified.

Chapters, in this order:

1. **Where is the price set?** From "What is LVR?" (a short lead-in only, defining LVR as
   adverse selection) and "Does the pool follow Binance?" (lead-lag, gap half-life, who closes
   gaps).
2. **Who has edge against the pool?** From "Who wins against the pool?": markouts by flow. Ends
   with a short paragraph answering the reference objection for markouts from data already in
   the README: 1.80 bp with t0 − 2 s, 3.34 bp against ETHUSDT, every label keeps its sign in all
   four variants up to 5 minutes.
3. **The arbitrage auction:** available → captured → kept → builders and proposers. From "How big
   is LVR, and when?" (as far as it concerns available arbitrage), "Do arbitrage bots keep the
   edge?" and the payment side of "Where LVR goes" (the 14.4% / 20.5% proposer/builder split and
   how it was tested).
4. **The passive maker's P&L:** fees vs LVR (measured trade by trade, against the Milionis et al.
   formula: $3.70M measured at block time, $4.09M at 12 s, $3.16M from the formula with 1-second
   returns), then where LVR goes. "Who pays?" (P&L by LP type) and the lifetime-vs-holding
   material shrink to one paragraph and a table link each.
5. **Is it the reference price?** The current chapter, figure 13 and its table, unchanged in
   substance (it is all about LP fees − LVR, so it follows the LP chapter).
6. **Can an LP do better?** Cut from 259 lines to five parts: how it was pre-registered, the
   range result, the fee result (model-only), the hedge, the verdict. Detail to methodology
   section 21 and `results/strategy*.md`.

Then appendices moved from the README: **Data**, **Reproduce** (with the repo map folded in),
**Further reading**. The README's "Method" section becomes a pointer to the methodology.

The README's "Limitations" block is not repeated at the end: each chapter carries its own, and the
full list moves to the methodology (Part 3).

**What happens to cut detail (designer's call).** Detail that already exists in
`docs/methodology.md` or `results/*.md` is dropped from the report and linked. Detail that exists
only in the README moves to the methodology section it belongs to, and is never dropped if it is
about a check, a decision or a failure (e.g. the "What it replaces" account of the earlier
two-sided split around README line 560). Methodology text that says a limitation is "also in the
README" is pointed at the REPORT chapter instead. No overall line target: each chapter is as
short as question → chart → finding → caveat → limitation allows; as a guide, REPORT.md should come
to well under half of the current README.

Figures: all 17 SVGs keep their current files; the report embeds the ones its chapters need. No
figure is redrawn except the hero (Part 4).

## Part 3: methodology changes (`docs/methodology.md`)

- **New section 0, "Why these choices".** One or two sentences each, in the author's own voice
  and phrased so they work as interview answers (the author reviews each before it ships), on at
  least:
  Binance's last trade as the reference, and t0 = block timestamp; notional weighting of markouts;
  the day-block bootstrap for intervals; the 5% of active liquidity price-taker threshold; the
  ±0.068 margin and other pre-registered numbers; using the rebalancing portfolio (LVR) rather
  than holding as the LP benchmark. Each points to the section that has the detail.
- **Limitations section:** the README's full "Limitations" block moves here as one section (the
  existing section 17 covers sub-project 3 only; merge without losing any item).
- The title ("sub-projects 2 and 3") becomes one that covers the whole project.
- Existing section numbers stay as they are (other files and results link to them).

## Part 4: hero figure

In `src/uniswap_lp_economics/viz/hero.py` (the `stats` tuple near line 443), drop the first side
stat (LP fees minus LVR, all swaps). The side panel keeps two stats: share to builders and
proposers (35%) and kept by searchers (−$202k). Re-space the two remaining stats so the panel
still reads as balanced. Update `tests/test_viz_hero.py` if it reads that stat. Re-render with
`ulpe figures`, then check `00_hero.svg` and the social card `00_hero.png` by eye.

## Part 5: `ulpe analyze` keeps downstream keys

Today `ulpe analyze` writes `summary.json` from scratch (`analyze.py` → `report.write_summary`),
which drops the `lp` key written by `ulpe lp` and the `strategy` key written by `ulpe strategy`
until those steps run again. Harmless in pipeline order, a trap when running one step by hand
(e.g. `analyze` then `figures` fails for the figures that read those keys).

A missing key fails loudly today (`run_strategy` refuses without `summary.json["lp"]`,
`strategy/analyze.py:753`; `figures` fails), and that must stay true whenever the downstream
keys could be stale. So the carry-over is conditional:

- Before writing, `analyze` reads any existing `summary.json`. If analyze's own part of it (every
  top-level key except `lp` and `strategy`) is unchanged by this run, **ignoring `generated_utc`
  and `git_commit`**, it carries `lp` and `strategy` over unchanged.
- If analyze's own part changed, it drops `lp` and `strategy` as today, so `ulpe strategy` and
  `ulpe figures` keep failing loudly until `ulpe lp` and `ulpe strategy` run again.

Tests for both cases: unchanged analyze output keeps both keys; changed analyze output drops
both. The pipeline order and the docs' "re-run lp and strategy after analyze" advice stay; the
byte-identical rerun check must still pass.

## Part 6: secret scan (the gate before going public)

Already checked by hand during design: every commit uses the GitHub noreply email, no commit
carries an AI co-author line, no `data/` or private parquet was ever committed (only two small
test fixtures), `.env`, `data/` and `.superpowers/` are git-ignored, the largest file ever
committed is `results/episodes.csv` (7.6 MB), and `.env.example` holds only an empty RPC URL and
the GCP project name.

Still to do:

1. Install gitleaks and run it over the full history (`gitleaks git` over all commits and refs,
   including tags). Also grep the history for RPC-key shapes (e.g. `alchemy.com/v2/`, `infura.io/v3/`),
   GCP service-account JSON (`"private_key"`), and `.env` files ever added.
2. Any finding: the key is **rotated** at its provider first (the user does this), then the
   history is fixed. Report findings to the user before rewriting any history; rewriting would
   move the pre-registration tags, which the user must approve.
3. **Binance data terms are not a gate** (user's decision). Almost everything in `results/` is
   statistics derived from Binance prices (bp, USD totals, intervals), as any paper publishes.
   Raw Binance prices appear only in `results/figure_data/episode_cex.csv` (381 timestamp-price
   rows) and the `p_cex` column of `results/figure_data/episode_blocks.csv` (32 rows), both inputs
   to one figure and taken from free data.binance.vision files. If the terms turn out to forbid
   redistribution: untrack those two files in the latest version and git-ignore them (`ulpe lp`
   regenerates them from the downloaded Binance data, `lp/analyze.py`); no history rewrite.
4. **Keep the specs, delete the plans** (user's decision). The specs are the pre-registration
   evidence and carry no tool-specific wording; the implementation plans do (agent-workflow
   headers, commit-message templates, and a local temp path with the Windows username in
   `plans/2026-10-15-chart-redesign.md:3130`).
   - `git mv docs/superpowers/specs docs/specs`, content byte-identical (this Phase 6 spec moves
     with them).
   - `git rm -r docs/superpowers/plans` (the Phase 6 plan included, as the last step before going
     public).
   - Repoint every link: `docs/methodology.md` lines 6, 8, 1070, 1214, 1288 to `docs/specs/…`;
     drop the plan link at `docs/methodology.md:1289`; `README.md:639` (moves into REPORT) and the
     repo map line at `README.md:1295`; `docs/roadmap.md` (intro paragraph and the spec column;
     the plan column goes).
   - Git history is **not** rewritten, so the three pre-registration tags stay where they are; the
     old plans stay findable in history, which the user accepts. No public page links into a tree
     that contains them (Part 1's tag-link rule).
5. Record the scan result (tool, version, commit range, findings) in the roadmap.

## Part 7: going public, Pages, v1.0

Order, each step gated on the one before:

1. Parts 1–5 merged to `main`, tests pass, byte-identical reruns hold.
2. Secret scan (Part 6) clean, specs moved and plans deleted (Part 6 step 4).
3. **The user** makes the repo public.
4. Turn on Pages: source = `main`, root folder, GitHub's built-in Jekyll. `README.md` serves as
   the index; `REPORT.md`, `docs/methodology.md` and `results/*.md` render as pages; Jekyll's
   relative-links plugin rewrites `.md` links. A minimal `_config.yml` (title, a GitHub-supported
   theme) is the only new file for Pages. No `.md` file contains Liquid markers (`{{`, `{%`);
   checked during design.
5. Check the live site by eye: every SVG figure shows, in-page anchors (`#where-lvr-goes` style)
   work, links between pages work, the landing page reads as agreed. Fix anything GitHub's
   Markdown and Jekyll's kramdown render differently.
6. Upload the social preview (`results/figures/00_hero.png`) — a manual step for the user.
7. Add `CITATION.cff` (author **Enrico Nagata**, title, version 1.0, date, repository URL).
   The user chose their real name for the citation and release. Designer's call: the LICENSE
   copyright line and the `pyproject.toml` author become "Enrico Nagata" as well, and the
   `pyproject.toml` version becomes 1.0.0. Past commits keep the `samuraixx-key` noreply identity
   (no history rewrite). The landing page still has no "about me" block.
8. **Regenerate results from a clean tree.** The committed `summary.json` records
   `"git_commit": "forwarder-preregistered-39-g225f999-dirty"`, i.e. results from uncommitted
   code. On a clean checkout of the final code, re-run the pipeline (`ulpe analyze`, `ulpe lp`,
   `ulpe strategy` report run, `ulpe figures`), confirm the only diffs are the provenance fields
   (`generated_utc`, `git_commit`) and that no frozen file (`results/strategy_freeze.json`, the
   holdout decisions) changed, then commit the results. Any other diff stops the release and is
   reported to the user.
9. When the user says so: tag `v1.0` and publish a GitHub release. Notes: the three findings with
   caveats, the three pre-registration tags, the data window (2026-07-01 to 2026-10-01), and how
   to reproduce.
10. Roadmap: Phase 6 to "Done"; Project 2 moves up to "Next".

## Left to the builder

- Exact wording of chapter prose, the trading glossary placement within REPORT, and which
  figures each chapter embeds, as long as every number matches the current text.
- Which Jekyll theme, provided figures render at full width and tables stay readable.
- How `analyze` merges the keys (read-then-update is enough).
- How to split the work into commits and whether to do it on a branch.
