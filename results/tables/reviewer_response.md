# Reviewer response: four requested analyses

All numbers below are produced by `scripts/19`–`22` and read from CSVs in
`results/tables/`. Nothing is transcribed by hand.

**Script numbering.** The brief suggested `14`–`17`; those numbers were
already occupied in this repo (`14_make_tables`, `15_revisions`,
`16_refit_vif`, `17_category_mix`, `18_type_s`). The new work is
`19`–`22`. Nothing at `05`–`18` was modified.

---

## Summary

| Task | Verdict |
|---|---|
| S1 sub-benchmark FE | **CLOC survives; AvgNOS does not** |
| S2 linearity of logit | **changes** — both survive a flexible form, both are non-linear |
| S3 Mythril timeout split | **overturned** — the RQ5 effect is a timeout effect |
| S4 triage attribution | **changes** — complexity does not beat category composition |

> **Net effect on the paper.** The positive content shrinks from *two
> surviving coefficients plus a marginal detector-class effect* to *one
> surviving coefficient, non-linear in form*, plus a detector-class effect
> whose mechanism must be renamed, plus a triage model whose complexity
> attribution is not established. The paper's central negative claim is
> untouched and, if anything, reinforced: two more specification choices
> change which coefficients stand.

---

## S1 — Sub-benchmark fixed effects

**Verdict: CLOC survives, AvgNOS does not.**

| Survivor | Model | Base coef | Base p | +sub-FE coef | +sub-FE p | Wild-bootstrap p | Verdict |
|---|---|---:|---:|---:|---:|---:|---|
| CLOC | detection | +0.0738 | 0.0033 | +0.0743 | 0.0029 | 0.0610 | survives |
| AvgNOS | analysis | +0.2871 | <0.0001 | +0.0940 | 0.0635 | 0.2610 | **does not survive** |

**AvgNOS, the analysis-failure survivor, drops from +0.2871 (p <0.0001) to +0.0940 (p 0.0635) once sub-benchmark fixed effects are added**, and the
wild cluster bootstrap over the four sub-benchmarks gives p 0.2610.
It is no longer significant at 0.05 under either.

CLOC is essentially unmoved (+0.0738 → +0.0743, p 0.0033 → 0.0029). Its wild-bootstrap p is 0.0610, which is marginal and should be reported alongside
the clustered value rather than instead of it.

Other significance changes — detection: ['NA']; analysis: ['AvgNOS'].

Sub-benchmark is used as a **fixed effect**, not a third clustering dimension:
with four clusters, cluster-robust SEs are unreliable. The wild cluster
bootstrap (Cameron–Gelbach–Miller, 299 replicates, Rademacher weights) supplies
inference on that dimension. Sub-benchmark FE is never combined with the §6.2
`LLOC × arithmetic-share` interaction, which would be collinear with it.

Backing: `s1_subbenchmark_detection.csv`, `s1_subbenchmark_analysis.csv`, `s1_survivors.csv`

---

## S2 — Linearity of the logit for the two survivors

**Verdict: both survive a flexible form; both are significantly non-linear.**

| Metric | Model | Linear coef | Linear p | Box–Tidwell p | Spline LR p | Same sign | Still significant |
|---|---|---:|---:|---:|---:|:--:|:--:|
| CLOC | detection | +0.0738 | 0.0033 | 0.0003 | <0.0001 | yes | yes |
| AvgNOS | analysis | +0.2871 | <0.0001 | 0.2008 | <0.0001 | yes | yes |

Both effects keep their sign and remain jointly significant under a natural
cubic spline, so neither is a pure functional-form artefact. **But the linear
form is rejected for both** (spline LR p <0.0001 in both models; Box–Tidwell
p 0.0003 for CLOC). The reported linear coefficients
should therefore be read as average directions, not as constant per-SD effects.

The LR test uses unclustered likelihoods, since a likelihood ratio is undefined
for a cluster-robust fit. That is anti-conservative about non-linearity — the
safe direction, as it makes a functional-form problem easier to detect.

Backing: `s2_logit_linearity.csv`, `results/figures/s2_CLOC_logit.png`,
`results/figures/s2_AvgNOS_logit.png`

---

## S3 — Mythril timeout versus genuine crash

**Verdict: overturned. The RQ5 interaction is a timeout effect, not a crash effect.**

Excluding unresolved imports, Mythril's non-completions are 24 timeouts and 92 genuine errors — timeouts are 20.7% of the total. **Slither records zero timeouts**, so a timeout-only *interaction* is not
estimable (the outcome is constant within one tool); the Mythril-only timeout
model below answers the confound question instead.

**Timeout propensity rises steeply with inheritance:**

| Metric | Timeout rate, lowest quartile | Highest quartile | logit(timeout) coef | p |
|---|---:|---:|---:|---:|
| NOA | 0.8% | 22.7% | +1.9147 | <0.0001 |
| DIT | 0.9% | 32.8% | +2.0818 | <0.0001 |

**The interaction does not hold within genuine crashes:**

| Metric | Slither slope | Pooled interaction | p | Crash-only interaction | p |
|---|---:|---:|---:|---:|---:|
| NOA | -0.1873 | +0.3840 | 0.0059 | +0.0194 | 0.8647 |
| DIT | -0.0341 | +0.3090 | 0.0295 | -0.0983 | 0.3616 |

**NOA collapses from +0.3840 (p 0.0059) to +0.0194 (p 0.8647) within genuine
crashes, and DIT reverses sign (+0.3090 → -0.0983).** The mechanism is budget exhaustion under
state growth, not a crash-level state explosion, and must be renamed accordingly.
Note this does not make the effect unreal — failing to finish within a fixed
symbolic budget is what state explosion looks like operationally — but the paper
must stop describing it in crash terms.

Backing: `s3_mythril_breakdown.csv`, `s3_timeout_by_inheritance.csv`,
`s3_interaction_by_failuremode.csv`

---

## S4 — Category-only baseline for the triage model

**Verdict: changes. Complexity does not significantly outperform category composition.**

| Deployment | Complexity AUC | Category-only AUC | Combined AUC | Δ (cx − cat) |
|---|---:|---:|---:|---:|
| slither | 0.915 | 0.901 | 0.945 | +0.013 |
| slither+mythril | 0.890 | 0.867 | 0.916 | +0.023 |
| combo3 | 0.798 | 0.770 | 0.857 | +0.028 |
| all19 | 0.706 | 0.785 | 0.857 | -0.079 |

For the primary Slither-only deployment the gap is +0.013, with a paired per-fold
95% CI of [-0.018, +0.027] (paired t p=0.599) — **not significant**. At the full 19-tool
ensemble the category-only model actually beats complexity (0.785 vs 0.706).

**Interpretive caution that must carry into the paper.** In a real deployment
you do not know a contract's vulnerability category before running the tool —
that is what the tool is for. The category-only model is an **attribution
diagnostic, not a deployable baseline**. The practical claim (complexity-based
triage beats size heuristics and random ordering) is unaffected; what fails is
the *attribution* of that performance to complexity rather than to the category
composition complexity proxies for. This connects RQ6 directly to the §6.2
mechanism.

Backing: `s4_triage_baseline.csv`

---

## Claims to update

Section numbers follow the REV3 draft.

**§5.3 / RQ3 box and Table 5.**
- Old: AvgNOS +0.287 presented as a robust analysis-failure predictor.
- New: add that it falls to +0.0940 (p 0.0635) under sub-benchmark fixed effects, wild-bootstrap p 0.2610.

**§5.5 ("What survives every filter") and Table 12.**
- Old: *"One coefficient survives in each model … comment density on detection
  failure (+0.074) and average statements per function on analysis failure (+0.287)."*
- New: **only CLOC survives.** AvgNOS does not survive sub-benchmark fixed
  effects. Add sub-benchmark FE as a fourth filter and restate as *one*
  surviving coefficient across both models.

**§5.5 and §6.1.**
- Old: *"Two coefficients survive every filter we applied."*
- New: *"One coefficient survives every filter we applied, and its linear form
  is rejected in favour of a non-linear one."*

**§5.6 / RQ5 box, and §6.3 second bullet.**
- Old: inheritance "defeats symbolic executors", framed as state explosion
  producing analysis failure.
- New: the interaction is carried by timeouts. Within genuine crashes NOA is
  +0.0194 (p 0.8647) and DIT reverses
  sign. Rename the mechanism **budget exhaustion under state growth** and state
  that timeouts are 20.7% of Mythril's
  non-completions while Slither has none.

**§5.7 / RQ6 and Table 14.**
- Old: AUC 0.915 attributed to complexity features.
- New: add the category-only row (0.901) and the
  non-significant gap ([-0.018, +0.027] (paired t p=0.599)), with the attribution-diagnostic
  caveat. The deployable claim stands; the attribution does not.

**§7 Threats to Validity.**
- Old: the paragraph listing these four as *open* checks ("specified in the
  replication package but not yet reflected in the coefficients above").
- New: delete it and report the four results. Two overturned a claim.

**§4.4 Statistical models.**
- New: add sub-benchmark fixed effects to the list of specifications reported,
  and note the four-cluster wild bootstrap.

**Abstract.**
- Old: *"leaves two coefficients standing"*.
- New: *"leaves one coefficient standing"*; and the detector-class effect
  should be described as a budget-exhaustion effect.

---

## Reproduce

```bash
./run.sh scripts/19_subbenchmark.py
./run.sh scripts/20_logit_linearity.py
./run.sh scripts/21_mythril_timeout_split.py
./run.sh scripts/22_triage_baseline.py
./run.sh scripts/23_reviewer_response.py   # regenerates this file
./run.sh scripts/24_verify_claims.py       # checks the paper against the CSVs
```
