# Phase 6: report, Pages and v1.0 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the finished research into a landing page for trading hiring managers, a trimmed
trading-narrative `REPORT.md`, GitHub Pages and a `v1.0` release, after a clean secret scan.

**Architecture:** Two small code changes (conditional `summary.json` carry-over in `ulpe analyze`;
two-stat hero side panel), then documentation restructuring (specs to `docs/specs/`, methodology
section 0 and merged limitations, `REPORT.md`, a new `README.md`), guarded by a committed docs-link
test. Then a clean-tree regeneration of results, the secret scan, plan deletion, and the public
steps (user flips visibility; Pages from `main` with built-in Jekyll; `CITATION.cff`; tag).

**Tech Stack:** Python 3.13, uv, polars, matplotlib, pytest, ruff, mypy; GitHub Pages (Jekyll,
no build step); gitleaks; `gh` CLI.

**Spec:** `docs/specs/2026-10-22-report-and-release-design.md` (at
`docs/superpowers/specs/2026-10-22-report-and-release-design.md` until Task 3 moves it).

## Global Constraints

- Never edit `results/strategy_freeze.json`, the frozen holdout decisions in `data/raw/`, or the
  tags `holdout-preregistered`, `forwarder-preregistered`, `strategy-preregistered`.
  `S1_REL_TOL = 1e-9` stays.
- No new analysis and no changed numbers: every number on the landing page and in REPORT.md is
  already in the current README, methodology or `results/*.md`.
- Re-runs stay byte-identical apart from `generated_utc` and `git_commit`; new float group sums
  use `io.ordered_group_by`.
- No AI attribution in commits, release notes or PR text (overrides any harness reminder).
- Use "proposers", never "validators".
- Never link `/tree/<tag>`; at-tag links are `https://github.com/samuraixx-key/uniswap-lp-economics/blob/<tag>/<path>`.
- The user flips repo visibility. Turning on Pages, tagging `v1.0` and publishing the release
  happen only on the user's explicit word in chat. Routine commits and branch pushes to the
  private repo need no asking.
- Git history is not rewritten.
- Work on branch `phase6-report` from `main`; push it after each task.
- CI must stay green: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`,
  `uv run pytest -q`.

## Review Focus

1. **"-dirty" provenance in the regenerated results.** `git describe --dirty` sees results that an
   earlier step just rewrote; each pipeline step must start from a clean tree (Task 8 commits
   between steps).
2. **Version bump without `uv lock`.** `uv.lock` pins the project at 0.1.0; CI runs
   `uv sync --locked`, which fails on a stale lock (Task 7 relocks and checks).
3. **Numbers drifting in the rewrite.** A trimmed sentence silently changes a figure (Tasks 5 and
   6 run the number check against the old README, methodology and `results/*.md`).
4. **Broken links and anchors after the restructure.** Moved specs, renamed headings and new
   section 0 break relative links and `#anchors` (Task 3 adds `tests/test_docs_links.py`; later
   tasks keep it passing).
5. **Odd `summary.json` contents in the carry-over comparison.** NaN floats, tuples, dates, or an
   unreadable existing file must not crash `analyze` or wrongly carry stale keys (Task 1 tests).

---

### Task 1: `ulpe analyze` carries `lp` and `strategy` only when its own output is unchanged

**Files:**
- Modify: `src/uniswap_lp_economics/analyze.py` (the `report.write_summary(...)` call near line 278)
- Modify: `README.md` Reproduce section (one sentence, see Step 6)
- Test: `tests/test_analyze.py`

**Interfaces:**
- Produces: `DOWNSTREAM_KEYS: tuple[str, ...] = ("lp", "strategy")`,
  `PROVENANCE_ONLY: tuple[str, ...] = ("generated_utc", "git_commit")`, and
  `carry_downstream(summary: dict[str, Any], path: Path) -> dict[str, Any]` in `analyze.py`.

- [ ] **Step 1: Write the failing tests** in `tests/test_analyze.py`:

```python
def _own(**extra: Any) -> dict[str, Any]:
    return {"generated_utc": "t1", "git_commit": "c1", "swaps": 3, "basis": {"x": 1.5}, **extra}

def test_carry_downstream_keeps_lp_and_strategy_when_own_output_unchanged(tmp_path: Path) -> None:
    p = tmp_path / "summary.json"
    p.write_text(json.dumps({**_own(), "lp": {"a": 1}, "strategy": {"b": 2}}), encoding="utf-8")
    new = {**_own(), "generated_utc": "t2", "git_commit": "c2"}
    out = analysis.carry_downstream(new, p)
    assert out["lp"] == {"a": 1} and out["strategy"] == {"b": 2}
    assert out["generated_utc"] == "t2" and out["git_commit"] == "c2"

def test_carry_downstream_drops_them_when_own_output_changed(tmp_path: Path) -> None:
    p = tmp_path / "summary.json"
    p.write_text(json.dumps({**_own(), "lp": {"a": 1}, "strategy": {"b": 2}}), encoding="utf-8")
    out = analysis.carry_downstream({**_own(), "swaps": 4}, p)
    assert "lp" not in out and "strategy" not in out

def test_carry_downstream_compares_as_written(tmp_path: Path) -> None:
    # NaN is written as null and tuples as lists: an unchanged run must still carry the keys
    p = tmp_path / "summary.json"
    old = {**_own(), "v": None, "t": [1, 2], "lp": {"a": 1}}
    p.write_text(json.dumps(old), encoding="utf-8")
    out = analysis.carry_downstream({**_own(), "v": float("nan"), "t": (1, 2)}, p)
    assert out["lp"] == {"a": 1}

def test_carry_downstream_without_a_readable_file_adds_nothing(tmp_path: Path) -> None:
    p = tmp_path / "summary.json"
    assert analysis.carry_downstream(_own(), p) == _own()
    p.write_text("{not json", encoding="utf-8")
    assert analysis.carry_downstream(_own(), p) == _own()
```

Use whatever name `tests/test_analyze.py` already imports the module under (check its imports).

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_analyze.py -k carry_downstream -v`
Expected: FAIL with `AttributeError: ... has no attribute 'carry_downstream'`

- [ ] **Step 3: Implement `carry_downstream` in `analyze.py`** and call it on the summary dict
  just before `report.write_summary(...)` in `_write_results`, with
  `out / "summary.json"`. Compare in written form: normalise the new summary with
  `json.loads(json.dumps(report._clean(summary)))` (`_clean` maps non-finite floats to `None`,
  tuples to lists, dates to ISO), drop `DOWNSTREAM_KEYS` and `PROVENANCE_ONLY` from both sides,
  and compare. A missing file or one that does not parse as a JSON object returns `summary`
  unchanged. Rename `_clean` to `clean` in `report.py` if importing a private name trips ruff
  (update its one caller).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_analyze.py -v`
Expected: all PASS (the existing end-to-end test included).

- [ ] **Step 5: Run the full checks**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q`
Expected: all clean, all tests pass.

- [ ] **Step 6: Document it.** In README.md's Reproduce section, next to the existing "`ulpe analyze`
  and `ulpe lp` rewrite the hashed processed files byte-identically" sentence, add: "`ulpe analyze`
  keeps `summary.json`'s `lp` and `strategy` results only when its own results are unchanged
  (run timestamps aside); otherwise it drops them, so `ulpe strategy` and `ulpe figures` refuse to
  run until `ulpe lp` and `ulpe strategy` run again."

- [ ] **Step 7: Commit**

```bash
git add src/uniswap_lp_economics/analyze.py src/uniswap_lp_economics/report.py tests/test_analyze.py README.md
git commit -m "ulpe analyze: keep lp and strategy keys when its own summary is unchanged"
git push -u origin phase6-report
```

### Task 2: Hero side panel drops the LP total

**Files:**
- Modify: `src/uniswap_lp_economics/viz/hero.py` (the `stats` tuple and its layout, lines ~441–458)
- Test: `tests/test_viz_hero.py`
- Regenerate: `results/figures/00_hero.svg`, `results/figures/00_hero.png`

**Interfaces:** none new.

- [ ] **Step 1: Write the failing test**

```python
def test_side_panel_has_two_stats_and_no_lp_total(tmp_path: Path) -> None:
    r = ...  # build the hero input the way the neighbouring hero tests do (fixture_frames / vizfix)
    texts = " ".join(_hero_texts(hero.hero(r)).values())
    assert "LP fees minus LVR" not in texts
    assert "of the arbitrage went to block" in texts
    assert "kept by searchers at block" in texts
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_viz_hero.py::test_side_panel_has_two_stats_and_no_lp_total -v`
Expected: FAIL on the first assert.

- [ ] **Step 3: Remove the first entry of `stats`** (the `fees_minus_lvr_usd` one) and re-space the
  remaining two so the panel sits centred against the Sankey: `yy = 0.70 - n * 0.24`, divider from
  `0.30` to `0.74`. Keep `lp = r.summary["lp"]` only if still used (it is, for `destination`).

- [ ] **Step 4: Run the hero tests**

Run: `uv run pytest tests/test_viz_hero.py -v`
Expected: all PASS.

- [ ] **Step 5: Re-render and check by eye**

Run: `uv run ulpe figures`
Then open `results/figures/00_hero.svg` and `results/figures/00_hero.png` (read both images).
Expected: two stats (35%, −$202k) evenly placed beside the Sankey, nothing overlapping, the social
card still 1280×640. `git status` shows only `00_hero.*` changed under `results/figures/`; if any
other figure changed, stop and find out why.

- [ ] **Step 6: Full checks, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/viz/hero.py tests/test_viz_hero.py results/figures/00_hero.svg results/figures/00_hero.png
git commit -m "Hero: drop the all-swaps LP total from the side panel"
git push
```

### Task 3: Specs move to `docs/specs/`; a docs-link test guards every link

**Files:**
- Move: `docs/superpowers/specs/*` → `docs/specs/` (`git mv`, content byte-identical)
- Modify: `docs/methodology.md` (lines 6, 8, 1070, 1214, 1288; delete the plan link at 1289),
  `README.md` (line ~639 spec link; repo-map line ~1295), `docs/roadmap.md` (intro paragraph;
  spec column repointed; plan column removed)
- Create: `tests/test_docs_links.py`

**Interfaces:**
- Produces: `tests/test_docs_links.py` with `github_slug(heading: str) -> str`, used by later tasks
  only through running the test file.

- [ ] **Step 1: Write the link test** `tests/test_docs_links.py`. It collects tracked Markdown with
  `git ls-files '*.md'`, skipping `docs/superpowers/plans/`. Tests:
  - `test_relative_links_resolve`: every Markdown link `](target)` that is not `http(s):`,
    `mailto:` or a bare `#anchor` resolves to an existing file relative to the linking file
    (strip any `#fragment`; image links included).
  - `test_anchors_exist`: every `#fragment` on a link to a `.md` file (or a bare `#fragment`, for
    the same file) matches a heading slug in the target. `github_slug`: lowercase; drop every
    character that is not a letter, digit, space, `-` or `_`; spaces → `-`. Duplicate headings get
    `-1`, `-2` suffixes.
  - `test_no_tree_tag_links`: no tracked `.md` contains `/tree/holdout-preregistered`,
    `/tree/forwarder-preregistered`, `/tree/strategy-preregistered` or `/tree/v1.0`.
  - `test_no_validator_wording`: `README.md`, `REPORT.md` (if present) and `docs/methodology.md`
    do not contain `validator` (case-insensitive).
  Add a unit test for `github_slug`: `"## 0. Why these choices"` → `"0-why-these-choices"`,
  `"Is it the reference price?"` → `"is-it-the-reference-price"`,
  `"Checks L1–L7 and R1–R6"` → `"checks-l1l7-and-r1r6"`.

- [ ] **Step 2: Run it to see the current state**

Run: `uv run pytest tests/test_docs_links.py -v`
Expected: `test_no_validator_wording` FAILS (README.md:1009); fix any other failure it shows
the same way in this task (they are pre-existing broken links).

- [ ] **Step 3: Move the specs and repoint links.** `git mv docs/superpowers/specs docs/specs`.
  Repoint every `superpowers/specs/` link listed above to `specs/` (from `docs/`) or `docs/specs/`
  (from the root). Delete methodology's plan link (line 1289, keep the sentence grammatical).
  Roadmap: intro becomes "Each piece of work has a design spec in [`docs/specs/`](specs/)."; the
  table keeps a Spec column and loses the Plan column. Replace "validator" at README.md:1009 with
  "proposer". Repo-map line: `docs/specs/   design specs for every sub-project, including the
  pre-registrations`.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/test_docs_links.py -v` → all PASS.
Run: `git grep -n "superpowers/" -- ':!docs/superpowers/plans'` → only the Phase 6 spec's own
references to the old paths (its Part 1 tag-link rule and Part 6).
Run: `git diff --stat -M HEAD -- docs/specs` after staging → every spec shows as a 100% rename.

- [ ] **Step 5: Full checks, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add -A docs README.md tests/test_docs_links.py
git commit -m "Specs move to docs/specs; docs-link test"
git push
```

### Task 4: Methodology: "Why these choices", one limitations section, a project-wide title

**Files:**
- Modify: `docs/methodology.md`

- [ ] **Step 1: Title.** Replace the H1 "Methodology: price discovery, markouts and LP P&L
  (sub-projects 2 and 3)" with "Methodology: who makes money on Uniswap V3", and update the
  opening paragraph so it covers sub-projects 1–5 (keep its spec links, now to `specs/`).

- [ ] **Step 2: Section 0.** Insert `## 0. Why these choices` before section 1. One or two
  sentences each, first person, phrased as an answer to "why did you…?", each ending with a link
  to the section that has the detail. At least: Binance's last ETHUSDC trade as the reference and
  t0 = block timestamp (section 2, 18); notional weighting of markouts (3); the day-block
  bootstrap for intervals (3); LVR against a rebalancing portfolio rather than holding as the LP
  benchmark (11, 13); 5% of active liquidity as the price-taker threshold (21); the ±0.068 fees ÷
  LVR margin and the other pre-registered numbers (21); why the proposer split needed a second
  pre-registered check (19, 20). Take every reason from the existing text; invent none.

- [ ] **Step 3: User checkpoint.** Show the user section 0 in chat and wait: the user reviews
  each sentence as their own interview answer and may rewrite it. Apply their edits verbatim.

- [ ] **Step 4: Limitations.** Add `## 22. Limitations (whole project)` at the end: the README's
  entire "Limitations" section (all sub-headings and items) merged with section 17's items, no
  item dropped, duplicates merged once. Section 17 keeps its heading and becomes one line pointing
  to section 22. Where methodology says a limitation text is "also in the README", point it at
  `REPORT.md` instead (the chapter it will sit in, per Task 5's chapter list).

- [ ] **Step 5: Verify**

Run: `uv run pytest tests/test_docs_links.py -v` → PASS.
Check by reading: every bullet of the README's Limitations section appears in section 22
(compare the two side by side).

- [ ] **Step 6: Commit**

```bash
git add docs/methodology.md
git commit -m "Methodology: why these choices, one limitations section"
git push
```

### Task 5: `REPORT.md`, the full story as a trading narrative

**Files:**
- Create: `REPORT.md`
- Modify: `docs/methodology.md` (receives README-only detail that is cut from the chapters)

- [ ] **Step 1: Save the number corpus** before anything changes the README:
  `git show main:README.md > <scratchpad>/old_README.md`.

- [ ] **Step 2: Write `REPORT.md`.** Title "Who makes money on Uniswap V3: the full report". One
  short opening paragraph (the question, pool, window 2026-07-01 to 2026-10-01, 534,377 swaps,
  $7.05B) plus the trading glossary from the landing page; no TL;DR. Then chapters, each as
  question → chart → finding with its interval → caveat → `*Limitation:*` paragraph (that
  chapter's items from methodology section 22), DeFi words translated into trading words on first
  use. Sources in the current README:

  | REPORT chapter | from README section(s) |
  |---|---|
  | 1. Where is the price set? | "What is LVR?" (short lead-in, LVR = adverse selection), "Does the pool follow Binance?" |
  | 2. Who has edge against the pool? | "Who wins against the pool?" + closing paragraph: 1.80 bp at t0 − 2 s, 3.34 bp against ETHUSDT, every label keeps its sign in all four variants up to 5 min |
  | 3. The arbitrage auction | available-arbitrage part of "How big is LVR, and when?", "Do arbitrage bots keep the edge?", payment side of "Where LVR goes" (14.4% / 20.5% and how it was tested) |
  | 4. The passive market maker's P&L | the LP part of "How big is LVR, and when?" (measured $3.70M at 0 s, $4.09M at 12 s, formula $3.16M with 1 s returns), "Where LVR goes"; "Who pays?" and the lifetime material as one paragraph + table link each |
  | 5. Is it the reference price? | "Is it the reference price?" (figure 13 and table), unchanged in substance |
  | 6. Can an LP do better? | "Can an LP do better?" cut to five parts: how it was pre-registered, range result, fee result (model-only), hedge, verdict |

  Appendices: `## Data` (README "Data"), `## Reproduce` (README "Reproduce" with "Repo map" folded
  in as a subsection), `## Further reading`. README's "Method" becomes one line pointing to the
  methodology. No end-of-report limitations block.

- [ ] **Step 3: Move cut detail.** Detail already in `docs/methodology.md` or `results/*.md`: drop
  it and link. Detail only in the README: move it to the methodology section it belongs to; never
  drop it if it is about a check, a decision or a failure (e.g. the "What it replaces" account of
  the earlier two-sided split in "Where LVR goes").

- [ ] **Step 4: Number check.** Save and run this script from the scratchpad:

```python
# numbers_check.py <new.md> <corpus files...>: every number in new.md must appear in the corpus
import re, sys, pathlib
NUM = re.compile(r"[−-]?\$?\d[\d,]*(?:\.\d+)?(?:\s?(?:bp|%|M|k|B|s|×))?")
norm = lambda s: s.replace("−", "-").replace(" ", "")
new = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
corpus = norm("".join(pathlib.Path(p).read_text(encoding="utf-8") for p in sys.argv[2:]))
missing = sorted({m for m in NUM.findall(new) if len(norm(m)) > 1 and norm(m) not in corpus})
print("\n".join(missing) or "all numbers found")
```

Run: `uv run python -I <scratchpad>/numbers_check.py REPORT.md <scratchpad>/old_README.md docs/methodology.md results/*.md`
Expected: "all numbers found", or a short list in which every entry is a chapter number, a
year, or a rounding of a corpus number that you can point to. Fix anything else.

- [ ] **Step 5: Verify links:** `uv run pytest tests/test_docs_links.py -v` → PASS.

- [ ] **Step 6: Commit**

```bash
git add REPORT.md docs/methodology.md
git commit -m "REPORT.md: the full story as a trading narrative"
git push
```

### Task 6: `README.md` becomes the landing page

**Files:**
- Modify: `README.md` (replaced wholesale)

- [ ] **Step 1: Write the new README** with this content, in this order. Prose wording may be
  tightened; numbers, tags and order may not change.

```markdown
# Who makes money trading against a Uniswap pool?

A trade-by-trade study of $7.05B of flow, measured against Binance: every one of the 534,377
swaps in the Uniswap V3 USDC/WETH 0.05% pool on Ethereum from 2026-07-01 to 2026-10-01.

[CI badge, exactly as today]

**In trading terms:** LP = passive market maker · LVR = the adverse-selection cost of quoting
stale prices · searchers = arbitrage bots · builder/proposer payments = what bots pay to get
their trades into the block.

[hero <img>, exactly as today's tag]

## Three findings
- **Binance sets the price.** The pool catches up one block later (correlation 0.59 at +1 block,
  0.06 in the same block). *Caveat:* block resolution (12 s), so this shows when the pool reacts,
  not who discovers the price within a block.
- **Bots +2.86 bp, router flow −10.66 bp** per swap, notional-weighted, after the 5 bp fee.
  *Caveat:* measured against Binance's last trade at the block time; the bots' edge is 1.80 bp if
  prices are read 2 s earlier.
- **LP fees fall $1.06M short of adverse selection; most of the bots' edge goes to block
  producers.** Bots keep nothing measurable at block time (−$0.20M, an upper bound). *Caveat:*
  most of the $1.06M is the protocol's quarter of the fees; before that cut, fees fall short by
  $0.18M and the interval includes zero.

## Why you can trust it (overfitting controls)
- Strategy tests and their pass/fail rules were frozen with a git tag before the strategy tests
  were run: `strategy-preregistered` ([freeze](results/strategy_freeze.json), [at the tag](https://github.com/samuraixx-key/uniswap-lp-economics/blob/strategy-preregistered/results/strategy_freeze.json);
  [spec](docs/specs/2026-10-21-strategy-experiment-design.md), [at the tag](https://github.com/samuraixx-key/uniswap-lp-economics/blob/strategy-preregistered/docs/superpowers/specs/2026-10-21-strategy-experiment-design.md)).
- A check that failed, reported as failed: the first proposer-split test, `holdout-preregistered`
  ([spec](docs/specs/2026-10-21-proposer-payments-design.md), [at the tag](https://github.com/samuraixx-key/uniswap-lp-economics/blob/holdout-preregistered/docs/superpowers/specs/2026-10-21-proposer-payments-design.md)).
  A new check, written down before a fresh holdout, `forwarder-preregistered`
  ([spec](docs/specs/2026-10-21-forwarder-recipient-check-design.md), [at the tag](https://github.com/samuraixx-key/uniswap-lp-economics/blob/forwarder-preregistered/docs/superpowers/specs/2026-10-21-forwarder-recipient-check-design.md)),
  passed 290 of 290; the first decision stays on file.
- August–September is out of sample for every parameter, but not for me: I'd seen the window's
  totals when I wrote the test.
- The range test was inconclusive; the fee model is labelled model-only after failing its July
  calibration (model LVR 1.38× measured).
- Data checks gate the analysis; re-runs reproduce every result file byte for byte (only the run
  timestamp in `summary.json` differs).

## Would I trade it?
No. Passive LP in this pool doesn't pay after the protocol's cut. An hourly hedge cuts a
full-range position's daily P&L spread from $16.4k to $160 per $1M, which changes the risk, not
the edge.

[Full report](REPORT.md) · [Why these choices](docs/methodology.md#0-why-these-choices) ·
[Methodology](docs/methodology.md) · [Limitations](docs/methodology.md#22-limitations-whole-project) ·
[Reproduce](REPORT.md#reproduce)

[Licence and disclaimer: today's section, cut to two lines]
```

Before writing the last trust bullet, read methodology section 21 item 7 and confirm the rerun
check compares exactly that (byte-identical apart from `generated_utc`; `git_commit` changes only
when the commit does). If it compares something else, match the wording to it.

- [ ] **Step 2: Number check**

Run: `uv run python -I <scratchpad>/numbers_check.py README.md <scratchpad>/old_README.md docs/methodology.md results/*.md`
Expected: as in Task 5 Step 4.

- [ ] **Step 3: Links:** `uv run pytest tests/test_docs_links.py -v` → PASS (the at-tag links are
  absolute and are checked by eye in Task 11, once the repo is public).

- [ ] **Step 4: Read it as the target reader.** Read the rendered README on GitHub (the private
  branch view) top to bottom: under two minutes, no DeFi term unexplained before the hero, every
  finding has its caveat beside it.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "README: landing page for trading readers"
git push
```

### Task 7: Name, version and Pages config

**Files:**
- Modify: `LICENSE` (copyright line), `pyproject.toml`, `uv.lock`
- Create: `_config.yml`

- [ ] **Step 1:** LICENSE: `Copyright (c) 2026 Enrico Nagata`. `pyproject.toml`: `version = "1.0.0"`
  and `authors = [{ name = "Enrico Nagata" }]` under `[project]`.

- [ ] **Step 2: Relock**

Run: `uv lock && uv sync --locked`
Expected: `uv.lock` shows the project at 1.0.0 and `uv sync --locked` succeeds.

- [ ] **Step 3: `_config.yml`** at the repo root: `title: Who makes money on Uniswap V3?`, a
  GitHub-Pages-supported theme (`jekyll-theme-primer` unless figures render too narrow), and
  `exclude:` for `src/`, `tests/`, `scripts/`, `labels/`, `uv.lock`, `pyproject.toml`. Do not
  exclude `results/`, `docs/`, `assets/` or `data_validation/`.

- [ ] **Step 4: Full checks, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add LICENSE pyproject.toml uv.lock _config.yml
git commit -m "v1.0.0 metadata, author name, Pages config"
git push
```

### Task 8: Merge, regenerate from a clean tree

**Files:**
- Regenerate: `results/**`, `data_validation/**` if touched

- [ ] **Step 1: Merge** `phase6-report` into `main` with a merge commit
  (`git checkout main && git merge --no-ff phase6-report -m "Merge branch 'phase6-report': Phase 6 report"`), push.

- [ ] **Step 2: Each step from a clean tree.** `git status --porcelain` must print nothing before
  each command; commit the results after each, so the next step's `git describe --dirty` is clean.
  `ulpe lp` takes a long time: run it in the background.

```bash
uv run ulpe analyze   && git add results && git commit -m "Results: ulpe analyze from a clean tree"
uv run ulpe lp        && git add results && git commit -m "Results: ulpe lp from a clean tree"
uv run ulpe strategy  && git add results && git commit -m "Results: ulpe strategy report from a clean tree"
uv run ulpe figures   && git add results && git commit -m "Results: figures from a clean tree"
```

  Before each `git add`:
  `git diff -U0 -- results | grep -E '^[+-]' | grep -v -E '^(\+\+\+|---) ' | grep -v -e generated_utc -e git_commit`
  must print nothing (a changed provenance line of the same run in a `.md` file is fine; anything
  else is not), `git diff --stat -- results/figures` must be empty, `git diff --quiet --
  results/strategy_freeze.json` must succeed, and no `git_commit` in `results/` may end in
  `-dirty`. `ulpe analyze` must report PASS,
  `ulpe lp` PASS, `ulpe strategy` PASS. Any other diff or result: stop and report it to the user.

- [ ] **Step 3: Push** `main`.

### Task 9: Secret scan (the gate)

- [ ] **Step 1: Install gitleaks** from its official source (`winget install gitleaks` or the
  GitHub release), record the version (`gitleaks version`).

- [ ] **Step 2: Scan all history**

Run: `gitleaks git --log-opts="--all" --redact -v --report-path <scratchpad>/gitleaks.json .`
Expected: "no leaks found".

- [ ] **Step 3: Targeted greps over all history**

Run: `git log --all -p | grep -n -i -E "alchemy\.com/v2/[A-Za-z0-9_-]{8,}|infura\.io/v3/[0-9a-f]{8,}|\"private_key\"|BEGIN (RSA |EC )?PRIVATE KEY"`
Run: `git log --all --name-only --format= | grep -E "(^|/)\.env$|credentials.*\.json$" | sort -u`
Expected: both print nothing.

- [ ] **Step 4: Any finding stops the release.** Report it to the user (file, commit, kind, never
  the secret itself). The user rotates the key at its provider; no history rewrite without the
  user's approval (it would move the pre-registration tags).

- [ ] **Step 5: Record** in `docs/roadmap.md` under "Manual steps" or a "Release checks" line:
  tool and version, `--all` refs, the HEAD commit scanned, result. Commit with Task 10.

### Task 10: Delete the plans; hand over for going public

- [ ] **Step 1:** Note this plan's last commit SHA (to read it later with `git show <sha>:docs/superpowers/plans/2026-10-22-report-and-release.md`).
- [ ] **Step 2:** `git rm -r docs/superpowers/plans` (this plan included); `docs/superpowers/` is
  then empty and gone. Run `uv run pytest tests/test_docs_links.py -v` → PASS;
  `git grep -n "superpowers/plans"` → nothing outside the Phase 6 spec.
- [ ] **Step 3: Commit** ("Remove implementation plans before going public", with the Task 9
  roadmap line) and push `main`.
- [ ] **Step 4: Stop.** Tell the user: scan clean, plans removed, ready for them to make the repo
  public (Settings → General → Danger zone → Change visibility). Wait.

### Task 11: Pages, citation and v1.0 (after the user has made the repo public)

- [ ] **Step 1: Ask, then turn on Pages.** On the user's yes:
  `gh api -X POST repos/samuraixx-key/uniswap-lp-economics/pages -f "source[branch]=main" -f "source[path]=/"`.
  Wait for the build: `gh api repos/samuraixx-key/uniswap-lp-economics/pages/builds/latest --jq .status`
  → `built`.

- [ ] **Step 2: Check the live site by eye** in the browser pane: landing page as agreed, all 17
  SVG figures display on REPORT, in-page anchors (`#reproduce`, `#0-why-these-choices`,
  `#22-limitations-whole-project`, the chapter anchors) jump correctly (kramdown can strip
  leading digits from heading ids where GitHub keeps them: if `#0-…` or `#22-…` fail, give those
  headings explicit ids or reword the links, and keep `tests/test_docs_links.py` passing), links between pages
  work, the at-tag `/blob/` links open the right files. Fix differences between GitHub's and
  Jekyll's Markdown in the source (not with Pages-only copies); push; recheck.

- [ ] **Step 3: Social preview.** Ask the user to upload `results/figures/00_hero.png` under
  Settings → General → Social preview.

- [ ] **Step 4: `CITATION.cff`** at the root: `cff-version: 1.2.0`, `message`, `title: "Who makes
  money on Uniswap V3?"`, `authors: [{family-names: Nagata, given-names: Enrico}]`,
  `version: 1.0.0`, `date-released:` the tag date, `repository-code:
  https://github.com/samuraixx-key/uniswap-lp-economics`, `license: MIT`. Commit and push; check
  that GitHub shows "Cite this repository".

- [ ] **Step 5: Ask, then release.** On the user's yes: `git tag -a v1.0 -m "v1.0"`,
  `git push origin v1.0`, and `gh release create v1.0 --title "v1.0" --notes-file <scratchpad>/notes.md`.
  Notes: the three findings with caveats (landing-page wording), the three pre-registration tags
  with their at-tag links, the data window 2026-07-01 to 2026-10-01, and "Reproduce:" linking
  `REPORT.md#reproduce`. No AI attribution.

- [ ] **Step 6: Roadmap.** Phase 6 moves to "Done" (spec link `specs/2026-10-22-report-and-release-design.md`);
  Project 2 (funding-rate basis backtester) moves to "Next", ahead of further polish here; the
  social-preview manual step is removed once done. Commit and push.
