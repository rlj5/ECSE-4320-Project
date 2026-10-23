#!/usr/bin/env python3
"""Runs all Project 1 experiments, pinned to one core, writing data/raw/*.csv.
Env: CPU=<logical cpu to pin to (default 2)>  Flags: --quick (fewer sizes/reps), --only name[,name]"""
import subprocess, os, sys, argparse
HERE = os.path.dirname(os.path.abspath(__file__)); BUILD = f"{HERE}/build"; RAW = f"{HERE}/data/raw"
CPU = os.environ.get("CPU", "2")
HDR = "variant,kernel,dtype,N,offx,offy,stride,rep,sec_per_call,tsc_per_call,iters,sink"
ap = argparse.ArgumentParser(); ap.add_argument("--quick", action="store_true"); ap.add_argument("--tiny", action="store_true"); ap.add_argument("--only", default="")
args = ap.parse_args()
REPS = 3 if args.tiny else (5 if args.quick else 11)
HI = 18 if args.tiny else (24 if args.quick else 25)
VARIANTS = ["scalar", "auto", "native", "native_fm"]
os.makedirs(RAW, exist_ok=True)

def run(v, k, dt, N, reps=REPS, offx=0, offy=0, stride=1):
    cmd = ["taskset", "-c", CPU, f"{BUILD}/bench_{v}", k, dt, str(N), str(reps), str(offx), str(offy), str(stride)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0: sys.exit(f"FAILED {' '.join(cmd)}\n{p.stderr}")   # correctness check failure aborts the run
    return p.stdout.strip().splitlines()

def sizes(lo=9, hi=HI):  # half-octave steps, multiples of 16 elements => no vector remainder in the sweep
    return sorted({int(round(2 ** (e / 2) / 16)) * 16 for e in range(2 * lo, 2 * hi + 1)})

def save(name, rows):
    with open(f"{RAW}/{name}.csv", "w") as f: f.write(HDR + "\n" + "\n".join(rows) + "\n")
    print(f"wrote {name}.csv ({len(rows)} rows)", flush=True)

def sweep():
    rows = []
    for dt in ("f32", "f64"):
        for k in ("saxpy", "mul", "dot", "stencil"):
            for N in sizes():
                for v in VARIANTS: rows += run(v, k, dt, N)
    save("sweep", rows)

def align():  # (offx, offy) in bytes; L1-resident (N=2048 f32 => 8 KiB/array) vs DRAM-resident (N=2^22)
    pairs = [(o, o) for o in (0, 4, 8, 16, 32, 60)] + [(0, o) for o in (4, 8, 16, 32, 60)]
    rows = []
    for k in ("saxpy", "mul"):
        for N in (2048, 1 << 22):
            for v in ("scalar", "native"):
                for ox, oy in pairs: rows += run(v, k, "f32", N, offx=ox, offy=oy)
    save("align", rows)

def tail():   # tiny N exposes prologue/epilogue cost; N=4096+r exposes remainder loops
    rows = []
    for v in ("scalar", "auto", "native"):
        for N in list(range(3, 73)) + [4096 + r for r in range(16)]: rows += run(v, "saxpy", "f32", N)
    save("tail", rows)

def stride():
    rows = []
    for dt in ("f32", "f64"):
        for v in ("scalar", "native"):
            for N in (4096, 1 << 22):
                for s in (1, 2, 4, 8, 16): rows += run(v, "stride", dt, N, stride=s)
                rows += run(v, "gather", dt, N)
    save("stride", rows)

def loopalign():   
    rows = []
    variants_to_test = ["scalar", "scalar_al", "auto", "auto_al", "native", "native_al", "native_fm", "native_fm_al"]
    for k in ("saxpy", "mul", "dot", "stencil", "stride"):
        for dt in ("f32", "f64"):
            for v in variants_to_test: 
                rows += run(v, k, dt, 1024)
    save("loopalign", rows)

def peak():
    p = subprocess.run(["taskset", "-c", CPU, f"{BUILD}/peak_flops"], capture_output=True, text=True)
    open(f"{RAW}/peak.csv", "w").write(p.stdout); print(p.stdout)

EXPS = dict(sweep=sweep, align=align, tail=tail, stride=stride, peak=peak, loopalign=loopalign)
for name in (args.only.split(",") if args.only else EXPS):
    print("== running", name, flush=True); EXPS[name]()
