# Survivorship-free data — acquire delisted major pairs — Design

**Iteration:** iter-16
**Advances open-topic:** `T0005` (point-in-time universe / survivorship) → **`partial`** at closeout — this lands the survivorship-free **data substrate**; the experiment-side de-bias (PIT-universe selection, delisting-loss, re-measure) remains, deferred to dedicated future iterations.
**Second of the "data foundation" program** (funding [iter-15] → **delisted-pair klines** [this] → aggTrades → on-chain).
**Depends on:** the `cli/data` pipeline (specs `00003`/`00004`/`00005`); iter-15 (funding rides along where a perp existed).

## Context — what

The dataset trades today's 19 **surviving** USDT majors across all history — survivorship-biased (`T0005`). The fix's data substrate is to acquire the major USDT spot pairs that a contemporaneous majors-trader *would* have held and that later **blew up / faded** (e.g. FTT, WAVES, DASH, ZEC, the LUNA collapse), so the panel is no longer survivor-only.

**Key RECON finding (already done — it re-scoped this iteration):** Binance does **not** remove delisted symbols from `exchangeInfo`; it keeps them with **`status="BREAK"`**. So every ever-top-25 delisted major is *already* reachable by the **existing** acquisition paths — `FTT/LUNA/LUNC` are still `TRADING`; the dead ones (`WAVES, UST, SRM, HNT, OMG, BTG, XEM, NANO, DASH, ZEC, QTUM, ICX, …`) are `BREAK`, which `download` already fetches as **archive-only**. No symbol that is both absent-from-`exchangeInfo` *and* has Vision archives exists among the majors. **No pipeline enhancement is needed to acquire them** — the work is data-population + confirming the lifecycle reports them, plus the `delist`→`drop` rename.

**This iteration is DATA ONLY:** acquire the curated blown-up majors (via the existing `download`) so they sit in the dataset with real listing→delisting ranges; confirm `verify` reports them; rename `delist`→`drop`. No recipe/universe/backtest change.

## Why this matters

Research §3/§12: Binance delists ~20-50 spot pairs/quarter; a "currently listed" universe inflates historical results via survivorship, and a faded/dead coin a contemporaneous trader held could drop 50-90%. Acquiring the delisted majors is the prerequisite for *every* downstream survivorship fix: the PIT-universe re-measure (future iteration) and `T0007`'s "LUNA/FTX" crisis-stress pass (which today would run over a survivor-only panel — the very bias this removes). The data has to exist before any of that is honest.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Scope = DATA ONLY.** Acquire + store the curated delisted majors with real ranges; confirm `verify` reports them; rename `delist`→`drop`. **No** `recipe.universe` change, **no** delisting-loss, **no** re-measure — deferred to dedicated experiment iterations. | The user scoped this iteration to the data substrate; recipe re-evaluation is handled later (like iter-15's funding data preceded the funding *feature*). Decided-but-deferred for the future iteration: delisting-loss = liquidate at last available close. |
| 2 | **Inclusion = curated contemporaneous majors:** USDT spot pairs that ever peaked **top-25 by market cap** during their Binance life and later **blew up / faded out of the current 19**. The RECON candidate set (all reachable today via `TRADING`/`BREAK`): `FTTUSDT`, `WAVESUSDT`, `DASHUSDT`, `ZECUSDT`, `QTUMUSDT`, `OMGUSDT`, `XEMUSDT`, `BTGUSDT`, `NANOUSDT`, `ICXUSDT`, `LUNCUSDT`/`USTCUSDT` (the Terra collapse), `HNTUSDT`/`SRMUSDT` (borderline). The closeout finalizes the cut. | Faithfully de-biases the liquid-majors strategy by adding the material blow-ups a majors-trader held, not micro-caps. The RECON confirmed each candidate is acquirable (archives exist) and its status. |
| 3 | **Acquisition mechanic = the existing `download`** — no pipeline change. `TRADING` survivors (FTT, LUNA, LUNC) extend as usual; `BREAK` dead pairs (WAVES, DASH, …) are fetched **archive-only** over their real `[listing, delisting]` range by the *existing* non-`TRADING` discovery (`_find_interior_anchor` + bisect). We just add the curated symbols to a download pairs file. | The RECON invalidated the original "acquire not-in-`exchangeInfo`" premise: Binance keeps delisted symbols as `BREAK`, so the existing paths already handle them. Building a not-in-`exchangeInfo` acquisition path would be speculative (no consumer) — dropped per YAGNI. |
| 4 | **Lifecycle already handles them; confirm + report.** `download` acquires (TRADING/BREAK); `backfill` skips the `BREAK` dead pairs (no right edge — existing behavior); `verify` must **accept + report** an archive-only pair whose `TO < today` (likely already valid, since `BREAK`/archive-only is a supported case — confirm with a test, add a coverage line if missing); `rename` handles a LUNA→LUNC-style rename if a target renamed (existing machinery + gap-NaN). Funding (iter-15) rides along where a perp existed, else NaN. | A delisted pair is a first-class, permanent dataset member; the existing lifecycle mostly covers it. The only open question is whether `verify` has ever exercised a `TO<today` pair (today's 19 are all `TRADING`) — a confirming test closes it. |
| 5 | **Rename `delist` → `drop`**, repurposed as a pure pair-removal tool — NOT a market-delisting handler. The delete *mechanics* are unchanged (`rmtree` + conditional calendar shrink); only the name + help text change. No back-compat alias (early-stage CLI). Ships as a **plain commit — no `!`, no major version bump** (`refactor(data): rename delist command to drop`). | The old `delist` encoded the survivorship-*inducing* action ("a pair delisted on Binance → delete it"), which is exactly what T0005 fixes; market delistings are now *retained* (acquired archive-only; `backfill` already retains non-`TRADING`). Renaming to `drop` + reframing as "remove an unwanted/mistaken pair" resolves the name/semantics conflict and makes deletion an explicit, deliberate act rather than a survivorship footgun. |

## Component file tree

```
cli/data/
├── verify.py      # MODIFY (only if needed): accept + report archive-only pairs with TO < today (BREAK/dead majors); a coverage line. Likely already valid — confirm with a test.
├── command.py     # MODIFY: rename the `delist` command → `drop` (+ help-text reframe as pair-removal).
└── pipeline.py    # MODIFY: rename delist_pipeline → drop_pipeline (delete mechanics unchanged). NO acquisition change (existing TRADING/BREAK paths suffice).
tests/
├── test_data_verify.py     # EXTEND: an archive-only delisted pair (TO < today) passes verify + is reported.
├── test_data_delist.py     # RENAME → test_data_drop.py: same delete-mechanics assertions, command/function renamed delist→drop.
└── (existing pipeline/e2e tests — unchanged; BREAK/archive-only acquisition already covered)
README.md                   # MODIFY: Usage — note the dataset can include delisted (BREAK / archive-only) majors; the delist→drop rename.
```

## Acquisition (no code — existing `download`)

The curated majors are acquired by adding their symbols to a download pairs file and running `zcrypto data download`:
- **`TRADING`** targets (FTT, LUNA, LUNC) extend to today as usual.
- **`BREAK`** targets (WAVES, DASH, ZEC, …) are fetched **archive-only** over their real `[listing, delisting]` range via the existing non-`TRADING` discovery; `instruments/all.txt` records the real range (TO < today).

Once present, qlib returns each pair's rows only within `[listing, delisting]` → the **point-in-time membership comes for free** the moment a future experiment iteration adds the pair to a recipe's `universe`. (That universe change is out of scope here.)

## Verify

`verify_dataset` must treat an archive-only delisted pair (`TO < today`, no recent data) as **valid** — its absence from the recent calendar is expected, covered by the surviving pairs (the interior-gap completeness check keys on whole-calendar coverage by *any* pair). It reports the pair's range as coverage evidence. This is likely already true for `BREAK`/archive-only pairs; the iteration adds a confirming test (today's 19 are all `TRADING`, so a `TO<today` pair may be untested).

## Scope & deferred

- **In:** acquiring the curated blown-up majors via the existing `download` (data-population); a confirming `verify` test (+ a coverage line if needed); the `delist`→`drop` rename; a `verify` run as data-ready evidence.
- **Out (future dedicated iterations — the experiment-side de-bias):** expand each `recipe.universe` to include the delisted majors (PIT membership); the **delisting-loss** model (liquidate held delisting positions at last available close); the **re-measure** (PIT universe vs survivor universe verdict that quantifies the bias and flips `T0005` → resolved).
- **Out (downstream, now data-enabled):** `T0007`'s multi-window × LUNA/FTX crisis-stress harness.
- **Dropped (per RECON / YAGNI):** the not-in-`exchangeInfo` acquisition enhancement (no consumer — Binance keeps delisted symbols as `BREAK`).
- **Untouched:** the experiment/recipe/strategy layers; the surviving pairs' acquisition; the universe/recipe tuples; the acquisition pipeline (only `delist`→`drop` renamed). (`drop`'s delete *mechanics* are unchanged.)

## Closeout tasks (authored when the work is real)

- Flip `T0005` → `partial`: `## Done so far` records the data substrate (the curated delisted majors acquired with real ranges; the `delist`→`drop` rename; the RECON that Binance keeps delisted symbols as `BREAK`); `## Suggested next steps` trimmed to the experiment-side remainder (PIT-universe selection, delisting-loss = last-close, re-measure → resolved).
- Note on `T0007`: its LUNA/FTX crisis pass is now data-enabled (no longer survivor-only).
- README `## Usage`: the dataset can include delisted (`BREAK` / archive-only) majors; `delist` is **renamed → `drop`** (repurposed pair-removal).
- A `verify` run confirming the delisted majors' coverage (the "data ready" evidence — each pair's listing→delisting range); iter-16 iterations-history entry.
