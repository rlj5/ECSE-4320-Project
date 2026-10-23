#!/usr/bin/env python3
"""Project 2: raw CSV -> processed CSV + plots. Error bars = std over repetitions (reps within a process, plus processes where applicable)."""
import os, numpy as np, pandas as pd, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
H = os.path.dirname(os.path.abspath(__file__)); RAW, PRO, PLT = f"{H}/data/raw", f"{H}/data/processed", f"{H}/plots"; os.makedirs(PRO, exist_ok=True); os.makedirs(PLT, exist_ok=True)
L1, L2, L3 = 32 * 1024, 512 * 1024, 16 * 2**20   # Ryzen 7 5825U; edit for other CPUs
def load(n): p = f"{RAW}/{n}.csv"; return pd.read_csv(p) if os.path.exists(p) else None
FREQ = float(open(f"{RAW}/freq_estimate_ghz.txt").read().split()[0]) if os.path.exists(f"{RAW}/freq_estimate_ghz.txt") else np.nan
def ann(ax, ys=None):
    for x, l in ((L1, "L1d 32K"), (L2, "L2 512K"), (L3, "L3 16M")): ax.axvline(x, ls=":", c="gray"); ax.text(x, ax.get_ylim()[1], l, rotation=90, va="top", ha="right", fontsize=7, color="gray")
def knee(x, y):  # Kneedle-style: point farthest below the chord between first and last points of the (normalised) throughput-latency curve
    x, y = np.asarray(x, float), np.asarray(y, float); o = np.argsort(x); x, y = x[o], y[o]
    if len(x) < 3: return None
    xn = (x - x[0]) / (x[-1] - x[0] + 1e-12); yn = (y - y[0]) / (y[-1] - y[0] + 1e-12); return o[np.argmax(xn - yn)]
def ga(df, keys, col): return df.groupby(keys)[col].agg(["median", "std", "count"]).reset_index()

zq = load("zero_queue")
if zq is not None:
    t = ga(zq, ["level", "huge"], "lat_ns"); t["cycles"] = t["median"] * FREQ; t.rename(columns={"median": "lat_ns_median", "std": "lat_ns_std", "count": "n"}, inplace=True)
    t.to_csv(f"{PRO}/zero_queue_table.csv", index=False)
    
    try: body = t.to_markdown(index=False, floatfmt=".2f")
    except ImportError: body = t.to_string()
    open(f"{PRO}/zero_queue_table.md", "w").write(f"core clock estimate: {FREQ:.2f} GHz (dependent-add loop; may differ from actual during memory-bound phases)\n\n" + body); print(t)
ws = load("ws_sweep")
if ws is not None:
    fig, ax = plt.subplots(figsize=(8, 5))
    for pat, g in ws.groupby("pattern"):
        a = ga(g, ["ws_bytes"], "lat_ns"); ax.errorbar(a.ws_bytes, a["median"], yerr=a["std"].fillna(0), marker=".", label=f"{pat} chase", capsize=2)
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlabel("working set (bytes)"); ax.set_ylabel("latency per dependent load (ns)")
    sec = ax.secondary_yaxis("right", functions=(lambda n: n * FREQ, lambda c: c / FREQ)); sec.set_ylabel(f"cycles @ {FREQ:.2f} GHz"); ann(ax); ax.legend(); ax.set_title("E-WS: working-set sweep (note seq << rand once prefetchers engage)")
    fig.tight_layout(); fig.savefig(f"{PLT}/ws_sweep_latency.png", dpi=130); plt.close(fig)
pl, pb = load("pattern_lat"), load("pattern_bw")
if pl is not None and pb is not None:
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.5)); a = ga(pl, ["pattern", "gran"], "lat_ns")
    for pat, g in a.groupby("pattern"): axs[0].errorbar(g.gran, g["median"], yerr=g["std"].fillna(0), marker="o", label=pat, capsize=3)
    axs[0].set_xscale("log", base=2); axs[0].set_xlabel("node granularity / stride (B)"); axs[0].set_ylabel("latency (ns)"); axs[0].set_title("DRAM-resident chase latency"); axs[0].legend()
    for (T, pat), g in pb.groupby(["threads", "pattern"]): axs[1].plot(g.stride, g.bw_GBps, "o-", label=f"{T} thr {pat}")
    axs[1].set_xscale("log", base=2); axs[1].set_xlabel("stride between 64B line touches (B)"); axs[1].set_ylabel("bandwidth of useful bytes (GB/s)"); axs[1].set_title("Bandwidth vs pattern/stride"); axs[1].legend(fontsize=7)
    fig.tight_layout(); fig.savefig(f"{PLT}/pattern_granularity.png", dpi=130); plt.close(fig); pb.to_csv(f"{PRO}/pattern_bw.csv", index=False)
rw = load("rw_mix")
if rw is not None:
    fig, axs = plt.subplots(1, 2, figsize=(11, 4)); 
    for pat, g in rw.groupby("pattern"): axs[0].plot(g.readpct, g.bw_GBps, "o-", label=pat); axs[1].plot(g.readpct, g.lat_ns, "o-", label=pat)
    for a, y in zip(axs, ("bandwidth (GB/s)", "loaded latency (ns)")): a.set_xlabel("% reads"); a.set_ylabel(y); a.invert_xaxis(); a.legend()
    fig.suptitle("Read/write mix (latency measured by a concurrent chase thread)"); fig.tight_layout(); fig.savefig(f"{PLT}/rw_mix.png", dpi=130); plt.close(fig)
for iname, ifig, icsv in (("intensity", "intensity_knee.png", "knee_summary.csv"), ("intensity_seq", "intensity_knee_seq.png", "knee_summary_seq.csv")):
  it = load(iname)
  if it is not None:
      fig, axs = plt.subplots(1, 2, figsize=(12, 4.8)); rows = []
      for T, g in it.groupby("threads"):
          g = g.sort_values("bw_GBps"); axs[0].plot(g.bw_GBps, g.lat_ns, "o-", label=f"{T} load thr")
          g = g.assign(inflight=g.Mlines_s * 1e6 * g.lat_ns * 1e-9)   # Little's Law: L = lambda * W  (cache lines in flight, whole-system)
          axs[1].plot(g.delay, g.inflight, "o-", label=f"{T} load thr")
          k = knee(g.bw_GBps, g.lat_ns); rows.append(dict(threads=T, knee_bw=g.bw_GBps.iloc[k] if k is not None else np.nan, knee_lat=g.lat_ns.iloc[k] if k is not None else np.nan, max_bw=g.bw_GBps.max(), unloaded_lat=g.lat_ns.min()))
          if k is not None: axs[0].plot(g.bw_GBps.iloc[k], g.lat_ns.iloc[k], "k*", ms=12)
      axs[0].set_xlabel("load-thread bandwidth (GB/s)"); axs[0].set_ylabel("latency seen by probe thread (ns)"); axs[0].set_title("Throughput-latency (stars = knee)"); axs[0].legend()
      axs[1].set_xscale("symlog"); axs[1].set_xlabel("injected delay (spin iters)"); axs[1].set_ylabel("lines in flight = BW/64 x latency (Little)"); axs[1].set_title("Little's Law concurrency"); axs[1].legend()
      fig.tight_layout(); fig.savefig(f"{PLT}/{ifig}", dpi=130); plt.close(fig); pd.DataFrame(rows).to_csv(f"{PRO}/{icsv}", index=False)
ch = load("chains")
if ch is not None:
    a = ga(ch.assign(thr=ch.thr_Mloads_s), ["chains"], "thr"); b = ga(ch, ["chains"], "lat_ns"); a["lat_ns"] = b["median"]; a["little_inflight"] = a["median"] * 1e6 * a.lat_ns * 1e-9
    a.to_csv(f"{PRO}/chains_littles_law.csv", index=False); fig, axs = plt.subplots(1, 2, figsize=(11, 4))
    axs[0].errorbar(a.chains, a["median"], yerr=a["std"].fillna(0), marker="o"); axs[0].set_xlabel("independent chains (= requested MLP)"); axs[0].set_ylabel("loads/us"); axs[0].set_title("Single-core MLP scaling")
    axs[1].plot(a["median"], a.lat_ns, "o-"); [axs[1].annotate(int(c), (x, y)) for c, x, y in zip(a.chains, a["median"], a.lat_ns)]; axs[1].set_xlabel("throughput (Mloads/s)"); axs[1].set_ylabel("latency (ns)"); axs[1].set_title("Throughput-latency, 1 core (labels = chains)")
    fig.tight_layout(); fig.savefig(f"{PLT}/chains_mlp.png", dpi=130); plt.close(fig)
cm = load("cache_miss")
if cm is not None:
    cm["ns_per_line"] = 1e3 / cm.Mlines_s; ops = cm.Mlines_s * 1e6 * cm.secs
    for e, c in (("l1mpo", "L1-dcache-load-misses"), ("llcmpo", "cache-misses"), ("dtlbmpo", "dTLB-load-misses")): cm[e] = cm[c] / ops
    cm.to_csv(f"{PRO}/cache_miss_processed.csv", index=False); HAVE_CTR = bool(cm.l1mpo.notna().any()); fig, axs = plt.subplots(1, 2 if HAVE_CTR else 1, figsize=(12 if HAVE_CTR else 6.5, 4.5), squeeze=False); axs = axs[0]
    for pat, g in cm.groupby("pattern"):
        axs[0].plot(g.ws_bytes, g.ns_per_line, "o-", label=f"{pat}: ns/line-op"); 
        if g.l1mpo.notna().any(): axs[1].plot(g.ws_bytes, g.l1mpo, "o-", label=f"{pat} L1 miss/op"); axs[1].plot(g.ws_bytes, g.llcmpo, "s--", label=f"{pat} cache-miss/op")
    for a in axs: a.set_xscale("log"); a.set_xlabel("working set per thread (bytes)"); a.legend(fontsize=7)
    axs[0].set_yscale("log"); axs[0].set_ylabel("ns per 64B line operation"); ann(axs[0])
    if HAVE_CTR: axs[1].set_ylabel("misses per line op (perf)"); axs[1].set_yscale("log"); ann(axs[1])
    fig.suptitle("Cache-miss impact: runtime vs perf counters" if HAVE_CTR else "Footprint sweep: runtime per line operation (no hardware counters available)"); fig.tight_layout(); fig.savefig(f"{PLT}/cache_miss_impact.png", dpi=130); plt.close(fig)
tl = load("tlb")
if tl is not None:
    tl["pages"] = tl.ws_bytes / 4096; fig, axs = plt.subplots(1, 2, figsize=(12, 4.5))
    for h, g in tl.groupby("huge"):
        a = ga(g, ["pages"], "lat_ns"); axs[0].errorbar(a.pages, a["median"], yerr=a["std"].fillna(0), marker="o", label=f"{'THP (2 MiB pages)' if h else '4 KiB pages'}", capsize=2)
    axs[0].set_xscale("log", base=2); axs[0].set_yscale("log"); axs[0].set_xlabel("distinct 4 KiB pages touched (1 line each)"); axs[0].set_ylabel("latency (ns)"); axs[0].set_title("TLB reach: 4 KiB pages vs transparent huge pages"); axs[0].legend()
    for x, l in ((64, "L1 DTLB 64"), (512, "L1D 32 KiB of lines"), (2048, "L2 DTLB 2048")): axs[0].axvline(x, ls=":", c="gray"); axs[0].text(x, axs[0].get_ylim()[0] * 1.2, l, rotation=90, fontsize=7, color="gray", ha="right")
    m = tl.groupby(["pages", "huge"]).lat_ns.median().unstack("huge"); d = (m[0] - m[1]).dropna()
    axs[1].plot(d.index, d.values, "o-"); axs[1].axhline(0, c="k", lw=.5); axs[1].set_xscale("log", base=2); axs[1].set_xlabel("distinct 4 KiB pages touched"); axs[1].set_ylabel("latency(4 KiB pages) - latency(THP)  (ns)")
    axs[1].set_title("Cost of TLB misses (same cache footprint in both runs)")
    for x in (64, 2048): axs[1].axvline(x, ls=":", c="gray")
    fig.tight_layout(); fig.savefig(f"{PLT}/tlb_impact.png", dpi=130); plt.close(fig); d.rename("delta_ns").to_csv(f"{PRO}/tlb_delta.csv")
pp, pc = load("pitfall_pin"), load("pitfall_cachereuse")
if pp is not None and pc is not None:
    fig, axs = plt.subplots(1, 2, figsize=(11, 4)); axs[0].boxplot([pp[pp["mode"] == m].lat_ns for m in ("pinned", "unpinned")]); axs[0].set_xticklabels(["pinned", "unpinned"]); axs[0].set_ylabel("latency (ns)"); axs[0].set_title("Pitfall: not pinning (spread across 12 runs)")
    axs[1].plot(pc.ws_bytes, pc.bw_GBps, "o-"); axs[1].set_xscale("log"); axs[1].set_xlabel("buffer size (bytes)"); axs[1].set_ylabel("'DRAM' read bandwidth (GB/s)"); axs[1].set_title("Pitfall: cache-resident buffer reported as DRAM"); ann(axs[1])
    fig.tight_layout(); fig.savefig(f"{PLT}/pitfalls.png", dpi=130); plt.close(fig)
pf = load("pitfall_freq")
if pf is not None: pf.groupby(["max_khz", "ws_bytes"]).lat_ns.agg(["median", "std"]).reset_index().to_csv(f"{PRO}/pitfall_freq_summary.csv", index=False)

# AMAT model, counter-free miss inference, crosscheck, power-mode pitfall
import glob
def amat_pred(W, lat, caps=(L1, L2, L3)):
    h1 = min(1, caps[0] / W); h12 = min(1, caps[1] / W); h123 = min(1, caps[2] / W)
    return h1 * lat["L1"] + (h12 - h1) * lat["L2"] + (h123 - h12) * lat["L3"] + (1 - h123) * lat["DRAM"]
if zq is not None and ws is not None:
    zt = zq[zq.huge == 1].groupby("level").lat_ns.median().to_dict()
    if all(k in zt for k in ("L1", "L2", "L3", "DRAM")):
        a = ws[ws.pattern == "rand"].groupby("ws_bytes").lat_ns.median().reset_index(); a["amat_model_ns"] = a.ws_bytes.map(lambda W: amat_pred(W, zt))
        a["implied_miss_to_DRAM"] = ((a.lat_ns - zt["L1"]) / (zt["DRAM"] - zt["L1"])).clip(0, 1); a["model_miss_to_DRAM"] = a.ws_bytes.map(lambda W: max(0, 1 - L3 / W))
        a.to_csv(f"{PRO}/amat_model.csv", index=False); fig, axs = plt.subplots(1, 2, figsize=(12, 4.5))
        axs[0].plot(a.ws_bytes, a.lat_ns, "o-", label="measured (random chase, THP)"); axs[0].plot(a.ws_bytes, a.amat_model_ns, "s--", label="AMAT capacity model")
        axs[0].set_xscale("log"); axs[0].set_yscale("log"); axs[0].set_xlabel("working set (bytes)"); axs[0].set_ylabel("average memory access time (ns)"); ann(axs[0]); axs[0].legend(); axs[0].set_title("AMAT: measured vs model (levels from zero-queue table)")
        axs[1].plot(a.ws_bytes, a.implied_miss_to_DRAM, "o-", label="implied by measured AMAT"); axs[1].plot(a.ws_bytes, a.model_miss_to_DRAM, "s--", label="model: 1 - C_L3/W")
        axs[1].set_xscale("log"); axs[1].set_xlabel("working set (bytes)"); axs[1].set_ylabel("fraction of accesses going to DRAM"); axs[1].legend(); axs[1].set_title("Counter-free miss-rate inference"); ann(axs[1])
        fig.tight_layout(); fig.savefig(f"{PLT}/amat_model.png", dpi=130); plt.close(fig)
if cm is not None:
    c = cm.groupby(["pattern", "ws_bytes"]).ns_per_line.median().reset_index()
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for pat, g in c.groupby("pattern"):
        lo, hi = g.ns_per_line.iloc[:2].min(), g.ns_per_line.iloc[-2:].max(); ax.plot(g.ws_bytes, ((g.ns_per_line - lo) / (hi - lo)).clip(0, 1), "o-", label=f"{pat}")
    ax.set_xscale("log"); ax.set_xlabel("working set per thread (bytes)"); ax.set_ylabel("inferred fraction of DRAM-like cost per line op"); ax.legend(); ann(ax); ax.set_title("Cache-miss impact inferred from runtime (no counters needed)")
    fig.tight_layout(); fig.savefig(f"{PLT}/cache_miss_inferred.png", dpi=130); plt.close(fig)
xc = load("crosscheck")
if xc is not None:
    piv = xc.pivot_table(index="threads", columns="tool", values="best_GBps").reset_index(); piv["membw70/triad"] = piv.membw70 / piv.triad; piv.to_csv(f"{PRO}/crosscheck.csv", index=False)
    fig, ax = plt.subplots(figsize=(6, 4)); ax.plot(piv.threads, piv.triad, "o-", label="STREAM-style triad (OpenMP)"); ax.plot(piv.threads, piv.membw70, "s--", label="membw 70/30 seq")
    ax.set_xlabel("threads"); ax.set_ylabel("counted GB/s"); ax.legend(); ax.set_title("Independent cross-check of the bandwidth tool"); fig.tight_layout(); fig.savefig(f"{PLT}/crosscheck.png", dpi=130); plt.close(fig)
tags = {os.path.basename(f)[len("zero_queue_"):-4]: pd.read_csv(f) for f in glob.glob(f"{RAW}/zero_queue_*.csv")}
if tags and zq is not None:
    tags = {"default": zq, **tags}; fig, ax = plt.subplots(figsize=(7, 4.5)); lv = ["L1", "L2", "L3", "DRAM"]
    for i, (tg, d) in enumerate(tags.items()):
        m = d[d.huge == 1].groupby("level").lat_ns.median().reindex(lv); ax.bar(np.arange(4) + i * 0.8 / len(tags), m.values, 0.8 / len(tags), label=tg)
    ax.set_xticks(np.arange(4) + 0.4); ax.set_xticklabels(lv); ax.set_yscale("log"); ax.set_ylabel("latency (ns)"); ax.legend(title="run tag (e.g. Windows power mode)"); ax.set_title("Pitfall: same benchmark under different power settings")
    fig.tight_layout(); fig.savefig(f"{PLT}/pitfall_power_mode.png", dpi=130); plt.close(fig)
print("plots ->", PLT)
