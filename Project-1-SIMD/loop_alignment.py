#!/usr/bin/env python3
"""For each build/kernel: first loop start when with/without 64-byte boundary
Writes to reports/loop_alignment.csv. Needs objdump and the binaries in build/."""
import subprocess, re, os, csv
H = os.path.dirname(os.path.abspath(__file__)); B = f"{H}/build"
def funcs(path):
    out = subprocess.run(["objdump", "-d", "--no-show-raw-insn", path], capture_output=True, text=True).stdout.splitlines(); cur = None; F = {}
    for l in out:
        m = re.match(r"^[0-9a-f]+ <(k_[A-Za-z0-9_.]+)>:", l)
        if m: cur = m.group(1); F[cur] = []; continue
        if not l.strip(): cur = None; continue
        m = re.match(r"\s*([0-9a-f]+):\t(.*)", l)
        if cur and m: F[cur].append((int(m.group(1), 16), m.group(2)))
    return F
rows = []
for v in ("scalar", "auto", "native", "native_fm", "scalar_al", "native_al", "native_fm_al"):
    p = f"{B}/bench_{v}"
    if not os.path.exists(p): continue
    F = funcs(p)
    for k in ("k_saxpy_f32", "k_saxpy_f64", "k_mul_f32", "k_mul_f64", "k_dot_f32", "k_dot_f64"):
        ins = F.get(k, [])
        for i, (a, t) in enumerate(ins):                       # first backward conditional jump = first loop in the function
            m = re.match(r"j\w+\s+([0-9a-f]+) <", t)
            if m and int(m.group(1), 16) < a:
                tgt = int(m.group(1), 16); end = ins[i + 1][0] if i + 1 < len(ins) else a + 2
                n = sum(1 for x in ins if tgt <= x[0] < end)
                rows.append(dict(build=v, function=k, loop_start=hex(tgt), loop_end=hex(end - 1), instructions=n, start_offset_in_64B=tgt % 64, crosses_64B_boundary=int(tgt // 64 != (end - 1) // 64))); break
os.makedirs(f"{H}/reports", exist_ok=True)
with open(f"{H}/reports/loop_alignment.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print(f"wrote reports/loop_alignment.csv ({len(rows)} rows)")
srows = []                                                  # every backward-branch loop in the strided kernels (which one runs depends on the stride)
for v in ("scalar", "native", "native_fm", "scalar_al", "native_al", "native_fm_al"):
    p = f"{B}/bench_{v}"
    if not os.path.exists(p): continue
    F = funcs(p)
    for k in ("k_stride_f32", "k_stride_f64"):
        ins = F.get(k, [])
        for i, (a, t) in enumerate(ins):
            m = re.match(r"j\w+\s+([0-9a-f]+) <", t)
            if m and int(m.group(1), 16) < a:
                tgt = int(m.group(1), 16); end = ins[i + 1][0] if i + 1 < len(ins) else a + 2
                srows.append(dict(build=v, function=k, loop_start=hex(tgt), loop_end=hex(end - 1), instructions=sum(1 for x in ins if tgt <= x[0] < end), start_offset_in_64B=tgt % 64, crosses_64B_boundary=int(tgt // 64 != (end - 1) // 64)))
with open(f"{H}/reports/loop_alignment_stride.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(srows[0].keys())); w.writeheader(); w.writerows(srows)
print(f"wrote reports/loop_alignment_stride.csv ({len(srows)} rows)")
