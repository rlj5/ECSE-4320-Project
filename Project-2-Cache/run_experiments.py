#!/usr/bin/env python3
"""Project 2 driver. Writes data/raw/*.csv. Env: CPUS=0,1,2,... (logical CPUs, one per physical core; auto-detected by default)
Flags: --quick (shorter), --only a,b,c   Experiments: zero_queue ws_sweep pattern rw_mix intensity intensity_seq chains cache_miss tlb pitfalls"""
import subprocess, os, sys, shutil, argparse, math, csv, io
HERE = os.path.dirname(os.path.abspath(__file__)); B = f"{HERE}/build"; RAW = f"{HERE}/data/raw"; os.makedirs(RAW, exist_ok=True)
ap = argparse.ArgumentParser(); ap.add_argument("--quick", action="store_true"); ap.add_argument("--only", default=""); ap.add_argument("--tag", default="", help="suffix for output files, e.g. --tag saver for a repeat under another Windows power mode"); args = ap.parse_args()
SECS = 1.0 if args.quick else 3.0; REPS = 3 if args.quick else 7
KiB, MiB, GiB = 1024, 2**20, 2**30
def phys_cpus():
    if os.environ.get("CPUS"): return [int(x) for x in os.environ["CPUS"].split(",")]
    seen, out = set(), []
    try:
        for l in subprocess.check_output(["lscpu", "-p=CPU,CORE"], text=True).splitlines():
            if l.startswith("#"): continue
            c, core = l.split(","); 
            if core not in seen: seen.add(core); out.append(int(c))
    except Exception: out = [0]
    return out
CPUS = phys_cpus(); NT = len(CPUS); print("physical CPUs used:", CPUS)
EVENTS = "cycles,instructions,L1-dcache-loads,L1-dcache-load-misses,cache-references,cache-misses,dTLB-loads,dTLB-load-misses"
def perf_works():   # perf may be installed yet unable to count hardware events (typical in WSL2): test it
    if not shutil.which("perf"): return False
    p = subprocess.run(["perf", "stat", "-x,", "-e", "cycles", "--", "true"], capture_output=True, text=True)
    return p.returncode == 0 and any(l.split(",")[0].strip().isdigit() for l in p.stderr.splitlines() if l.count(",") > 1)
HAVE_PERF = perf_works(); print("hardware perf counters usable:", HAVE_PERF)
def mem_avail_gib():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable"): return int(l.split()[1]) / 2**20
    return 0.0
LOADWS = 256 * MiB if mem_avail_gib() >= 3.5 else 128 * MiB    # per-thread private buffer; ~(threads+1) x this is allocated at once
if LOADWS < 256 * MiB: print("WARNING: low MemAvailable; using 128 MiB per-thread buffers (still >> 16 MiB L3)")
def perf_wrap(cmd):
    if not HAVE_PERF: return cmd, None
    return ["perf", "stat", "-x,", "-e", EVENTS, "--"] + cmd, True
def parse_perf(err):
    d = {}
    for l in err.splitlines():
        p = l.split(",")
        if len(p) > 2:
            try: d[p[2].split(":")[0]] = float(p[0])
            except ValueError: d[p[2].split(":")[0]] = float("nan")
    return d
def sh(cmd, pin=None, perf=False):
    if pin is not None: cmd = ["taskset", "-c", str(pin)] + cmd
    if perf: cmd, _ = perf_wrap(cmd)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0: sys.exit(f"FAILED {cmd}\n{p.stderr}")
    return p.stdout.strip().splitlines(), (parse_perf(p.stderr) if perf and HAVE_PERF else {})
def hdr(tool): return subprocess.check_output([f"{B}/{tool}", "--header"], text=True).strip()
def lat(ws, gran=64, pattern="rand", chains=1, huge=1, pin=True, perf=False, reps=None):
    r, pc = sh([f"{B}/memlat", str(ws), "--gran", str(gran), "--pattern", pattern, "--chains", str(chains), "--huge", str(huge), "--reps", str(reps or REPS)], CPUS[0] if pin else None, perf)
    return [x + "," + ",".join(f"{pc.get(e, float('nan')):.0f}" for e in EVENTS.split(",")) if perf else x for x in r]
def bw(ws, threads, pattern="seq", stride=64, read=100, delay=0, secs=None, lat_ws=0, perf=False, cpus=None):
    cl = cpus or [CPUS[i % NT] for i in range(threads + (1 if lat_ws else 0))]   # wraps (shares cores) only if fewer cores than threads
    cmd = [f"{B}/membw", "--ws", str(ws), "--threads", str(threads), "--pattern", pattern, "--stride", str(stride), "--read", str(read), "--delay", str(delay), "--secs", str(secs or SECS), "--cpus", ",".join(map(str, cl))] + (["--lat_ws", str(lat_ws)] if lat_ws else [])
    r, pc = sh(cmd, None, perf)
    return [x + "," + ",".join(f"{pc.get(e, float('nan')):.0f}" for e in EVENTS.split(",")) if perf else x for x in r]
def save(name, header, rows, perf=False):
    h = header + ("," + EVENTS if perf else "")
    open(f"{RAW}/{name}{'_' + args.tag if args.tag else ''}.csv", "w").write(h + "\n" + "\n".join(rows) + "\n"); print("wrote", name, len(rows), flush=True)
def half_octaves(lo, hi): return sorted({int(2 ** (e / 2)) // 64 * 64 for e in range(2 * lo, 2 * hi + 1)})
_f = subprocess.check_output([f"{B}/memlat", "--freq"], text=True).split(); FREQ = float(_f[0]); _freq_name = f"freq_estimate_{args.tag}.txt" if args.tag else "freq_estimate_ghz.txt"; open(f"{RAW}/{_freq_name}", "w").write(f"{_f[0]} {_f[1]}\n")
print(f"core clock estimate GHz: add-chain {_f[0]}, imul-chain {_f[1]} (should agree within a few percent)")
if abs(float(_f[0]) - float(_f[1])) / float(_f[0]) > 0.1: print("WARNING: clock estimates disagree by >10%; ns->cycle conversions are unreliable")
DRAM = min(LOADWS * 2, 256 * MiB) if args.quick else (1 * GiB if LOADWS >= 256 * MiB else 512 * MiB)
def zero_queue():  # random chase, 1 chain; THP on (huge=1) to minimise TLB contamination; also huge=0 for comparison
    rows = []
    for name, ws in (("L1", 16 * KiB), ("L2", 256 * KiB), ("L3", 8 * MiB), ("DRAM", DRAM)):
        for huge in (1, 0): rows += [f"{name},{x}" for x in lat(ws, huge=huge)]
    save("zero_queue", "level," + hdr("memlat"), rows)
def ws_sweep():
    rows = []
    for pat in ("rand", "seq"):
        for ws in half_octaves(12, 30 if not args.quick else 28): rows += lat(ws, pattern=pat)
    save("ws_sweep", hdr("memlat"), rows)
def pattern():
    rows = []
    for pat in ("rand", "seq"):
        for g in (64, 256, 1024): rows += lat(2 * LOADWS if not args.quick else LOADWS, gran=g, pattern=pat)
    save("pattern_lat", hdr("memlat"), rows)
    rows = []
    for T in (1, NT):
        for pat in ("seq", "rand"):
            for s in (64, 256, 1024): rows += bw(LOADWS, T, pat, s)
    save("pattern_bw", hdr("membw"), rows)
def rw_mix():
    rows = []
    for pat in ("seq", "rand"):
        for rp in (100, 70, 50, 0): rows += bw(LOADWS, max(1, NT - 1), pat, 64, rp, lat_ws=LOADWS)
    save("rw_mix", hdr("membw"), rows)
def intensity():
    rows = []; delays = [0, 20, 50, 100, 200, 500, 1000, 3000, 10000, 40000]
    for T in sorted({1, 2, 4, max(1, NT - 1)}):
        for d in delays: rows += bw(LOADWS, T, "rand", 64, 100, d, lat_ws=LOADWS)
    save("intensity", hdr("membw"), rows)
def intensity_seq():   # same sweep with SEQUENTIAL loads: random loads never saturate DRAM with this tool (see report 4.4), streams do
    rows = []; delays = [0, 20, 50, 100, 200, 500, 1000, 3000, 10000, 40000]
    for T in sorted({1, 2, 4, max(1, NT - 1)}):
        for d in delays: rows += bw(LOADWS, T, "seq", 64, 100, d, lat_ws=LOADWS)
    save("intensity_seq", hdr("membw"), rows)
def chains():
    rows = []
    for K in (1, 2, 3, 4, 6, 8, 12, 16): rows += lat(DRAM, chains=K)
    save("chains", hdr("memlat"), rows)
def cache_miss():
    rows = []
    for pat in ("seq", "rand"):
        for ws in [2**e for e in range(12, 31 if not args.quick else 29)]: rows += bw(ws, 1, pat, 64, 100, secs=SECS, perf=True)
    save("cache_miss", hdr("membw"), rows, perf=True)
def tlb():
    rows = []
    for huge in (0, 1):
        for ws in half_octaves(16, 30 if not args.quick else 28): rows += lat(ws, gran=4096, huge=huge, perf=True, reps=3)
    save("tlb", hdr("memlat"), rows, perf=True)
def crosscheck():   # independent STREAM-style triad vs membw at a matching read/write mix (70/30 ~ 2 reads + 1 write)
    rows = []
    for T in sorted({1, 2, 4, NT}):
        env = dict(os.environ, OMP_NUM_THREADS=str(T), OMP_PROC_BIND="true", OMP_PLACES=",".join("{%d}" % c for c in CPUS[:T]))
        p = subprocess.run([f"{B}/stream_triad", str(LOADWS)], capture_output=True, text=True, env=env)
        if p.returncode != 0: sys.exit(p.stderr)
        rows += ["triad," + x for x in p.stdout.strip().splitlines()]
        rows += [f"membw70,{T},{LOADWS}," + ",".join([x.split(",")[7]] * 2) for x in bw(LOADWS, T, "seq", 64, 70)]   # bw_GBps (single run: best = median)
    save("crosscheck", "tool,threads,bytes_per_array,best_GBps,median_GBps", rows)
def pitfalls():
    rows = []   # (a) pinning: 12 independent processes, pinned vs unpinned, DRAM-ish random chase
    for i in range(12):
        for pin in (True, False): rows += [f"{'pinned' if pin else 'unpinned'},{x}" for x in lat(LOADWS, pin=pin, reps=3)]
    save("pitfall_pin", "mode," + hdr("memlat"), rows)
    rows = []   # (b) 'DRAM bandwidth' measured with a buffer that actually lives in cache
    for ws in (1 * MiB, 4 * MiB, 8 * MiB, 32 * MiB, 128 * MiB, 512 * MiB): rows += bw(ws, 1, "seq", 64, 100)
    save("pitfall_cachereuse", hdr("membw"), rows)
    # (c) sequential-vs-random chase at DRAM size is already in pattern_lat.csv (prefetcher hides latency); (d) frequency: see pitfall_freq.sh
EXPS = dict(crosscheck=crosscheck, zero_queue=zero_queue, ws_sweep=ws_sweep, pattern=pattern, rw_mix=rw_mix, intensity=intensity, intensity_seq=intensity_seq, chains=chains, cache_miss=cache_miss, tlb=tlb, pitfalls=pitfalls)
for n in (args.only.split(",") if args.only else EXPS): print("==", n, flush=True); EXPS[n]()
