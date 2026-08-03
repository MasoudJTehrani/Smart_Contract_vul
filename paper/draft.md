# Complexity and Detector Failure in Smart Contracts: A Cross-Corpus Replication

**Draft manuscript.** Every number in this draft is produced by the pipeline in
this repository and traceable to a CSV in `results/tables/`. Claims that did not
survive robustness or replication testing are reported as such rather than
omitted.

---

## Abstract

Automated vulnerability detectors are the first line of defence for Solidity
smart contracts, yet they miss a large share of real defects. A natural
hypothesis, inherited from four decades of software-engineering research, is
that code complexity explains where they fail. We test that hypothesis at scale
and find it is mostly wrong, and wrong in an instructive way.

Using 21 validated complexity metrics, we model **63,783 detection outcomes**
(1,829 annotated vulnerabilities × 19 tools) and **40,252 tool runs** drawn from
the replication package of Salzano et al., then attempt to replicate every
finding on an independent corpus of 801 contracts from 415 professionally
audited DApp projects.

Five results. First, detector failure is **not one phenomenon**: whether a tool
crashes and whether a tool misses a bug have different, sometimes opposite,
complexity signatures, and conflating them — as prior work does — destroys the
signal. Second, contract **size does not predict missed bugs** (SLOC p=0.267);
only coupling, inheritance and parameters-per-function do, weakly. Third, almost
every metric-level association we find **fails to replicate** across corpora,
including two we initially reported; a category-specific mechanism that looked
significant in the main corpus is withdrawn entirely after testing on two
further corpora with 350 and 801 audited projects. Fourth, the one finding that does
replicate is a claim about detector *classes*: **symbolic executors fail to
complete far more often than static analysers** (22.8% vs 13.0% on identical
contracts), and the property that separates them is **inheritance structure**
(NOA interaction p=0.006; DIT p=0.030), not size, coupling or invocation count.

We conclude that "complexity is the enemy of automated detection" is not a
defensible general claim for smart contracts, and that the instability of
metric-level results across corpora is itself the likely explanation for
disagreement in the existing literature.

---

## 1. Introduction

Smart contracts hold substantial value and cannot be patched after deployment,
so pre-deployment analysis carries unusual weight. Dozens of detectors exist,
and several large studies now agree that they perform poorly on real-world code
[Durieux et al. 2020; Zheng et al. 2024; Salzano et al. 2026]. What none of
them answer is the question a practitioner actually has:

> Given that a vulnerability exists, can I predict **from the code itself**
> whether my detector will find it?

An answer would be directly actionable. It would tell an auditor where the
scanner is blind and where to spend a limited manual budget. The natural
candidate predictor is code complexity, which has been linked to defects since
McCabe (1976) and to vulnerabilities specifically by Shin and Williams (2008)
and Chowdhury and Zulkernine (2011). Prior work by the present authors
established that 21 complexity metrics discriminate vulnerable from neutral
Solidity contracts, though no single metric correlates strongly (all ρ < 0.19).

This paper inverts that question. Rather than asking whether complexity predicts
*the presence of a bug*, we ask whether it predicts *the failure of a tool to
find one*. We treat the answer as an empirical question to be tested rather than
a hypothesis to be confirmed, and we report the substantial parts of it that
came out negative.

**Contributions.**

1. A decomposition of "detector failure" into **analysis failure** (the tool
   crashed or timed out) and **detection failure** (the tool ran and missed the
   bug), which behave differently and must be modelled separately.
2. A per-instance statistical model of 63,783 detection outcomes across 19
   tools, with tool and vulnerability-category fixed effects and standard errors
   clustered by contract.
3. A four-way robustness protocol that overturns one of our own initial
   findings, and replication on two further corpora that overturns two more.
4. The one finding that survives all of it: a **detector-class** effect in which
   symbolic executors are defeated by inheritance structure specifically.
5. A practical triage model (AUC 0.915), reported with the honest caveat that it
   is corpus-specific tooling rather than a general law.
6. Evidence that unresolved build dependencies silently delete a
   complexity-correlated 37% of a real-world corpus — a methodological hazard
   for every source-based tool evaluation.

---

## 2. Background and Related Work

**Tool evaluations.** Durieux et al. (ICSE 2020) ran 9 tools over 47,587
contracts and reported low recall. Ghaleb and Pattabiraman (ISSTA 2020) used
injected bugs to show systematic blind spots. Zheng et al. (TSE 2024)
constructed DAppSCAN from 1,199 professional audit reports and found tools
perform poorly on real DApp projects. Salzano et al. (EMSE 2026) evaluated 20
tools against 2,182 manually annotated, line-level instances and observed sharp
degradation from curated to real-world contracts.

**The gap.** All of these establish *that* detectors fail. None model *what
property of the code* predicts failure. Salzano et al. compute a per-contract
cyclomatic complexity file but never use it as a predictor; their statistical
analysis consists of Fisher's exact tests comparing tool coverage. This study
occupies exactly that gap.

**Complexity and defects.** The link between complexity and defects is
well-established in traditional languages. Whether it transfers to Solidity is
unclear a priori: contracts are small, gas costs discourage deep control flow,
and the dominant defect classes (reentrancy, oracle manipulation) are
architectural rather than control-flow-local.

---

## 3. Research Questions

| RQ | Question |
|---|---|
| RQ1 | Are the 21 complexity metrics redundant on this corpus? |
| RQ2 | Does complexity predict a *missed bug*? |
| RQ3 | Does complexity predict a *tool crash*? |
| RQ4 | Is any such effect universal across tools and detector classes? |
| RQ5 | Do the observed signs survive robustness checks? |
| RQ6 | Can the relationship be turned into an audit triage model? |
| RQ7 | Do the findings replicate on an independent corpus? |
| RQ8 | Does the detector-class effect replicate when tested directly? |
| RQ9 | Does the reentrancy effect survive a third, larger corpus? |

---

## 4. Study Design

### 4.1 Corpora

| | Main corpus | Replication 1 | Replication 2 |
|---|---|---|---|
| source | Salzano et al. (EMSE 2026) | DAppSCAN (TSE 2024) | FORGE (ICSE 2026) |
| units | 2,167 contracts | 801 contracts | 350 projects |
| provenance | Etherscan + SmartBugs + Zeus | 415 audited DApp projects | 6,571 audited projects |
| ground truth | manual, line-level, DASP-10 | 1,199 audit reports, SWC | 27,495 LLM-extracted findings, CWE |
| label granularity | line | line | free-text location |
| annotated bugs | 1,829 | 941 | 1,200 (6 DASP classes) |
| median SLOC | 127 | 246 | 1,696 (project) |

The three differ in provenance, taxonomy, granularity and scale. FORGE is used
only for RQ9, where its 350 reentrancy projects settle a question the other two
corpora answer inconsistently.

### 4.2 Complexity metrics

We compute the 21 Solmet metrics (Hegedűs 2019) used in our prior work. Solmet
itself fails on modern Solidity, and Slither-based extraction requires successful
compilation — which biases the sample, because compilability correlates with
project structure. We therefore reimplemented the metrics over a tree-sitter
Solidity grammar, which parses without compiling.

**Validation.** Against Salzano's independently computed, Slither-based
cyclomatic complexity on 414 shared contracts: **Spearman ρ = 0.930**
(p ≈ 8×10⁻¹⁸²). Absolute levels differ, as expected — Slither's CFG counts
short-circuit and implicit branches that AST decision-point counting does not —
but rank agreement is what the modelling relies on. The extractor is also unit
tested against hand-computed values on a reference contract.

### 4.3 Outcome definitions

The prototype for this study used a contract-level flag: "did the tool get
everything right." That collapses "missed one of five bugs" into "found
nothing", destroys outcome variance, and yields degenerate all-zero regressions.
We instead use:

- **Detection panel** — one row per (vulnerability instance × tool): 63,783
  rows. Outcome: was *this* bug found.
- **Run panel** — one row per (contract × tool): 40,252 rows. Outcome: did the
  tool complete.

**Analysis failure is kept distinct from detection failure.** 17.6% of runs in
the main corpus crashed or timed out. A tool that never ran has failed
differently from one that ran and missed, and — as Section 5 shows — the two
have different complexity signatures. Crashed runs are excluded from detection
models rather than counted as misses.

**Two matching semantics are reported.** *Category match* (right vulnerability
class anywhere in the contract) follows Durieux et al. and is the only option
for the 21% of findings that carry no line number. *Line match* additionally
requires the report to land within ±5 lines. They disagree substantially: 23.5%
vs 13.5% overall.

### 4.4 Statistical models

Logistic regression of failure on standardised (log1p, then z-scored) metrics,
with:

- **tool fixed effects** — mandatory, since detection rates range from 82%
  (conkas) to 0% (teether);
- **vulnerability-category fixed effects** — categories differ enormously in
  detectability and their mix varies with contract size;
- **standard errors clustered by contract** — one contract contributes up to 19
  rows;
- **redundancy screening before fitting** — the 21 metrics are highly collinear
  and fitting them jointly produces unstable coefficients.

**A note on separation.** Naive fits of this data emit "perfect separation"
warnings, which a prototype of this study misread as evidence of a deterministic
complexity threshold. The true cause is mundane: five tools detect nothing at
all, so their dummies perfectly predict the outcome and the Hessian is singular.
Such levels are dropped and reported, never silently fitted.

---

## 5. Results

### RQ1 — Metric redundancy

Twelve metric pairs exceed |ρ| ≥ 0.9, and the structure reproduces our prior
work on a different corpus: `DIT~NOD` 0.989, `NL~NLE` 0.988, `AvgMcCC~AvgNL`
0.980, `NOA~NOD` 0.935, `LLOC~WMC` 0.920, `LLOC~NF` 0.913. Twenty-one metrics
carry roughly **thirteen metrics of information**.

This is the only finding in the paper that replicates on all three corpora
(prior work, main corpus, DAppSCAN: 13 pairs, same families).

### RQ2 — Complexity does not predict missed bugs

51,090 usable outcomes, miss rate 76.5%.

| metric | coef | odds ratio | p |
|---|---:|---:|---:|
| AvgNUMPAR | +0.362 | 1.44 | 0.0002 |
| CBO | +0.131 | 1.14 | 0.025 |
| CLOC | +0.130 | 1.14 | 0.002 |
| NOA | +0.090 | 1.09 | 0.012 |
| SLOC | −0.081 | 0.92 | **0.267** |
| LLOC | +0.122 | 1.13 | **0.386** |
| NUMPAR | −0.595 | 0.55 | 0.001 |

**Contract size — the intuition everyone holds — is not significant.** Only
coupling (CBO), inheritance (NOA), comment density (CLOC) and
parameters-per-function reach significance, all with small effects. Pseudo-R²
of 0.296 is carried mostly by the fixed effects, not by complexity.

### RQ3 — Complexity does predict crashes

40,252 runs, failure rate 17.6%.

| metric | coef | odds ratio | p |
|---|---:|---:|---:|
| NOI | +0.911 | **2.49** | 0.0002 |
| AvgNOS | +0.439 | 1.55 | <0.0001 |
| SLOC | +0.314 | 1.37 | 0.003 |
| NOA | +0.180 | 1.20 | <0.0001 |
| NL | +0.127 | 1.14 | 0.021 |
| CBO | −0.257 | 0.77 | <0.0001 |
| AvgNOI | −0.538 | 0.58 | <0.0001 |

> Complexity predicts detectors **crashing** far more strongly than it predicts
> them **missing bugs**. One standard deviation of outgoing invocations
> multiplies the odds of a crash by ≈2.5.

This outcome does not exist in prior work, which folds crashed runs into
not-found. It is only visible because the two failure modes were separated.

### RQ4 — The effect is not universal

Per-detector-class LLOC slopes:

| class | detection failure | analysis failure |
|---|---:|---:|
| symbolic | +0.111 (p=0.002) | +0.126 (p<0.001) |
| static | −0.182 (p<0.001) | +0.192 (p<0.001) |
| linter | −0.118 (p<0.001) | −0.387 (p<0.001) |
| fuzzing | −0.183 (p=0.049) | −0.094 (p=0.018) |

Symbolic execution is the only class harmed in both dimensions. Static analysers
appear to get *better* at detection as code grows while crashing more often.

### RQ5 — Robustness: one of our own findings does not survive

Larger contracts carry more annotated bugs, skewed toward common, easily
detected classes. We ran four checks: (A) control for bugs-per-contract, (B)
restrict to single-bug contracts, (C) estimate within vulnerability category,
(D) re-run on the arithmetic-excluded annotation set.

Label density is *not* a confound in the pooled model (+0.021, p=0.38). But
three tools flip sign across specifications:

| tool | baseline | single-bug | no arithmetic | stable |
|---|---:|---:|---:|:--:|
| conkas | +0.781 | +0.845 | +0.870 | yes |
| solhint | −0.550 | −0.926 | −0.615 | yes |
| sfuzz | −0.353 | −0.523 | −0.454 | yes |
| smartcheck | −0.578 | −0.765 | −0.027 | yes |
| **slither** | **−0.625** | −0.433 | **+0.093 (n.s.)** | **no** |
| securify | +0.057 | −0.043 | +0.064 | no |
| confuzzius | −0.183 | −0.062 | +0.935 | no |

Slither's apparently strong "improves on complex code" result is an
**arithmetic-label artefact** and vanishes when arithmetic annotations are
excluded. We report this because we initially believed it.

**The mechanism is category-specific.** Within vulnerability classes:

| category | LLOC slope | p | n |
|---|---:|---:|---:|
| reentrancy | **+0.278** | 0.0001 | 1,405 |
| arithmetic | **−0.172** | <0.0001 | 22,195 |
| bad_randomness | −0.258 | <0.0001 | 529 |
| others | n.s. | | |

Because arithmetic constitutes 39% of annotations, it drags every pooled
per-tool estimate negative. Pooled complexity coefficients are therefore
artefacts of benchmark composition.

### RQ6 — A triage model that works, with a caveat

We predict out-of-sample (grouped 5-fold) whether a contract is a blind spot for
the deployed tool set.

| deployed tools | bugs missed | AUC |
|---|---:|---:|
| slither | 52.6% | **0.915** |
| slither + mythril | 47.2% | 0.890 |
| slither + conkas + smartcheck | 9.7% | 0.798 |
| all 19 | 3.5% | 0.706 |

Share of Slither-missed bugs captured, budget in **contracts reviewed**:

| strategy | @5% | @10% | @25% | @50% |
|---|---:|---:|---:|---:|
| **complexity model** | **7.9** | **15.8** | **40.2** | **76.7** |
| largest first | 3.1 | 6.8 | 25.1 | 61.7 |
| smallest first | 3.0 | 6.2 | 25.2 | 38.3 |
| random | 5.3 | 10.0 | 26.2 | 51.4 |

Roughly 1.5× random at every budget, beating both free heuristics.

**The cost model matters and is not neutral.** Under a *lines-of-code* budget
instead, "review the smallest contracts first" beats the model (23.1% vs 2.8% at
5% LOC). That is a degenerate exploit: charging only for lines makes small
contracts free, so the strategy harvests one bug per contract while ignoring the
fixed cost of picking a contract up at all. Real audit effort lies between the
two. Studies reporting only an LOC-budget curve, without baselines, will
overstate their result.

A secondary observation: the **union of all 19 tools misses only 3.5%** of
annotated bugs. The ensemble is not blind; individual tools are weak, and the
union's real cost is false-positive volume.

### RQ7 — Most findings do not replicate

We repeated the analysis on DAppSCAN using Slither with the identical DASP
mapping. After vendoring the npm dependencies DAppSCAN does not ship, 440 of 801
contracts were analysable (up from 275 before vendoring).

| claim | main corpus | DAppSCAN | verdict |
|---|---|---|---|
| C3 redundancy structure | 12 pairs ρ≥0.9 | 13 pairs, same families | **replicates** |
| C2 complexity → crash (static) | NOI +0.911, p=0.0002 | NOI +0.204, p=0.12 | not replicated |
| C1 reentrancy degrades | **+0.278**, p=0.0001 | **−0.834**, p=0.041 | **sign reverses** |
| C1 arithmetic improves | −0.172, p<0.0001 | −0.290, p=0.40 | same sign, n.s. |

The reentrancy reversal is not a small-sample artefact: vendoring dependencies
increased the estimate's basis from 34 instances / 5 misses to 62 instances / 9
misses, and the coefficient regressed toward zero (−1.74 → −0.83) as expected
while remaining significantly negative. Section RQ9 settles it with a third
corpus.

### RQ9 — A third corpus: the reentrancy effect does not exist

Because the reentrancy result carried the C1 claim and rested on 9 misses, we
added FORGE (Shen et al., ICSE 2026): 6,571 projects with findings extracted
from real audit reports, of which **350 carry a reentrancy finding**. Scoring is
per project and deliberately generous — a project counts as detected if Slither
reports reentrancy in any of its files — because FORGE findings carry free-text
locations rather than line numbers. Generosity biases *against* the "complexity
hurts detection" hypothesis, which is the conservative direction here.

133 of 350 projects had at least one analysable file (median project SLOC
1,696). Slither missed **76.7%** of audit-reported reentrancy.

| corpus | ground truth | n | LLOC coef | p |
|---|---|---:|---:|---:|
| Salzano (main) | researcher annotation | 1,405 | **+0.278** | **0.0001** |
| DAppSCAN | human report extraction | 62 | **−0.834** | **0.041** |
| FORGE | LLM report extraction | 133 | −0.314 | 0.105 |

**Three corpora, two signs, and no consistent effect.** FORGE agrees with
DAppSCAN in direction but does not reach significance. The only significant
positive estimate is the one from the researcher-annotated corpus.

We therefore withdraw the category-specific mechanism entirely. It is not that
reentrancy detection degrades with complexity, nor that it improves: **the
effect is not identifiable across corpora at all.**

One pattern in the FORGE estimates deserves separate mention, as a hypothesis
rather than a finding. Coupling predicts *better* reentrancy detection there,
strongly (CBO −0.635, p=0.002; NA −0.472, p=0.029; NUMPAR −0.459, p=0.044). A
plausible reading is that heavily coupled DeFi protocols make many external
calls, and Slither's reentrancy detectors are pattern-triggered by external
calls, so coupling raises the true-positive rate mechanically. If so, apparent
"complexity helps detection" results are an artefact of pattern-based detectors
firing more often on code with more trigger sites — which would be worth testing
directly.

A second pattern, with n = 3 corpora, is too weak to advance as a result but is
recorded for future work: the sign of the effect tracks **label provenance**
(researcher annotation positive; audit-report extraction negative) rather than
corpus size, complexity range or category mix.

### RQ8 — The detector-class effect replicates

RQ7 could not test C2, because C2 concerns symbolic execution and Slither is a
static analyser. We therefore ran Mythril, a symbolic executor, over the same
801 contracts with a fixed 60-second symbolic budget.

On identical contracts:

| tool | class | analysis-failure rate | runs |
|---|---|---:|---:|
| **mythril** | symbolic | **22.8%** | 508 |
| slither | static | 13.0% | 506 |

Two opposite-signed slopes is suggestive, not a test. The claim is about a
*difference* of slopes, so we fit an interaction, clustered by contract:

| metric | slither slope | mythril − slither | p (interaction) |
|---|---:|---:|---:|
| **NOA** (ancestors) | −0.187 | **+0.384** | **0.0059** |
| **DIT** (inheritance depth) | −0.034 | **+0.309** | **0.0295** |
| NOD | +0.131 | +0.147 | 0.29 |
| NOI | +0.204 | −0.137 | 0.34 |
| SLOC | +0.146 | −0.080 | 0.59 |
| CBO | +0.247 | −0.021 | 0.86 |

**Only inheritance separates the classes.** Size, invocation count and coupling
affect both tools equally — CBO raises failure odds for both, so it is not a
symbolic-execution effect at all, though the per-tool slopes alone would suggest
otherwise.

This is mechanistically coherent: deep inheritance multiplies virtual-dispatch
targets and reachable paths, precisely what explodes a symbolic executor's state
space, whereas a static analyser merely walks more AST. NOA also agrees in sign
and significance with the main corpus (+0.180, p<0.0001).

**Verdict: the class-level claim replicates; the metric-level claim does not.**
NOI, the main corpus's headline effect at OR 2.49, is null for Mythril
(+0.067, p=0.55).

---

## 6. Discussion

### 6.1 What can actually be claimed

> Symbolic executors fail to complete more often than static analysers on the
> same code, and inheritance structure is what separates them. Which individual
> metric carries the effect is corpus-dependent and should not be reported as a
> stable result.

Everything weaker than that did not survive. In particular, "complexity is the
enemy of automated detection" is **not** defensible for smart contracts: size
does not predict missed bugs at all, and the category-level effect that looked
strongest in the main corpus is not identifiable once two further corpora are
brought in.

### 6.2 Why the literature disagrees

We offer instability as the explanation, and RQ9 makes the case concretely: the
same question — does reentrancy detection degrade with size? — yields +0.278
(p=0.0001), −0.834 (p=0.041) and −0.314 (p=0.105) on three corpora. Two honest
studies on two benchmarks will reach opposite conclusions without either being
wrong.

Two mechanisms plausibly contribute. First, pooled coefficients are dominated by
whichever vulnerability class a benchmark over-represents; arithmetic is 39% of
annotations in the main corpus and 22% in DAppSCAN, and it carries the opposite
sign to reentrancy. Second, and more speculatively, pattern-based detectors fire
on trigger sites, so code with more external calls yields more true positives
mechanically — which would make "complexity helps detection" an artefact of
detector design rather than a property of the code. Studies reporting pooled
complexity effects should report their category mix and their detectors'
trigger density.

### 6.3 Practical guidance

- **Choose tool class by code shape.** Deep inheritance hierarchies are where
  symbolic executors stop finishing. Pair them with a static analyser rather
  than trusting a clean symbolic run.
- **Treat a crashed run as a finding, not a blank.** 17.6% of runs in the main
  corpus never completed. Silence from a tool that timed out is not evidence of
  safety.
- **Ensembles are cheap recall.** The union of 19 tools misses 3.5% of bugs
  versus 52.6% for Slither alone. The binding constraint is triage of false
  positives, not recall.
- **Triage is worth doing but must be recalibrated per corpus.** Our model
  reaches AUC 0.915, but we make no claim it transfers.

### 6.4 A methodological hazard

Before vendoring dependencies, the analysable subsample of DAppSCAN looked
strongly complexity-biased (SLOC p=0.017, NF p=2.0×10⁻⁵). After vendoring, that
bias largely disappears (SLOC p=0.997, NF p=0.269), though coupling remains
biased (CBO p=1.6×10⁻⁵).

> Unresolved build dependencies silently delete a complexity-correlated 37% of a
> real-world corpus. Any tool evaluation on real projects should report its
> compile-failure rate, test it against complexity, and vendor dependencies
> before drawing conclusions about coverage.

We are not aware of a tool evaluation that does this.

---

## 7. Threats to Validity

**Construct.** Our metric extractor is a reimplementation of Solmet over a
different parser. It is validated at ρ=0.930 against an independent
implementation and unit tested, but absolute values differ from Solmet's.
Documented deviations: McCC excludes boolean operators; CBO and the inheritance
metrics are scoped per compilation unit (a corpus-wide name-keyed graph inflates
NOD by orders of magnitude, since every corpus contains many `Ownable`s); NA
counts state-variable declarations.

**Internal.** Detection outcomes for the main corpus are Salzano et al.'s, not
ours; errors in their tool-to-DASP mapping propagate here. We use their mapping
deliberately, so that the two corpora remain comparable. Line matching uses a
±5-line tolerance; category matching does not depend on it.

**External.** Three corpora, three label taxonomies. The FORGE analysis covers
133 of 350 reentrancy projects (38%), so selection remains a concern there, and
FORGE labels are extracted by a single LLM
(DeepSeek-Chat v3, `deepseek-chat-v3-0324`, via OpenRouter) at **temperature
0.8** with no ensemble or cross-model check, at 95.6% reported precision
validated on a sample rather than exhaustively. Because the temperature is not
zero, FORGE's own pipeline is not deterministic and re-running it would not
reproduce the labels exactly. FORGE is therefore the corpus with the softest
ground truth of the three, and should not be treated as a tie-breaker of
record — its role in RQ9 is to show that no consistent effect exists, which
does not depend on its labels being exact. FORGE scoring is project-level and generous, which biases
against detecting a positive complexity effect. The DAppSCAN detection analysis
uses a single static analyser and a single symbolic executor. Mythril
was given a 60-second budget; a different budget would change absolute failure
rates, though it is held constant across contracts so between-contract
comparisons are unaffected.

**Conclusion.** Many hypotheses were tested; we have not applied a family-wise
correction, so individual p-values near 0.05 should be read cautiously. The
findings we advance (RQ1, RQ8) are those that replicated across corpora, which
is a stronger filter than any correction.

---

## 8. Conclusion

We set out to show that code complexity predicts where smart-contract detectors
fail. It largely does not. Contract size does not predict missed bugs; the
strongest single-metric effect we found in one corpus is null in another; and
the category-level mechanism that survived four robustness checks in the main
corpus could not be reproduced on either of two independent corpora, one of
which was assembled specifically to test it.

What survives is narrower and, we think, more useful: detector *failure* is two
distinct phenomena that prior work conflates, and the one property that reliably
separates detector classes is inheritance structure, which defeats symbolic
executors specifically. The instability of everything else is not a nuisance
result — it is the most plausible explanation for why this literature disagrees
with itself.

---

## References

1. T. J. McCabe. A complexity measure. *IEEE TSE*, SE-2(4):308–320, 1976.
2. Y. Shin and L. Williams. Is complexity really the enemy of software
   security? *QoP*, 47–50, 2008.
3. I. Chowdhury and M. Zulkernine. Using complexity, coupling, and cohesion
   metrics as early indicators of vulnerabilities. *JSA*, 57(3):294–313, 2011.
4. S. R. Chidamber and C. F. Kemerer. A metrics suite for object oriented
   design. *IEEE TSE*, 20(6):476–493, 1994.
5. P. Hegedűs. Towards analyzing the complexity landscape of Solidity based
   Ethereum smart contracts. *Technologies*, 7(1):6, 2019.
6. J. Feist, G. Grieco, and A. Groce. Slither: a static analysis framework for
   smart contracts. *WETSEB*, 8–15, 2019.
7. T. Durieux, J. F. Ferreira, R. Abreu, and P. Cruz. Empirical review of
   automated analysis tools on 47,587 Ethereum smart contracts. *ICSE*,
   530–541, 2020.
8. A. Ghaleb and K. Pattabiraman. How effective are smart contract analysis
   tools? Evaluating smart contract static analysis tools using bug injection.
   *ISSTA*, 415–427, 2020.
9. Z. Zheng et al. DAppSCAN: Building large-scale datasets for smart contract
   weaknesses in DApp projects. *IEEE TSE*, 2024.
10. F. Salzano et al. An empirical analysis of vulnerability detection tools for
    Solidity smart contracts using line level manually annotated
    vulnerabilities. *EMSE*, 2026. arXiv:2505.15756.
11. Y. Shen et al. FORGE: An LLM-driven framework for large-scale smart contract
    vulnerability dataset construction. *ICSE*, 2026. arXiv:2506.18795.
12. Z. Zhang, B. Zhang, W. Xu, and Z. Lin. Demystifying exploitable bugs in
    smart contracts. *ICSE*, 615–627, 2023.
13. M. J. Tehrani. Assessing vulnerability in smart contracts: the role of code
    complexity metrics in security analysis. arXiv:2411.17343, 2026.
14. J. Romano and J. Kromrey. Appropriate statistics for ordinal level data.
    *FAIR*, 2006.

---

## Data Availability

All code, derived tables and figures: this repository. Detection outcomes and
ground truth for the main corpus are from the replication package of Salzano et
al. (EMSE 2026); SWC ground truth is from DAppSCAN (TSE 2024). Both must be
cited by any user of this pipeline. Complexity extraction, panel construction,
statistical models, the triage model and the Mythril runs are ours.

Reproduce with `scripts/01` through `scripts/12`; see `README.md`.
