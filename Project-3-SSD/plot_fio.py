#!/usr/bin/env python3
"""Project 3: raw CSV/logs -> processed tables + plots. Error bars = std over repeated runs. Env overrides: FIO_RAW, FIO_OUT (for testing)."""
import os, re, glob, numpy as np, pandas as pd, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
H = os.path.dirname(os.path.abspath(__file__)); RAW = os.environ.get("FIO_RAW", f"{H}/data/raw"); OUT = os.environ.get("FIO_OUT", H)
PRO, PLT = f"{OUT}/data/processed", f"{OUT}/plots"; os.makedirs(PRO, exist_ok=True); os.makedirs(PLT, exist_ok=True)
def load(n): p = f"{RAW}/{n}.csv"; return pd.read_csv(p) if os.path.exists(p) else None
def ag(df, keys, cols):
    g = df.groupby(keys)[cols].agg(["median", "std"]); g.columns = [f"{a}_{b}" for a, b in g.columns]; return g.reset_index()
def knee(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float); o = np.argsort(x); x, y = x[o], y[o]
    if len(x) < 3: return None
    xn = (x - x[0]) / (x[-1] - x[0] + 1e-12); yn = (y - y[0]) / (y[-1] - y[0] + 1e-12); return o[np.argmax(xn - yn)]
P = lambda d, p: f"{d}_p{p}_us"

zq = load("zero_queue")
if zq is not None:
    zq["dir"] = zq.name.map(lambda n: "read" if n in ("rr4k", "sr128k") else "write"); rows = []
    for (n, d), g in zq.groupby(["name", "dir"]):
        r = dict(test=n, dir=d, iops=g.iops.median(), bw_MiBs=g.bw_MiBs.median(), mean_us=g[f"{d}_lat_mean_us"].median(), mean_us_std=g[f"{d}_lat_mean_us"].std())
        for p in (50, 95, 99, 99.9): r[f"p{p}_us"] = g[P(d, p)].median(); r[f"p{p}_us_std"] = g[P(d, p)].std()
        rows.append(r)
    t = pd.DataFrame(rows); t.to_csv(f"{PRO}/zero_queue_table.csv", index=False); print(t.round(1).to_string())

bs = load("bs_sweep")
if bs is not None:
    m = bs.name.str.extract(r"(?P<pat>rand|seq)-(?P<dir>read|write)-(?P<bsz>\d+k|1m)-qd(?P<q>\d+)"); bs = pd.concat([bs, m], axis=1)
    bs["bs_kib"] = bs.bsz.map(lambda s: int(s[:-1]) * (1024 if s.endswith("m") else 1)); bs["q"] = bs.q.astype(int)
    a = ag(bs, ["pat", "dir", "bs_kib", "q"], ["iops", "bw_MiBs", "lat_mean_us"]); a["p99_us"] = bs.apply(lambda r: r[P(r["dir"], 99)], axis=1).groupby([bs.pat, bs["dir"], bs.bs_kib, bs.q]).median().values; a.to_csv(f"{PRO}/bs_sweep_agg.csv", index=False)
    fig, axs = plt.subplots(2, 3, figsize=(17, 8))
    for r, q in enumerate((1, 32)):
        for (pat, d), g in a[a.q == q].groupby(["pat", "dir"]):
            g = g.sort_values("bs_kib")

            x = pd.to_numeric(g["bs_kib"], errors="coerce")
            
            # 1) Throughput (bw_MiBs)
            y_bw = pd.to_numeric(g["bw_MiBs_median"], errors="coerce")
            err_bw = pd.to_numeric(g["bw_MiBs_std"], errors="coerce").fillna(0).clip(lower=0)
            valid_bw = x.notna() & y_bw.notna()
            if valid_bw.any():
                axs[r, 0].errorbar(x[valid_bw], y_bw[valid_bw], yerr=err_bw[valid_bw], marker="o", label=f"{pat} {d}", capsize=2)

            # 2) IOPS
            y_iops = pd.to_numeric(g["iops_median"], errors="coerce")
            err_iops = pd.to_numeric(g["iops_std"], errors="coerce").fillna(0).clip(lower=0)
            valid_iops = x.notna() & y_iops.notna()
            if valid_iops.any():
                axs[r, 1].errorbar(x[valid_iops], y_iops[valid_iops], yerr=err_iops[valid_iops], marker="o", capsize=2)

            # 3) Mean Latency
            y_lat = pd.to_numeric(g["lat_mean_us_median"], errors="coerce")
            err_lat = pd.to_numeric(g["lat_mean_us_std"], errors="coerce").fillna(0).clip(lower=0)
            valid_lat = x.notna() & y_lat.notna()
            if valid_lat.any():
                axs[r, 2].errorbar(x[valid_lat], y_lat[valid_lat], yerr=err_lat[valid_lat], marker="o", capsize=2)

        for c, y_lbl in enumerate(("throughput (MiB/s)", "IOPS", "mean latency (us)")): 
            axs[r, c].set_xscale("log", base=2)
            axs[r, c].set_yscale("log")
            axs[r, c].set_xlabel("block size (KiB)")
            axs[r, c].set_ylabel(y_lbl)
            axs[r, c].set_title(f"QD={q}")
            
    axs[0, 0].legend(fontsize=7); fig.suptitle("Block-size sweep (same runs give throughput, IOPS, latency)"); fig.tight_layout(); fig.savefig(f"{PLT}/bs_sweep.png", dpi=130); plt.close(fig)

rm = load("rw_mix")
if rm is not None:
    a = ag(rm, ["rwmix"], ["iops", "read_lat_mean_us", "write_lat_mean_us", "read_p99_us", "write_p99_us"]).sort_values("rwmix", ascending=False); a.to_csv(f"{PRO}/rw_mix_agg.csv", index=False)
    fig, axs = plt.subplots(1, 2, figsize=(11, 4)); axs[0].bar(a.rwmix.astype(str), a.iops_median, yerr=a.iops_std.fillna(0)); axs[0].set_xlabel("% reads"); axs[0].set_ylabel("total IOPS"); axs[0].set_title("4K random, QD32")
    x = np.arange(len(a)); axs[1].bar(x - .2, a.read_lat_mean_us_median, .4, label="read mean"); axs[1].bar(x + .2, a.write_lat_mean_us_median, .4, label="write mean"); axs[1].set_xticks(x); axs[1].set_xticklabels(a.rwmix); axs[1].set_xlabel("% reads"); axs[1].set_ylabel("latency (us)"); axs[1].set_yscale("log"); axs[1].legend()
    fig.tight_layout(); fig.savefig(f"{PLT}/rw_mix.png", dpi=130); plt.close(fig)

qs = load("qd_sweep")
if qs is not None:
    q = qs[qs.exp == "qd_sweep"].copy(); q["test"] = q.name.str.extract(r"^(\w+)-qd")[0]; fig, axs = plt.subplots(2, 3, figsize=(17, 8)); krows = []
    for j, (test, d, unit, col) in enumerate((("rr4k", "read", "IOPS", "iops"), ("rw4k", "write", "IOPS", "iops"), ("sr128k", "read", "MiB/s", "bw_MiBs"))):
        g = ag(q[q.test == test], ["qd"], [col, "lat_mean_us"]).sort_values("qd"); tl = q[q.test == test].groupby("qd")[P(d, 99)].median().values
        axs[0, j].errorbar(g[f"{col}_median"], g.lat_mean_us_median, xerr=g[f"{col}_std"].fillna(0), yerr=g.lat_mean_us_std.fillna(0), marker="o", capsize=2, label="mean"); axs[0, j].plot(g[f"{col}_median"], tl, "s--", label="p99")
        [axs[0, j].annotate(f"QD{int(a_)}", (x, y), fontsize=7) for a_, x, y in zip(g.qd, g[f"{col}_median"], g.lat_mean_us_median)]
        k = knee(g[f"{col}_median"], g.lat_mean_us_median); mx = g[f"{col}_median"].max(); k90 = int(g.qd[g[f"{col}_median"] >= 0.9 * mx].min())
        if k is not None: axs[0, j].plot(g[f"{col}_median"].iloc[k], g.lat_mean_us_median.iloc[k], "k*", ms=14)
        axs[0, j].set_xlabel(unit); axs[0, j].set_ylabel("latency (us)"); axs[0, j].set_yscale("log"); axs[0, j].set_title(f"{test}: throughput-latency (star = knee)"); axs[0, j].legend(fontsize=7)
        iops = g.iops_median if col == "iops" else g[f"{col}_median"] * 1024 / 128; outst = iops * g.lat_mean_us_median * 1e-6   # Little: L = lambda * W
        pred = iops.max() * g.lat_mean_us_median.iloc[0] * 1e-6        # Little's Law at the knee: QD* = X_max x unloaded latency (device concurrency needed to reach max throughput)
        axs[1, j].loglog(g.qd, outst, "o-", label="IOPS x mean latency"); axs[1, j].loglog(g.qd, g.qd, "k--", label="= QD (identity for a closed loop: consistency check)"); axs[1, j].axvline(pred, color="r", ls=":", label=f"predicted knee X_max x L_QD1 = {pred:.0f}")
        axs[1, j].set_xlabel("queue depth (iodepth)"); axs[1, j].set_ylabel("IOPS x latency = requests in flight"); axs[1, j].legend(fontsize=6)
        krows.append(dict(test=test, little_predicted_knee_qd=pred, knee_qd_kneedle=int(g.qd.iloc[k]) if k is not None else np.nan, qd_at_90pct_max=k90, max_throughput=mx, unit=unit, qd1_lat_us=g.lat_mean_us_median.iloc[0], lat_at_90pct_us=g.lat_mean_us_median[g.qd == k90].iloc[0]))
    pd.DataFrame(krows).to_csv(f"{PRO}/knee_summary.csv", index=False); fig.tight_layout(); fig.savefig(f"{PLT}/qd_sweep_knee.png", dpi=130); plt.close(fig)
    jb = qs[qs.exp == "jobs_sweep"]
    if len(jb):
        g = ag(jb, ["numjobs"], ["iops", "lat_mean_us"]); fig, ax = plt.subplots(figsize=(6, 4)); ax.errorbar(g.iops_median, g.lat_mean_us_median, marker="o", yerr=g.lat_mean_us_std.fillna(0), xerr=g.iops_std.fillna(0)); [ax.annotate(f"{j}j", (x, y)) for j, x, y in zip(g.numjobs, g.iops_median, g.lat_mean_us_median)]
        ax.set_xlabel("IOPS"); ax.set_ylabel("mean latency (us)"); ax.set_title("4K randread: parallelism via numjobs (QD1 each)"); fig.tight_layout(); fig.savefig(f"{PLT}/jobs_sweep.png", dpi=130); plt.close(fig)

tl = load("tail")
if tl is not None:
    tl["d"] = tl.name.map(lambda n: "read" if n.startswith("rr") else "write"); pcs = [50, 90, 95, 99, 99.9, 99.99]; rows = []
    for n, g in tl.groupby("name"): d = g.d.iloc[0]; rows.append(dict(config=n, **{f"p{p}_us": g[P(d, p)].median() for p in pcs}, **{f"p{p}_std": g[P(d, p)].std() for p in pcs}))
    t = pd.DataFrame(rows); t.to_csv(f"{PRO}/tail_table.csv", index=False); fig, ax = plt.subplots(figsize=(10, 4.5)); w = 0.8 / len(t)
    for i, r in t.iterrows(): ax.bar(np.arange(len(pcs)) + i * w, [r[f"p{p}_us"] for p in pcs], w, yerr=[r[f"p{p}_std"] if not np.isnan(r[f"p{p}_std"]) else 0 for p in pcs], label=r.config)
    ax.set_xticks(np.arange(len(pcs)) + 0.4 - w / 2); ax.set_xticklabels([f"p{p}" for p in pcs]); ax.set_yscale("log"); ax.set_ylabel("completion latency (us)"); ax.legend(fontsize=6, ncol=2); ax.set_title("Tail latency vs queue depth"); fig.tight_layout(); fig.savefig(f"{PLT}/tail_latency.png", dpi=130); plt.close(fig)

logs = sorted(glob.glob(f"{RAW}/logs/*_bw*.log"))
if logs:
    fig, axs = plt.subplots(1, len(logs), figsize=(6 * len(logs), 4), squeeze=False)
    for ax, p in zip(axs[0], logs):
        d = pd.read_csv(p, header=None, names=["ms", "val", "ddir", "bs", "off"], skipinitialspace=True); name = os.path.basename(p).split("_bw")[0]
        ax.plot(d.ms / 1000, d.val / 1024, lw=.8); ax.set_xlabel("time (s)"); ax.set_ylabel("throughput (MiB/s)"); ax.set_title(name, fontsize=9)
        tp = f"{RAW}/logs/{name}_temp.csv"
        if os.path.exists(tp): t = pd.read_csv(tp); a2 = ax.twinx(); a2.plot(t.t_s, t.temp_c, "r", lw=.8); a2.set_ylabel("NVMe temp (C)", color="r")
    fig.suptitle("Device state / SLC cache / thermal behaviour over time"); fig.tight_layout(); fig.savefig(f"{PLT}/device_state_timeseries.png", dpi=130); plt.close(fig)

pf = load("pitfalls")
if pf is not None:
    a = ag(pf, ["name"], ["iops"]); ref = a.loc[a.name == "correct_direct_async_qd32", "iops_median"].iloc[0] if (a.name == "correct_direct_async_qd32").any() else float("nan"); a["ratio_vs_correct_run"] = a.iops_median / ref; a.to_csv(f"{PRO}/pitfalls_agg.csv", index=False); fig, ax = plt.subplots(figsize=(9, 4)); ax.bar(range(len(a)), a.iops_median, yerr=a.iops_std.fillna(0)); ax.set_xticks(range(len(a))); ax.set_xticklabels(a.name, rotation=25, ha="right", fontsize=7); ax.set_yscale("log"); ax.set_ylabel("IOPS (4K randread)"); ax.set_title("Misleading setups vs correct direct-I/O QD32 run"); fig.tight_layout(); fig.savefig(f"{PLT}/pitfalls.png", dpi=130); plt.close(fig)

print("plots ->", PLT)