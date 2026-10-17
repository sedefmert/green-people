#!/usr/bin/env python3
# This script analyses the results of the experiment, producing CSV tables and figures for the report.
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats
from statsmodels.stats.multicomp import pairwise_tukeyhsd
from statsmodels.stats.multitest import multipletests

ALPHA = 0.05
SEED = 2026
TREATMENTS = ["none", "zip", "tar.gz", "tar.zst", "tar.br"]
COMPRESSING = TREATMENTS[1:]
PAYLOADS = ["S", "L"]

# (hypothesis family, metric id, column, treatments included, label)
TESTS = [
    ("H1", "M1", "cpu_util_mean_compress", COMPRESSING, "CPU utilisation, compression (%)"),
    ("H1", "M1", "cpu_util_mean_transmit", TREATMENTS,  "CPU utilisation, transmission (%)"),
    ("H1", "M2", "cpu_time_compress_s",    COMPRESSING, "CPU time, compression (s)"),
    ("H1", "M2", "cpu_time_transmit_s",    TREATMENTS,  "CPU time, transmission (s)"),
    ("H2", "M3", "wlan_tx_mb",             TREATMENTS,  "Data sent over WLAN (MB)"),
    ("H2", "M5", "t_transmit_s",           TREATMENTS,  "Transmission time (s)"),
    ("H3", "M6", "energy_total_j",         TREATMENTS,  "Total energy (J)"),
    ("H3", "M7", "energy_compress_j",      COMPRESSING, "Energy, compression phase (J)"),
    ("H3", "M7", "energy_transmit_j",      TREATMENTS,  "Energy, transmission phase (J)"),
]

DESCRIBE = ["cpu_util_mean_compress", "cpu_util_peak_compress", "cpu_util_mean_transmit",
            "cpu_util_peak_transmit", "cpu_time_compress_s", "cpu_time_transmit_s",
            "cpu_time_total_s", "wlan_tx_mb", "compression_ratio", "t_compress_s", "t_transmit_s",
            "energy_compress_j", "energy_transmit_j", "energy_total_j", "energy_per_mb_j",
            "energy_total_counter_j", "energy_tx_above_idle_j", "energy_compress_above_idle_j", "p_idle_w",
            "clock_offset_pre_s", "sync_rtt_max_s"]


# Load data from run_table.csv
def load(main, rerun, include_invalid):
    m = pd.read_csv(main)
    m = m[m["__done"] == "DONE"].assign(source="main")
    parts = [m]

    for path in rerun or []:
        r = pd.read_csv(path)
        r = r[r["__done"] == "DONE"].assign(source=f"rerun:{Path(path).parent.name}")
        parts.append(r)

    allruns = pd.concat(parts, ignore_index=True)
    allruns["valid"] = allruns["valid"].astype(str) == "True"

    used = allruns if include_invalid else allruns[allruns["valid"]]
    used = used[used.treatment.isin(TREATMENTS) & used.payload.isin(PAYLOADS)].copy()

    used["treatment"] = pd.Categorical(used.treatment, TREATMENTS)
    used["payload"] = pd.Categorical(used.payload, PAYLOADS)

    return allruns, used

# Compute Cohen's d for effect size between two groups.
def cohens_d(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    sp = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2))
    return (a.mean() - b.mean()) / sp if sp > 0 else np.nan

# Compute Cliff's delta for effect size between two groups.
def cliffs_delta(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    gt = (a[:, None] > b[None, :]).sum()
    lt = (a[:, None] < b[None, :]).sum()
    return (gt - lt) / (len(a) * len(b))


# Perform ANOVA for a 2-factor between-subjects design.
def anova(df, y):
    model = smf.ols(f"{y} ~ C(treatment) * C(payload)", data=df).fit()
    tab = sm.stats.anova_lm(model, typ=2)
    ss_res = tab.loc["Residual", "sum_sq"]
    tab["partial_eta2"] = tab["sum_sq"] / (tab["sum_sq"] + ss_res)

    return model, tab

# Check assumptions for ANOVA.
def assumptions(df, y, model):
    resid = model.resid
    degenerate = np.allclose(resid.std(), 0)
    sw_p = np.nan if degenerate else stats.shapiro(resid).pvalue
    groups = [g[y].values for _, g in df.groupby(["treatment", "payload"], observed=True)]
    lev_p = np.nan if degenerate else stats.levene(*groups, center="mean").pvalue
    ok = (not degenerate) and sw_p >= ALPHA and lev_p >= ALPHA

    return ok, sw_p, lev_p, degenerate

# Perform ART ANOVA.
def art_anova(df, y):
    d = df[["treatment", "payload", y]].copy()
    d["treatment"], d["payload"] = d.treatment.astype(str), d.payload.astype(str)
    mu = d[y].mean()
    cell = d.groupby(["treatment", "payload"])[y].transform("mean")
    a_m = d.groupby("treatment")[y].transform("mean")
    b_m = d.groupby("payload")[y].transform("mean")
    resid = d[y] - cell
    aligned = {
        "C(treatment)": resid + (a_m - mu),
        "C(payload)": resid + (b_m - mu),
        "C(treatment):C(payload)": resid + (cell - a_m - b_m + mu),
    }
    rows = {}

    for effect, values in aligned.items():
        d["_r"] = stats.rankdata(values)
        tab = sm.stats.anova_lm(smf.ols("_r ~ C(treatment) * C(payload)", data=d).fit(), typ=2)
        ss_res = tab.loc["Residual", "sum_sq"]
        rows[effect] = {"df": tab.loc[effect, "df"], "F": tab.loc[effect, "F"],
                        "PR(>F)": tab.loc[effect, "PR(>F)"],
                        "partial_eta2": tab.loc[effect, "sum_sq"] / (tab.loc[effect, "sum_sq"] + ss_res)}
        
    return pd.DataFrame(rows).T


TRANSFORMS = {"log": np.log, "sqrt": np.sqrt, "reciprocal": lambda v: 1.0 / v}

# Test a metric for differences between treatments.
def test_metric(df, family, mid, col, treatments, label, figdir):
    d = df[df.treatment.isin(treatments)].copy()
    d["treatment"] = d.treatment.cat.remove_unused_categories()
    d = d.dropna(subset=[col])

    rows, posthoc = [], []
    model, tab = anova(d, col)

    ok, sw, lev, degenerate = assumptions(d, col, model)
    method, used_col = "two-way ANOVA", col

    if not ok and not degenerate and (d[col] > 0).all():
        for name, fn in TRANSFORMS.items():
            d["_t"] = fn(d[col])
            m2, t2 = anova(d, "_t")
            ok2, sw2, lev2, _ = assumptions(d, "_t", m2)

            if ok2:
                model, tab, sw, lev, ok = m2, t2, sw2, lev2, True
                method, used_col = f"two-way ANOVA on {name}({col})", "_t"
                break

    qq(model.resid, f"{mid} {label}", figdir / f"qq_{col}.png")
    
    if degenerate:
        method = "descriptive only (no within-cell variance)"
    elif not ok:
        tab, method = art_anova(d, col), "ART ANOVA"

    effects = {"C(treatment)": f"{family}.1", "C(treatment):C(payload)": f"{family}.2"}

    if mid == "M6":
        effects["C(payload)"] = "(payload effect)"

    for effect, hid in effects.items():
        if degenerate:
            break
        rows.append({"hypothesis": hid, "metric": mid, "column": col, "label": label,
                     "effect": effect.replace("C(", "").replace(")", ""), "method": method,
                     "df": tab.loc[effect, "df"], "F": tab.loc[effect, "F"],
                     "p": tab.loc[effect, "PR(>F)"], "partial_eta2": tab.loc[effect, "partial_eta2"],
                     "shapiro_resid_p": sw, "levene_p": lev})

    if not degenerate:
        for p in PAYLOADS:
            s = d[d.payload == p]
            if ok:
                tk = pairwise_tukeyhsd(s[used_col], s.treatment.astype(str), alpha=ALPHA)
                res = pd.DataFrame(tk.summary().data[1:], columns=tk.summary().data[0])
                for _, r in res.iterrows():
                    a, b = s[s.treatment == r.group1][col], s[s.treatment == r.group2][col]
                    posthoc.append({"column": col, "payload": p, "group1": r.group1, "group2": r.group2,
                                    "test": "Tukey HSD", "p": float(r["p-adj"]),
                                    "effect_size": cohens_d(a, b), "effect_measure": "Cohen's d"})
            else:
                groups = [t for t in treatments if (s.treatment == t).any()]
                for i, g1 in enumerate(groups):
                    for g2 in groups[i + 1:]:
                        a, b = s[s.treatment == g1][col], s[s.treatment == g2][col]
                        posthoc.append({"column": col, "payload": p, "group1": g1, "group2": g2,
                                        "test": "Wilcoxon rank-sum",
                                        "p": stats.mannwhitneyu(a, b, alternative="two-sided").pvalue,
                                        "effect_size": cliffs_delta(a, b), "effect_measure": "Cliff's delta"})
                        
    return rows, posthoc

# Test the effect of payload on energy per MB of input
def h33(df):
    d = df.dropna(subset=["energy_per_mb_j"])
    model, tab = anova(d, "energy_per_mb_j")
    ok, sw, lev, _ = assumptions(d, "energy_per_mb_j", model)
    method = "two-way ANOVA"

    if not ok:
        tab, method = art_anova(d, "energy_per_mb_j"), "ART ANOVA"
    e = "C(payload)"

    return [{"hypothesis": "H3.3", "metric": "M8", "column": "energy_per_mb_j",
             "label": "Energy per MB of input (J/MB)", "effect": "payload", "method": method,
             "df": tab.loc[e, "df"], "F": tab.loc[e, "F"], "p": tab.loc[e, "PR(>F)"],
             "partial_eta2": tab.loc[e, "partial_eta2"], "shapiro_resid_p": sw, "levene_p": lev}]

# Test the effect of compression on energy per MB of input, with bootstrapped confidence intervals and effect sizes.
def h34(df, n_boot=10000):
    rng = np.random.default_rng(SEED)
    rows = []

    for p in PAYLOADS:
        base = df[(df.payload == p) & (df.treatment == "none")]["energy_total_j"].to_numpy()

        for a in COMPRESSING:
            x = df[(df.payload == p) & (df.treatment == a)]["energy_total_j"].to_numpy()

            if len(base) < 2 or len(x) < 2:
                continue

            delta = base.mean() - x.mean()
            boots = (rng.choice(base, (n_boot, len(base))).mean(1)
                     - rng.choice(x, (n_boot, len(x))).mean(1))
            lo, hi = np.percentile(boots, [2.5, 97.5])
            normal = stats.shapiro(base).pvalue >= ALPHA and stats.shapiro(x).pvalue >= ALPHA

            if normal:
                pval, test = stats.ttest_ind(base, x, equal_var=False).pvalue, "Welch t-test"
                es, esm = cohens_d(base, x), "Cohen's d"
            else:
                pval, test = stats.mannwhitneyu(base, x, alternative="two-sided").pvalue, "Wilcoxon rank-sum"
                es, esm = cliffs_delta(base, x), "Cliff's delta"

            rows.append({"hypothesis": "H3.4", "treatment": a, "payload": p,
                         "baseline_mean_j": base.mean(), "treatment_mean_j": x.mean(),
                         "delta_j": delta, "delta_pct": 100 * delta / base.mean(),
                         "ci95_low_j": lo, "ci95_high_j": hi, "test": test, "p": pval,
                         "effect_size": es, "effect_measure": esm})
            
    out = pd.DataFrame(rows)

    if len(out):
        out["p_bh"] = multipletests(out.p, method="fdr_bh")[1]
        out["energy_efficient"] = (out.p_bh < ALPHA) & (out.delta_j > 0) & (out.ci95_low_j > 0)

    return out

# Test the correlation between CPU time and energy consumption for each payload size.
def h35(df):
    rows = []
    for p in PAYLOADS:
        s = df[df.payload == p].dropna(subset=["cpu_time_total_s", "energy_total_j"])
        rho, pval = stats.spearmanr(s.cpu_time_total_s, s.energy_total_j)
        rows.append({"hypothesis": "H3.5", "payload": p, "n": len(s), "rho": rho, "p": pval})
    out = pd.DataFrame(rows)
    out["p_bh"] = multipletests(out.p, method="fdr_bh")[1]
    return out


# Plot Q-Q plots for residual analysis.
def qq(resid, title, path):
    fig, ax = plt.subplots(figsize=(4, 4))
    sm.qqplot(np.asarray(resid), line="45", fit=True, ax=ax, markersize=3)
    ax.set_title(title, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)

# Plot box plots for each treatment and payload combination.
def boxplots(df, figdir):
    for _, mid, col, treatments, label in TESTS + [("", "M8", "energy_per_mb_j", TREATMENTS, "Energy per MB (J/MB)"),
                                                   ("", "M4", "compression_ratio", COMPRESSING, "Compression ratio")]:
        fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
        for ax, p in zip(axes, PAYLOADS):
            s = df[(df.payload == p) & df.treatment.isin(treatments)]
            data = [s[s.treatment == t][col].dropna() for t in treatments]
            ax.boxplot(data)
            ax.set_xticks(range(1, len(treatments) + 1), treatments)
            ax.set_title(f"{mid} - payload {p}", fontsize=9)
            ax.set_ylabel(label, fontsize=8)
            ax.tick_params(labelsize=8)
        fig.tight_layout()
        fig.savefig(figdir / f"box_{col}.png", dpi=150)
        plt.close(fig)

# Plot density plots for each treatment and payload combination.
def densities(df, figdir):
    for col, label in [("energy_total_j", "Total energy (J)"), ("t_transmit_s", "Transmission time (s)"),
                       ("cpu_time_total_s", "CPU time (s)")]:
        fig, axes = plt.subplots(1, 2, figsize=(9, 3.2))
        for ax, p in zip(axes, PAYLOADS):
            for t in TREATMENTS:
                v = df[(df.payload == p) & (df.treatment == t)][col].dropna().to_numpy()
                if len(v) > 2 and v.std() > 0:
                    xs = np.linspace(v.min() - v.std(), v.max() + v.std(), 200)
                    ax.plot(xs, stats.gaussian_kde(v)(xs), label=t)
            ax.set_title(f"payload {p}", fontsize=9)
            ax.set_xlabel(label, fontsize=8)
            ax.legend(fontsize=7)
        fig.tight_layout()
        fig.savefig(figdir / f"density_{col}.png", dpi=150)
        plt.close(fig)

# Plot stacked bar charts for M7 energy consumption per phase.
def stacked_m7(df, figdir):
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
    for ax, p in zip(axes, PAYLOADS):
        s = df[df.payload == p].groupby("treatment", observed=False)[["energy_compress_j", "energy_transmit_j"]].mean()
        s = s.reindex(TREATMENTS)
        ax.bar(TREATMENTS, s.energy_compress_j, label="compression")
        ax.bar(TREATMENTS, s.energy_transmit_j, bottom=s.energy_compress_j, label="transmission")
        ax.set_title(f"M7 energy per phase - payload {p}", fontsize=9)
        ax.set_ylabel("J", fontsize=8)
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(figdir / "stacked_energy_per_phase.png", dpi=150)
    plt.close(fig)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", required=True)
    ap.add_argument("--rerun", nargs="*", help="one or more re-execution run tables")
    ap.add_argument("--out", default="data/results")
    ap.add_argument("--include-invalid", action="store_true",
                    help="dry-run testing only (e.g. simulated runs); never for the report")
    a = ap.parse_args()
    out = Path(a.out)
    figdir = out / "figures"
    figdir.mkdir(parents=True, exist_ok=True)

    allruns, df = load(a.main, a.rerun, a.include_invalid)
    allruns.to_csv(out / "runs_all.csv", index=False)
    df.to_csv(out / "runs_analysed.csv", index=False)
    counts = df.groupby(["treatment", "payload"], observed=False).size().unstack()
    incomplete = counts[(counts != 10).any(axis=1)]

    desc = (df.groupby(["treatment", "payload"], observed=True)[[c for c in DESCRIBE if c in df.columns]]
            .agg(["mean", "median", "std"]).round(4))
    desc.to_csv(out / "descriptives.csv")

    boxplots(df, figdir)
    densities(df, figdir)
    stacked_m7(df, figdir)

    hyp, post = [], []
    for family, mid, col, treatments, label in TESTS:
        r, ph = test_metric(df, family, mid, col, treatments, label, figdir)
        hyp += r
        post += ph
    hyp += h33(df)
    hyp = pd.DataFrame(hyp)
    hyp["p_bh"] = multipletests(hyp.p, method="fdr_bh")[1]
    hyp["reject_H0"] = hyp.p_bh < ALPHA
    hyp.to_csv(out / "hypothesis_tests.csv", index=False)

    post = pd.DataFrame(post)
    if len(post):
        post["p_adj"] = post.p
        wil = post.test == "Wilcoxon rank-sum"
        for _, idx in post[wil].groupby(["column", "payload"]).groups.items():
            post.loc[idx, "p_adj"] = multipletests(post.loc[idx, "p"], method="fdr_bh")[1]
        post["significant"] = post.p_adj < ALPHA
        post.to_csv(out / "posthoc_pairwise.csv", index=False)

    saving = h34(df)
    saving.to_csv(out / "h34_energy_saving.csv", index=False)
    corr = h35(df)
    corr.to_csv(out / "h35_spearman.csv", index=False)

    with open(out / "summary.md", "w") as f:
        f.write("# Analysis summary\n\n")
        f.write(f"Runs analysed: {len(df)} (all runs incl. invalid: {len(allruns)}; "
                f"invalid: {int((~allruns.valid).sum())})\n\n")
        if len(incomplete):
            f.write("**WARNING: cells without exactly 10 valid runs:**\n\n" + incomplete.to_markdown() + "\n\n")
        f.write("## Omnibus tests (BH-adjusted)\n\n")
        f.write(hyp[["hypothesis", "metric", "column", "effect", "method", "F", "p", "p_bh",
                     "partial_eta2", "reject_H0"]].round(4).to_markdown(index=False) + "\n\n")
        f.write("## H3.4 net energy saving vs. baseline\n\n")
        if len(saving):
            f.write(saving[["treatment", "payload", "delta_j", "delta_pct", "ci95_low_j", "ci95_high_j",
                            "test", "p_bh", "effect_size", "energy_efficient"]].round(3)
                    .to_markdown(index=False) + "\n\n")
        f.write("## H3.5 Spearman rho(M2, M6)\n\n" + corr.round(4).to_markdown(index=False) + "\n")
    print((out / "summary.md").read_text())


if __name__ == "__main__":
    main()
