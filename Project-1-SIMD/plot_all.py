#!/usr/bin/env python3
"""Reads data/raw/*.csv -> data/processed/*.csv and plots/*.png. Error bars = std over repetitions (propagated for ratios)."""
import os, numpy as np, pandas as pd, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
H = os.path.dirname(os.path.abspath(__file__)); RAW, PRO, PLT = f"{H}/data/raw", f"{H}/data/processed", f"{H}/plots"
os.makedirs(PRO, exist_ok=True); os.makedirs(PLT, exist_ok=True)
L1, L2, L3 = 32 * 1024, 512 * 1024, 16 * 2**20       # Ryzen 7 5825U: 32 KiB L1d, 512 KiB L2/core, 16 MiB shared L3. EDIT for other CPUs.
SZ = {"f32": 4, "f64": 8}
META = {  # kernel: (flops/elem, nominal bytes moved/elem in units of sizeof(T), arrays touched)
    "saxpy": (2, 3, 2), "mul": (1, 3, 3), "dot": (2, 2, 2), "stencil": (5, 2, 2), "stride": (2, 3, 2), "gather": (2, 3, 2)}
COL = {"scalar": "C0", "auto": "C1", "native": "C2", "native_fm": "C3"}   # same colour per build in every panel
def load(n):
    p = f"{RAW}/{n}.csv"; return pd.read_csv(p) if os.path.exists(p) else None
def agg(df, keys):
    df = df.copy(); df["sec_per_elem"] = df.sec_per_call / df.N; df["tsc_per_elem"] = df.tsc_per_call / df.N
    g = df.groupby(keys).agg(t_med=("sec_per_call", "median"), t_std=("sec_per_call", "std"), t_min=("sec_per_call", "min"),
                             tsc_med=("tsc_per_elem", "median"), n=("rep", "count")).reset_index()
    g["rel_err"] = (g.t_std / g.t_med).fillna(0); return g
def derive(g):
    g["flops"] = g.kernel.map(lambda k: META[k][0]) * g.N
    g["bytes"] = g.apply(lambda r: META[r.kernel][1] * r.N * SZ[r["dtype"]], axis=1)   # nominal (no write-allocate)
    g["ws"] = g.apply(lambda r: META[r.kernel][2] * r.N * SZ[r["dtype"]] * (r.stride if r.kernel == "stride" else 1), axis=1)
    g["gflops"] = g.flops / g.t_med / 1e9; g["gibs"] = g.bytes / g.t_med / 2**30; return g
def cache_lines(ax):
    for x, l in ((L1, "L1d"), (L2, "L2"), (L3, "L3")): ax.axvline(x, ls=":", c="gray"); ax.text(x, ax.get_ylim()[1], l, ha="right", va="top", fontsize=8, color="gray")
def speedup(g, base="scalar"):
    b = g[g.variant == base].set_index([c for c in g.columns if c in ("kernel", "dtype", "N", "offx", "offy", "stride")])
    out = []
    for v in g.variant.unique():
        if v == base: continue
        x = g[g.variant == v].set_index(b.index.names); j = x.join(b, rsuffix="_b", how="inner")
        j["speedup"] = j.t_med_b / j.t_med; j["sp_err"] = j.speedup * np.sqrt(j.rel_err**2 + j.rel_err_b**2); j["variant"] = v; out.append(j.reset_index())
    return pd.concat(out)

sw = load("sweep")
if sw is not None:
    g = derive(agg(sw, ["variant", "kernel", "dtype", "N", "offx", "offy", "stride"])); g.to_csv(f"{PRO}/sweep_agg.csv", index=False)
    sp = speedup(g); sp = sp.merge(g[g.variant == "scalar"][["kernel", "dtype", "N", "ws"]], on=["kernel", "dtype", "N"], suffixes=("", "_s")); sp.to_csv(f"{PRO}/sweep_speedup.csv", index=False)
    for dt in ("f32", "f64"):   # E1: speedup + throughput per kernel
        fig, axs = plt.subplots(2, 4, figsize=(18, 7), sharex=True)
        for j, k in enumerate(("saxpy", "mul", "dot", "stencil")):
            for v in ("scalar", "auto", "native", "native_fm"):
                d = g[(g.kernel == k) & (g.dtype == dt) & (g.variant == v)].sort_values("ws")
                axs[0, j].errorbar(d.ws, d.gflops, yerr=d.gflops * d.rel_err, label=v, marker=".", capsize=2, color=COL[v])
                if v != "scalar":
                    s = sp[(sp.kernel == k) & (sp.dtype == dt) & (sp.variant == v)].sort_values("ws")
                    axs[1, j].errorbar(s.ws, s.speedup, yerr=s.sp_err, label=v, marker=".", capsize=2, color=COL[v])
            axs[0, j].set_title(f"{k} {dt}"); axs[0, j].set_xscale("log"); axs[0, j].set_yscale("log"); axs[0, j].set_ylabel("GFLOP/s")
            axs[1, j].set_xscale("log"); axs[1, j].axhline(1, c="k", lw=.5); axs[1, j].set_ylabel("speedup vs scalar (x)"); axs[1, j].set_xlabel("working set (bytes)")
            for a in axs[:, j]: cache_lines(a)
        axs[0, 0].legend(); fig.suptitle(f"E1: scalar vs auto-vectorized vs native-ISA ({dt}); error bars = std over reps"); fig.tight_layout(); fig.savefig(f"{PLT}/e1_sweep_{dt}.png", dpi=130); plt.close(fig)
    # E2 locality sweep (saxpy f32): GiB/s + speedup, annotated
    fig, ax = plt.subplots(figsize=(8, 5)); ax2 = ax.twinx()
    for v in ("scalar", "native"):
        d = g[(g.kernel == "saxpy") & (g.dtype == "f32") & (g.variant == v)].sort_values("ws"); ax.errorbar(d.ws, d.gibs, yerr=d.gibs * d.rel_err, marker=".", label=f"{v} GiB/s", capsize=2)
    s = sp[(sp.kernel == "saxpy") & (sp.dtype == "f32") & (sp.variant == "native")].sort_values("ws"); ax2.plot(s.ws, s.speedup, "k--", label="speedup (right)")
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlabel("working set (bytes)"); ax.set_ylabel("nominal GiB/s"); ax2.set_ylabel("native/scalar speedup (x)"); cache_lines(ax)
    ax.legend(loc="lower left"); ax2.legend(loc="upper right"); ax.set_title("E2: locality sweep, SAXPY f32 (SIMD gain compresses past L2/L3)"); fig.tight_layout(); fig.savefig(f"{PLT}/e2_locality_saxpy.png", dpi=130); plt.close(fig)
    # E5 data type comparison at L1-resident (ws ~ 16 KiB) vs DRAM-resident
    rows = []
    for k in ("saxpy", "mul", "dot", "stencil"):
        for dt in SZ:
            for regime, lo, hi in (("L1", 8e3, 32e3), ("DRAM", 4 * L3, 1e12)):
                d = sp[(sp.kernel == k) & (sp.dtype == dt) & (sp.variant == "native_fm") & (sp.ws_s >= lo) & (sp.ws_s <= hi)]
                if len(d): rows.append(dict(kernel=k, dtype=dt, regime=regime, speedup=d.speedup.median()))
    dtc = pd.DataFrame(rows); dtc.to_csv(f"{PRO}/dtype_compare.csv", index=False)
    if len(dtc):
        fig, axs = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
        for a, r in zip(axs, ("L1", "DRAM")):
            p = dtc[dtc.regime == r].pivot(index="kernel", columns="dtype", values="speedup")
            if p.empty: a.set_title(f"{r}: no data"); continue
            p.plot.bar(ax=a); a.set_title(f"E5: native_fm speedup, {r}-resident"); a.set_ylabel("speedup vs scalar (x)")
        fig.tight_layout(); fig.savefig(f"{PLT}/e5_dtype.png", dpi=130); plt.close(fig)
    # Roofline
    pk = load("peak")
    rd0 = g[(g.kernel == "dot") & (g.dtype == "f32") & (g.variant == "native_fm") & (g.ws > 4 * L3)]
    if pk is not None and len(rd0):
        peak32 = pk[pk.dtype == "f32"].gflops.iloc[0]
        rd = g[(g.kernel == "dot") & (g.dtype == "f32") & (g.variant == "native_fm") & (g.ws > 4 * L3)]
        bw = (rd.bytes / rd.t_med / 1e9).max()   # GB/s, best single-thread read stream at DRAM size
        fig, ax = plt.subplots(figsize=(7, 5)); ai = np.logspace(-2, 2, 100); ax.loglog(ai, np.minimum(peak32, ai * bw), "k", label=f"roof: {peak32:.0f} GFLOP/s, {bw:.1f} GB/s (1 thread)")
        for k in ("saxpy", "mul", "dot", "stencil"):
            for v, m in (("scalar", "s"), ("native_fm", "o")):
                d = g[(g.kernel == k) & (g.dtype == "f32") & (g.variant == v)]
                big = d[d.ws > 4 * L3]
                if len(big): ax.loglog(META[k][0] / (META[k][1] * 4), big.gflops.max(), m, color=f"C{('saxpy','mul','dot','stencil').index(k)}", label=f"{k} {v} (DRAM)")
                if len(d): ax.loglog(META[k][0] / (META[k][1] * 4), d.iloc[(d.ws - 16 * 1024).abs().argmin()].gflops, m, mfc="none", color=f"C{('saxpy','mul','dot','stencil').index(k)}", label=f"{k} {v} (L1, 16 KiB)")
        ax.set_xlabel("arithmetic intensity (FLOP/byte, nominal)"); ax.set_ylabel("GFLOP/s"); ax.legend(fontsize=6, ncol=2); ax.set_title("Roofline (single thread, f32): filled = DRAM, hollow = L1\n(L1 points lie above the DRAM-bandwidth slope: L1 bandwidth is far higher)", fontsize=9); fig.tight_layout(); fig.savefig(f"{PLT}/e7_roofline.png", dpi=130); plt.close(fig)
        pd.DataFrame([dict(peak_f32_gflops=peak32, bw_gbs=bw, ridge_ai=peak32 / bw)]).to_csv(f"{PRO}/roofline_params.csv", index=False)

al = load("align")
if al is not None:
    a = agg(al, ["variant", "kernel", "N", "offx", "offy", "dtype", "stride"]); a["label"] = a.apply(lambda r: f"x+{r.offx}/y+{r.offy}", axis=1); a.to_csv(f"{PRO}/align_agg.csv", index=False)
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.5))
    for ax, N in zip(axs, (2048, 1 << 22)):
        for v in ("scalar", "native"):
            d = a[(a.N == N) & (a.kernel == "saxpy") & (a.variant == v)]; ax.errorbar(range(len(d)), d.t_med / N * 1e9, yerr=d.t_std / N * 1e9, marker="o", label=v, capsize=3)
        ax.set_xticks(range(len(d))); ax.set_xticklabels(d.label, rotation=60, fontsize=7); ax.set_ylabel("ns / element"); ax.set_title(f"E3 alignment, saxpy f32, N={N}"); ax.legend()
    fig.tight_layout(); fig.savefig(f"{PLT}/e3_alignment.png", dpi=130); plt.close(fig)
tl = load("tail")
if tl is not None:
    t = agg(tl, ["variant", "kernel", "N", "offx", "offy", "dtype", "stride"]); t.to_csv(f"{PRO}/tail_agg.csv", index=False)
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.5))
    for v in ("scalar", "auto", "native"):
        d = t[(t.variant == v) & (t.N <= 72)]; axs[0].plot(d.N, d.t_med / d.N * 1e9, ".-", label=v)
        d = t[(t.variant == v) & (t.N >= 4096)]; axs[1].errorbar(d.N - 4096, d.t_med * 1e9, yerr=d.t_std * 1e9, marker="o", label=v, capsize=2)
    axs[0].set_xlabel("N"); axs[0].set_ylabel("ns / element"); axs[0].set_title("E3b: small-N overhead (prologue/epilogue/remainder)"); axs[0].set_yscale("log"); axs[0].legend()
    axs[1].set_xlabel("remainder r in N = 4096 + r"); axs[1].set_ylabel("ns / call"); axs[1].set_title("E3c: remainder-loop cost"); axs[1].legend(); fig.tight_layout(); fig.savefig(f"{PLT}/e3_tail.png", dpi=130); plt.close(fig)
st = load("stride")
if st is not None:
    s = derive(agg(st, ["variant", "kernel", "dtype", "N", "offx", "offy", "stride"])); s.to_csv(f"{PRO}/stride_agg.csv", index=False)
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.5))
    for ax, N in zip(axs, (4096, 1 << 22)):
        for dt in SZ:
            for v in ("scalar", "native"):
                d = s[(s.kernel == "stride") & (s.N == N) & (s.dtype == dt) & (s.variant == v)].sort_values("stride")
                ax.errorbar(d.stride, d.gibs, yerr=d.gibs * d.rel_err, marker="o", label=f"{v} {dt}", capsize=2)
                gg = s[(s.kernel == "gather") & (s.N == N) & (s.dtype == dt) & (s.variant == v)]
                if len(gg): ax.plot([20], gg.gibs, "x", ms=9)
        ax.set_xscale("log", base=2); ax.set_yscale("log"); ax.set_xlabel("stride (elements); x at 20 = random gather"); ax.set_ylabel("useful GiB/s (nominal)"); ax.set_title(f"E4 stride/gather N={N}"); ax.legend(fontsize=7)
    fig.tight_layout(); fig.savefig(f"{PLT}/e4_stride_gather.png", dpi=130); plt.close(fig)

la = load("loopalign")
if la is not None:
    la = la.assign(ns=la.sec_per_call / la.N * 1e9); G = la.groupby(["kernel", "dtype", "variant"]).ns.agg(["median", "std"]).reset_index(); G.to_csv(f"{PRO}/loopalign_agg.csv", index=False)
    order = ["scalar", "scalar_al", "native", "native_al", "native_fm", "native_fm_al"]; cases = [(k, t) for k in ("saxpy", "mul", "dot") for t in ("f32", "f64")]
    fig, axs = plt.subplots(1, 6, figsize=(21, 3.9))
    for ax, (k, t) in zip(axs, cases):
        d = G[(G.kernel == k) & (G.dtype == t)].set_index("variant").reindex(order)
        for i, v in enumerate(order): ax.bar(i, d.loc[v, "median"], yerr=d.loc[v, "std"], color=COL[v.replace("_al", "")], hatch="//" if v.endswith("_al") else "", edgecolor="k", capsize=2)
        ax.set_xticks(range(6)); ax.set_xticklabels(order, rotation=60, fontsize=7); ax.set_title(f"{k} {t}"); ax.set_ylabel("ns / element (N = 1024)" if (k, t) == cases[0] else "")
    fig.suptitle("Loop-placement test: hatched = same flags + -falign-loops=64; error bars = std over 11 repetitions", fontsize=10); fig.tight_layout(); fig.savefig(f"{PLT}/e8_loop_placement.png", dpi=130); plt.close(fig)
print("plots ->", PLT)
