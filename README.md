# Does Code Complexity Predict When Smart-Contract Vulnerability Detectors Fail?

A follow-up study to *Assessing Vulnerability in Smart Contracts: The Role of Code
Complexity Metrics in Security Analysis* (arXiv:2411.17343), which asked whether
complexity metrics predict **the presence of vulnerabilities**.

This study asks the inverted, practitioner-facing question:

> Given that a vulnerability exists, does the complexity of the surrounding code
> predict whether an automated detector will **find** it?

The distinction matters. Complexity predicting *bugs* tells a developer what to
rewrite. Complexity predicting *detector failure* tells an auditor **where not to
trust the tool** — which is directly actionable, and is what the triage model at
the end of the pipeline quantifies.

---

## Why this question is still open

Recent work established that detectors do poorly on real-world code:

- **Durieux et al. (ICSE'20)** — 47,587 contracts, 9 tools.
- **DAppSCAN (TSE'24)** — tools perform poorly on real DApp projects.
- **Salzano et al. (EMSE'26)** — 20 tools, 2,182 line-level manually annotated
  instances; ChatGPT-4o degrades sharply on real-world versus curated contracts.

None of them models *which complexity properties* drive failure. Salzano's
replication package even ships a per-contract cyclomatic complexity file, but
their statistical analysis (`stat_test.py`) is only Fisher's exact tests
comparing tool coverage — complexity is never used as a predictor.

**That gap is this study.** The prior paper contributes the validated 21-metric
instrument; Salzano contributes 40,252 detection outcomes. Joining them is new.

---

## Data provenance

| Layer | Source | Ours or theirs |
|---|---|---|
| Detection outcomes, 19 tools × 2,167 contracts | Salzano et al. (EMSE'26) replication package | **theirs** — cite |
| Line-level manual ground truth (DASP-10) | Salzano et al. | **theirs** — cite |
| Tool-check → DASP category mapping | Salzano et al. | **theirs** — cite |
| SWC ground truth from 1,199 audit reports | DAppSCAN (TSE'24) | **theirs** — cite |
| Audit findings from 6,571 projects (CWE) | FORGE (ICSE'26) | **theirs** — cite |
| 21 Solmet complexity metrics | this repo (`sccomplex/metrics/solmet.py`) | **ours** |
| Slither runs on DAppSCAN | this repo (`sccomplex/detect/`) | **ours** |
| Panel construction, statistical models, triage model | this repo | **ours** |

The contribution is the *model*, not the measurement. This must be stated
plainly in the paper.

---

## Reproducing from a clean checkout

```bash
# 1. environment (pinned)
conda create -y -n scvul python=3.11
PYTHONNOUSERSITE=1 ~/miniconda3/envs/scvul/bin/python -m pip install -r requirements.txt

# 2. fetch external corpora (~150 MB; not committed)
./run.sh scripts/01_fetch_data.py

# 3. pipeline
./run.sh scripts/02_extract_metrics.py     # 21 metrics for 8,413 contracts
./run.sh scripts/03_validate_metrics.py    # external check vs Slither
./run.sh scripts/04_build_panel.py         # build the two analysis panels
./run.sh scripts/05_model.py               # RQ1-RQ4
./run.sh scripts/06_robustness.py          # RQ5  do the signs survive?
./run.sh scripts/07_triage.py              # RQ6  audit triage model

# external validity (optional; needs slither + solc-select + ~35 min)
PYTHONNOUSERSITE=1 ~/miniconda3/envs/scvul/bin/python -m pip install slither-analyzer solc-select
./run.sh scripts/01_fetch_data.py --with-dappscan
./run.sh scripts/10_vendor_deps.py         # vendor npm deps (+60% analysable)
./run.sh scripts/08_dappscan_detect.py --remap   # Slither on 801 audited contracts
./run.sh scripts/09_dappscan_replicate.py  # RQ7  do the findings replicate?
./run.sh scripts/11_dappscan_mythril.py --remap --workers 16   # symbolic executor
./run.sh scripts/12_c2_symbolic.py         # RQ8  symbolic vs static interaction

# third corpus (optional; needed for RQ9)
./run.sh scripts/01_fetch_data.py --with-forge
./run.sh scripts/13_forge_reentrancy.py --workers 24 --max-files 20

# tests
./run.sh -m pytest tests/ -q
```

`run.sh` addresses the interpreter by absolute path and sets
`PYTHONNOUSERSITE=1`. This is deliberate: `conda activate` silently failed to
switch environments during development and installs landed in an unrelated env.
Override with `SCVUL_PYTHON=/path/to/python ./run.sh ...`.

Nothing under `data/` is committed. Everything there is reconstructed by
steps 2–3 above.

---

## Design decisions that differ from the naive approach

Each of these was a bug in the first prototype and is now a deliberate choice.

**Unit of analysis is (vulnerability instance × tool), not contract.**
A contract-level "did the tool get everything right" flag collapses "missed one
of five bugs" into "found nothing", destroys outcome variance, and yields
degenerate all-zero regressions. Per-instance gives 63,783 observations with
real variance.

**Analysis failure is separated from detection failure.**
17.6% of tool runs crash or time out. Folding those into "missed" conflates a
tool that never ran with one that ran and missed. They are modelled separately —
and they behave *oppositely*, which is the study's main finding.

**Two matching semantics, both reported.**
`detected_category` (right category anywhere in the contract; the Durieux and
Salzano protocol, and the only option for the 21% of findings with no line
information) and `detected_line` (within ±5 lines). They disagree: 23.5% vs 13.5%.

**Tool and category fixed effects are mandatory.**
Detection rates range from 82% (conkas) to 0% (teether). Without conditioning on
tool, a "complexity" coefficient mostly encodes which tools ran on what.

**Standard errors clustered by contract.**
One contract contributes up to 19 rows; treating them as independent badly
understates standard errors.

**Degenerate fixed-effect levels are dropped and reported, not silently fitted.**
Five tools detect nothing at all. Their dummies perfectly predict the outcome,
producing a singular Hessian. *This* is the true source of the "perfect
separation" warnings that a naive fit produces — it is not evidence of a
complexity threshold.

**Metrics are screened for redundancy before modelling.**
Paper 1 established these 21 metrics are highly collinear. Feeding all of them
to one model produces unstable, uninterpretable coefficients.

---

## Results

### RQ1 — Are the metrics redundant on this corpus?

Yes, and the structure **independently replicates Paper 1** on a different
corpus: 12 pairs at |ρ| ≥ 0.9.

```
DIT~NOD 0.989   NL~NLE 0.988   AvgMcCC~AvgNL 0.980   AvgNL~AvgNLE 0.962
AvgMcCC~AvgNLE 0.950   DIT~NOA 0.937   NOA~NOD 0.935   WMC~NOS 0.922
LLOC~WMC 0.920   LLOC~NOS 0.915   LLOC~NF 0.913   NF~WMC 0.902
```

21 metrics → **13 non-redundant**: SLOC, LLOC, CLOC, NL, NUMPAR, NOA, CBO, NA,
NOI, AvgMcCC, AvgNUMPAR, AvgNOS, AvgNOI.

### RQ2 — Does complexity predict a *missed bug*?

Barely. 51,090 observations, miss rate 76.5%, pseudo-R² 0.296 (mostly the fixed
effects).

| metric | coef | odds ratio | p |
|---|---:|---:|---:|
| AvgNUMPAR | +0.362 | 1.44 | 0.0002 |
| CBO | +0.131 | 1.14 | 0.025 |
| CLOC | +0.130 | 1.14 | 0.002 |
| NOA | +0.090 | 1.09 | 0.012 |
| SLOC | −0.081 | 0.92 | 0.267 |
| LLOC | +0.122 | 1.13 | 0.386 |
| NUMPAR | −0.595 | 0.55 | 0.001 |

**Contract size is not significant.** Only coupling (CBO), inheritance (NOA),
comment density (CLOC) and parameters-per-function are, with small effects.

### RQ3 — Does complexity predict the tool *crashing*?

Strongly. 40,252 runs, failure rate 17.6%.

| metric | coef | odds ratio | p |
|---|---:|---:|---:|
| NOI | +0.911 | **2.49** | 0.0002 |
| AvgNOS | +0.439 | 1.55 | <0.0001 |
| SLOC | +0.314 | 1.37 | 0.003 |
| NOA | +0.180 | 1.20 | <0.0001 |
| NL | +0.127 | 1.14 | 0.021 |
| AvgNOI | −0.538 | 0.58 | <0.0001 |
| CBO | −0.257 | 0.77 | <0.0001 |

> **Complexity predicts detectors crashing far more than it predicts them
> missing bugs.** One SD of outgoing invocations ≈ 2.5× the odds of a crash.

### RQ4 — Is the effect universal across tools?

**No — but only some of the variation survives scrutiny.** Per-tool LLOC slopes
on detection failure, before robustness checks (negative = *better* on more
complex code):

```
  slither      -0.625  p<0.001      securify     +0.057  ns
  smartcheck   -0.578  p<0.001      mythril      +0.154  ns
  solhint      -0.550  p<0.001      osiris       +0.208  ns
  sfuzz        -0.353  p=0.002      oyente       +0.251  ns
  vandal       -0.132  ns           conkas       +0.781  p<0.001
```

By detector class:

| class | detection failure | analysis failure | reading |
|---|---:|---:|---|
| symbolic | **+0.111** (p=0.002) | **+0.126** (p<0.001) | state explosion — hurt both ways |
| static | −0.182 (p<0.001) | +0.192 (p<0.001) | scales on detection, crashes more |
| linter | −0.118 (p<0.001) | −0.387 (p<0.001) | improves on both |
| fuzzing | −0.183 (p=0.049) | −0.094 (p=0.018) | improves on both |

### RQ5 — Do those signs survive robustness checks?

`scripts/06_robustness.py` runs four independent checks: (A) control for bugs
per contract, (B) restrict to single-bug contracts, (C) estimate within each
vulnerability category, (D) re-run on the arithmetic-excluded annotation set.

**Label density is not a confound in the pooled model** — the density term is
itself insignificant (+0.021, p=0.38) and coefficients barely move.

**But three tools flip sign and must not be reported:**

| | baseline | single-bug | no arithmetic | verdict |
|---|---:|---:|---:|---|
| conkas | +0.781 | +0.846 | +0.870 | **stable** |
| solhint | −0.550 | −0.926 | −0.615 | **stable** |
| smartcheck | −0.578 | −0.765 | −0.027 | **stable** |
| sfuzz | −0.353 | −0.523 | −0.454 | **stable** |
| **slither** | −0.625 | −0.433 | **+0.093 (ns)** | **FLIPS** |
| securify | +0.057 | −0.043 | +0.064 | FLIPS |
| confuzzius | −0.183 | −0.062 | +0.935 | FLIPS |

Slither's apparent "gets better on complex code" **was an arithmetic-label
artefact** and does not survive. Nine of twelve tools are sign-stable.

**The mechanism is category-specific, and that is the real finding.** Within
vulnerability categories:

| category | LLOC slope | p | n |
|---|---:|---:|---:|
| reentrancy | **+0.278** | 0.0001 | 1,405 |
| front_running | +0.419 | 0.36 | 217 |
| time_manipulation | +0.031 | 0.24 | 14,107 |
| unchecked_low_calls | +0.030 | 0.34 | 7,190 |
| denial_service | −0.029 | 0.55 | 3,990 |
| access_control | −0.045 | 0.52 | 1,440 |
| arithmetic | **−0.172** | <0.0001 | 22,195 |
| bad_randomness | −0.258 | <0.0001 | 529 |

**Reentrancy detection degrades with complexity; arithmetic detection
improves.** Because arithmetic is 39% of all annotations, it drags every pooled
per-tool estimate negative. This — not tool identity — is what generates the
apparent sign flips.

So the defensible claim is:

> "Complexity is the enemy of automated detection" is false as a blanket claim.
> The direction depends on the **vulnerability class**: complexity hurts
> reentrancy detection and helps arithmetic detection. Pooled estimates are
> dominated by whichever class is most numerous in the benchmark, which is why
> prior work reports inconsistent results.

### RQ6 — Can this be turned into an audit triage model?

Yes. `scripts/07_triage.py` predicts, out of sample (grouped 5-fold), whether a
contract is a blind spot for the deployed tool set.

| deployed tools | missed bugs | AUC |
|---|---:|---:|
| slither | 52.6% | **0.915** |
| slither + mythril | 47.2% | 0.890 |
| slither + conkas + smartcheck | 9.7% | 0.798 |
| all 19 | 3.5% | 0.706 |

Share of Slither-missed bugs captured, **budget measured in contracts
reviewed**:

| strategy | @5% | @10% | @25% | @50% |
|---|---:|---:|---:|---:|
| **complexity model** | **7.9** | **15.8** | **40.2** | **76.7** |
| largest first | 3.1 | 6.8 | 25.1 | 61.7 |
| smallest first | 3.0 | 6.2 | 25.2 | 38.3 |
| random | 5.3 | 10.0 | 26.2 | 51.4 |

Roughly **1.5× random at every budget**, and it beats both free heuristics
everywhere.

**Caveat that must appear in the paper.** Under a *lines-of-code* budget instead,
"review the smallest contracts first" beats the model (23.1% vs 2.8% at 5% LOC).
That is a degenerate exploit of the cost function: charging only for lines makes
tiny contracts free, so the strategy harvests one bug per contract at almost no
cost, ignoring the fixed cost of picking up a contract at all. Real audit effort
lies between the two cost models. Reporting only the LOC curve — as the earlier
prototype did, with no baselines — would have been misleading.

---

### RQ7 — Do the findings replicate on an independent corpus?

**Mostly no.** This is the most important result in the repository and it is a
negative one.

Replication target: DAppSCAN — 801 contracts from 415 real DApp projects,
labelled by professional auditors from 1,199 audit reports. Materially more
complex than the main corpus (median SLOC 246 vs 127, median NOI 42 vs 16) and
with a different category mix (arithmetic 22% vs 39%). Detector: Slither, using
Salzano's identical tool→DASP mapping.

Run outcomes over 801 contracts, after vendoring the OpenZeppelin family that
DAppSCAN does not ship (`scripts/10_vendor_deps.py`): **440 ok, 66 error, 295
unresolved imports**. Vendoring raised the analysable set from 275 to 440
(+60%) and usable vulnerability instances from 309 to 477.

| claim | main corpus | DAppSCAN | verdict |
|---|---|---|---|
| C3 metric redundancy structure | 12 pairs ρ≥0.9 | 13 pairs, same families | **replicates** |
| C2 complexity → analysis failure (Slither) | NOI +0.911, p=0.0002 | NOI +0.204, p=0.12 | **not replicated** |
| C2 symbolic vs static split (Mythril, RQ8) | symbolic > static | NOA interaction p=0.006 | **replicates** |
| C1 reentrancy detection degrades | **+0.278**, p=0.0001 | **−0.834**, p=0.041 | **sign reverses** |
| C1 arithmetic detection improves | −0.172, p<0.0001 | −0.290, p=0.40 | same sign, n.s. |

**C3 replicates cleanly.** The same redundancy families reappear: `NL~NLE`
(0.969), `AvgMcCC~AvgNL~AvgNLE`, `LLOC~WMC~NOS~NF`, `SLOC~LLOC` (0.975). Three
corpora now agree that the 21 metrics carry roughly 13 metrics of information.

**C2 does not replicate at the metric level.** With 506 usable Slither runs the
only significant term is CBO (+0.251, p=0.033) — and CBO's coefficient in the
main corpus was *negative* (−0.257). NOI, which carried the main corpus's
strongest effect (+0.911, OR 2.49), is null here (+0.204, p=0.12).

But this was never the right test. In the main corpus the
analysis-failure effect was driven by *symbolic* executors (manticore +1.03,
ethor-2023 +1.36); Slither's own slope was **negative** (−0.384), so a
Slither-only replication cannot test the symbolic-execution claim at all.
**RQ8 below runs Mythril on the same contracts and does test it — and the
class-level claim replicates.**

**C1 does not replicate, and C1 was the headline.** Reentrancy detection
degrades with complexity in the main corpus (+0.278) and *improves* in DAppSCAN
(−0.834), both individually significant.

This survived the obvious objection. On the first pass the DAppSCAN estimate
rested on 34 instances with 5 misses, which is too thin to trust. After
vendoring dependencies it rests on **62 instances with 9 misses**: the
coefficient regressed toward zero as expected with more data (−1.74 → −0.83)
but stayed significantly negative. The reversal is not simply underpowering.

Remaining caveats:

- Slither misses only 14.5% of DAppSCAN reentrancy labels versus far more in
  the main corpus, so the corpora are not measuring equal difficulty.
- Ground-truth provenance differs fundamentally: researcher pattern-matching
  plus review versus paid auditors reading real code.
- 9 misses is still small. A third corpus would settle it.

The defensible conclusion is weaker than the one the main corpus suggested:

> Complexity effects on detector reliability are **corpus-dependent and do not
> transfer**. Only the redundancy structure of the metrics is stable. Any claim
> that a specific complexity metric predicts detector failure must be scoped to
> the corpus it was measured on — which is itself a plausible explanation for
> why the existing literature disagrees about whether complexity hurts
> detection.

### RQ8 — C2 retested with a symbolic executor

C2 could not be judged from the Slither-only replication, because C2 was a
claim about *symbolic execution* and Slither is a static analyser. Mythril was
therefore run over the same 801 DAppSCAN contracts
(`scripts/11_dappscan_mythril.py`, 60s symbolic budget held constant, 16
workers). Outcomes: **392 ok, 293 unresolved imports, 92 error, 24 timeout**.

**The class-level prediction holds.** On identical contracts:

| tool | class | analysis-failure rate | runs |
|---|---|---:|---:|
| mythril | symbolic | **22.8%** | 508 |
| slither | static | 13.0% | 506 |

**And the difference is specifically about inheritance.** Two separate slopes
with opposite signs is suggestive but not a test, so the claim — "symbolic
executors degrade with complexity where static analysers do not" — is tested as
an interaction, clustered by contract:

| metric | slither slope | mythril − slither | p (interaction) |
|---|---:|---:|---:|
| **NOA** (ancestors) | −0.187 | **+0.384** | **0.0059** |
| **DIT** (inheritance depth) | −0.034 | **+0.309** | **0.0295** |
| NA | +0.155 | −0.160 | 0.25 |
| NOD | +0.131 | +0.147 | 0.29 |
| NOI | +0.204 | −0.137 | 0.34 |
| SLOC | +0.146 | −0.080 | 0.59 |
| CBO | +0.247 | −0.021 | 0.86 |

Only the two inheritance metrics differ significantly between the tool classes.
Size, coupling and invocation counts affect both equally — CBO raises failure
odds for both, so it is not a symbolic-execution effect at all.

This is mechanistically coherent: deep inheritance multiplies virtual-dispatch
targets and reachable paths, which is exactly what makes a symbolic executor
explode, while a static analyser simply walks more AST. And NOA agrees in sign
and significance with the main corpus (+0.180, p<0.0001).

**Verdict on C2: the class-level claim replicates, the metric-level claim does
not.** NOI — the main corpus's strongest single effect, odds ratio 2.49 — is
null for Mythril here (+0.067, p=0.55). What transfers is the *shape* of the
finding:

> Symbolic executors fail to complete more often than static analysers on the
> same code, and inheritance structure is what separates them. Which individual
> metric carries the effect is corpus-dependent and should not be reported as a
> stable result.

This is the study's one positive cross-corpus finding, and it is a claim about
detector *classes*, not about individual metrics.

### RQ9 — A third corpus withdraws the category-specific mechanism

The reentrancy result carried the C1 claim and rested on 9 misses, so we added
FORGE (ICSE'26): 6,571 audited projects, of which **350 carry a reentrancy
finding**. Scoring is per project and deliberately generous — detected if
Slither flags reentrancy in *any* file — because FORGE findings carry free-text
locations, not line numbers. Generosity biases *against* the
"complexity-hurts-detection" hypothesis, the conservative direction here.

133 of 350 projects had an analysable file (median project SLOC 1,696). Slither
missed **76.7%** of audit-reported reentrancy.

| corpus | ground truth | n | LLOC coef | p |
|---|---|---:|---:|---:|
| Salzano (main) | researcher annotation | 1,405 | **+0.278** | **0.0001** |
| DAppSCAN | human report extraction | 62 | **−0.834** | **0.041** |
| FORGE | LLM report extraction | 133 | −0.314 | 0.105 |

**Three corpora, two signs, no consistent effect.** The category-specific
mechanism is **withdrawn**: reentrancy detection neither reliably degrades nor
improves with complexity — the effect is not identifiable across corpora.

Two observations recorded as hypotheses, not findings:

- In FORGE, coupling predicts *better* reentrancy detection, strongly (CBO
  −0.635 p=0.002; NA −0.472 p=0.029; NUMPAR −0.459 p=0.044). Pattern-based
  detectors fire on trigger sites, so code with more external calls may yield
  more true positives mechanically — making "complexity helps detection" an
  artefact of detector design.
- With n=3 corpora, the sign appears to track **label provenance** (researcher
  annotation positive, audit-report extraction negative) rather than corpus
  size or category mix. Too weak to advance; noted for future work.

### Sample loss in source-based tool evaluation

Before dependencies were vendored, the analysable subsample looked strongly
complexity-biased (SLOC p=0.017, NF p=2.0e-5, CBO p=3.7e-18). **That bias was
mostly an artefact of the missing dependencies, not a property of the corpus.**
With the OpenZeppelin family vendored it largely disappears:

| metric | analysable median | not analysable | p (vendored) | p (before) |
|---|---:|---:|---:|---:|
| SLOC | 245 | 249 | 0.997 | 0.017 |
| LLOC | 158 | 161 | 0.753 | 0.081 |
| NF | 17 | 14 | 0.269 | 2.0e-5 |
| CBO | 0 | 0 | **1.6e-5** | 3.7e-18 |

The practical lesson is narrower than "compilability is complexity-dependent",
which is what the un-vendored numbers appeared to show. It is:

> Unresolved build dependencies silently delete a **complexity-correlated** 37%
> of a real-world corpus. Vendoring them removes almost all of that bias. Any
> tool evaluation on real projects should report its compile-failure rate and
> test it against complexity — and should vendor dependencies before concluding
> anything about tool coverage.

Residual coupling (CBO) bias remains significant and should be declared as a
threat to validity.

---

## Verification

The metric extractor is a tree-sitter reimplementation of Solmet (the Java
original fails on modern Solidity, and Slither-based extraction requires
successful compilation — which biases the sample, since compilability correlates
with complexity). It is checked two ways:

- **Unit tests** (`tests/test_solmet.py`) against hand-computed values on a
  reference contract, including a regression test for per-file inheritance
  scoping. A corpus-wide name-keyed graph merges every `Ownable` in the corpus
  into one node and reported NOD in the hundreds; this is now scoped per
  compilation unit.
- **External validation** (`scripts/03_validate_metrics.py`) against Salzano's
  independently computed Slither cyclomatic complexity:
  **Spearman ρ = 0.930** (n=414, p≈8e-182). Levels differ (Slither's CFG counts
  short-circuit and implicit branches) but rank agreement is what the modelling
  relies on.

Known deviations from Solmet are documented in `DEVIATIONS` in
`sccomplex/metrics/solmet.py` and must be reported as threats to validity.

---

## Corpus

2,167 contracts, 8,413 contract declarations, 1,829 annotated vulnerability
instances.

| corpus | contracts |
|---|---:|
| smartbugs_results (real-world) | 1,083 |
| zeus_vulnerable | 257 |
| smartbugs_curated | 138 |
| zeus_safe | 44 |

| category | instances |
|---|---:|
| arithmetic | 716 |
| time_manipulation | 507 |
| unchecked_low_calls | 263 |
| denial_service | 153 |
| access_control | 84 |
| reentrancy | 77 |
| bad_randomness | 15 |
| front_running | 13 |

SLOC: median 127, IQR 89–212, 95th pct 735, max 3,445 — genuine complexity
spread, unlike SmartBugs-Curated alone (Q1 = 14–27 lines).

---

## Status and next steps

Done: metric extraction and external validation, panel construction, RQ1–RQ6
(redundancy, detection failure, analysis failure, tool heterogeneity,
robustness, triage model).

**Open:**

1. **A third corpus.** Dependency vendoring took the DAppSCAN reentrancy
   estimate from 5 to 9 misses and the reversal held, but 9 is still thin.
   Vendoring the remaining non-OpenZeppelin packages (uniswap, aragon, 0x,
   chainlink) would recover part of the 295 still-unresolved contracts.
2. **A genuinely trained neural detector.** Salzano covers static, symbolic,
   fuzzing, linters and an LLM, but no learned model — this is the one detector
   class that would be an original measurement rather than reuse.
3. **LLM detector done properly** (full file, constrained label set, repeated
   runs at temperature 0), with a contamination threat-to-validity: these
   contracts are public and almost certainly in training data.
4. Rewrite the manuscript draft against these numbers. The current draft in
   `New_Smart_Contract.ipynb` asserts findings that this pipeline contradicts.

**Do not report without re-checking:** slither, securify and confuzzius
detection slopes (sign-unstable across specifications).

## Manuscript

The draft is [`paper/draft.md`](paper/draft.md). Every number in it is produced
by this pipeline and traceable to a CSV in `results/tables/`; a verification
script checks all 55 numeric claims against those tables.

Claims that did not survive robustness or replication testing are reported as
negative results rather than dropped — including two the authors initially
believed (Slither's detection slope, and an apparent complexity bias in
compilability).

## Repository layout

```
sccomplex/
  config.py            paths, the 21 metric names, detector-class map
  metrics/solmet.py    tree-sitter metric extractor (compilation-free)
  data/salzano.py      replication-package loader + finding parser
  panel.py             analysis panels, dual matching semantics
  model.py             clustered logit, redundancy screening, per-group slopes
sccomplex/
  data/dappscan.py     DAppSCAN loader, SWC -> DASP mapping
  detect/              Slither runner + DASP normalisation
scripts/               01 fetch -> 02 extract -> 03 validate -> 04 panel
                       -> 05 model -> 06 robustness -> 07 triage
                       -> 08 dappscan detect -> 09 dappscan replicate
                       -> 10 vendor deps (run before 08 --remap)
                       -> 11 dappscan mythril -> 12 c2 symbolic-vs-static
tests/                 hand-verified extractor tests
results/tables/        committed CSVs backing every number above
run.sh                 pinned interpreter entry point
```
