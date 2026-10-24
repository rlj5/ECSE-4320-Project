#!/usr/bin/env python3
"""Project 3 driver: FIO experiments -> data/raw/*.csv (+ raw fio JSON in data/raw/json/, time-series logs in data/raw/logs/).

TWO MODES (chosen by the target path):
  Windows mode  --target 'C:\\ssdtest\\bench.fio-testfile'   Runs the WINDOWS fio.exe (via WSL interop) against a file on the NTFS volume that lives on the SSD:
                the only valid way to measure the SSD from WSL2, whose own disk is a virtual disk (vhdx). Engine windowsaio, unbuffered (O_DIRECT-equivalent) I/O.
  Linux mode    --target /path/on/nvme/bench.fio-testfile   Native Linux fio (libaio, O_DIRECT). Use this on native Linux (live USB / dual boot).
SAFETY: the target must be a disposable file whose name ends in .fio-testfile. Windows mode never touches raw devices; Linux mode refuses block devices unless --allow-raw,
no partition may be mounted, and you must type the device path. tmpfs/overlay targets are refused (they cannot show SSD behaviour)."""
import argparse, glob, json, os, re, shutil, stat, subprocess, sys, threading, time
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); RAW = f"{HERE}/data/raw"
for d in (RAW, f"{RAW}/json", f"{RAW}/logs"): os.makedirs(d, exist_ok=True)
ap = argparse.ArgumentParser()
ap.add_argument("--target", required=True); ap.add_argument("--fio", default="", help="fio command (default: fio.exe in Windows mode, fio in Linux mode; full path allowed)")
ap.add_argument("--size", default="4G", help="main workload range (default matches the captured Project 3 run)"); ap.add_argument("--runtime", type=int, default=20); ap.add_argument("--ramp", type=int, default=3); ap.add_argument("--repeats", type=int, default=3)
ap.add_argument("--engine", default=""); ap.add_argument("--only", default=""); ap.add_argument("--quick", action="store_true"); ap.add_argument("--allow-raw", action="store_true")
ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--state-secs", type=int, default=600); ap.add_argument("--state-size", default="4G", help="device-state workload range (default matches the captured Project 3 run)"); ap.add_argument("--slc-gib", type=int, default=200, help="total GiB for the sequential-write (SLC cache) test")
ap.add_argument("--knee-qd", type=int, default=0); ap.add_argument("--precond-passes", type=int, default=1); ap.add_argument("--no-temp", action="store_true", help="do not read the SSD temperature")
ap.add_argument("--wsl-target", default="", help="optional: file on the WSL ext4 (virtual) disk for the 'wrong layer' pitfall demo; needs Linux fio inside WSL")
A = ap.parse_args()
WIN = re.match(r"^[A-Za-z]:[\\/]", A.target) is not None
if A.quick:
    if A.size == "32G": A.size = "4G"
    if A.state_size == "64G": A.state_size = "4G"
    A.runtime, A.ramp, A.repeats, A.state_secs, A.slc_gib = 5, 1, 1, 30, 6
ENGINE = A.engine or ("windowsaio" if WIN else "libaio")
FIO = A.fio or ("fio.exe" if WIN else "fio")
def to_bytes(s):
    m = re.fullmatch(r"(\d+)([KMGT]?)", s.upper()); return int(m.group(1)) * {"": 1, "K": 2**10, "M": 2**20, "G": 2**30, "T": 2**40}[m.group(2)]
SIZE, STATE_SIZE = to_bytes(A.size), to_bytes(A.state_size)
PCT = [50, 90, 95, 99, 99.9, 99.99]
def die(m): sys.exit("SAFETY/SETUP ERROR: " + m)
def to_unix(p):                      # Windows path -> path usable from WSL (wslpath if present, else /mnt/<drive>/...)
    if not re.match(r"^[A-Za-z]:[\\/]", p): return p
    if shutil.which("wslpath"):
        r = subprocess.run(["wslpath", "-u", p], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip(): return r.stdout.strip()
    return "/mnt/" + p[0].lower() + p[2:].replace("\\", "/")
def fio_path(p):                     # path as fio wants it: Windows needs backslashes and the drive colon escaped (colon is fio's filename separator)
    if not WIN: return p
    p = p.replace("/", "\\"); return p.replace(":", "\\:", 1)
def wdirname(p): return re.sub(r"[\\/][^\\/]*$", "", p) if WIN else os.path.dirname(os.path.abspath(p))
U = to_unix(A.target)                # unix view of the target (for existence/size/free-space checks)

def safety():
    t = A.target
    if not WIN and os.path.exists(t) and stat.S_ISBLK(os.stat(t).st_mode):
        if not A.allow_raw: die(f"{t} is a block device. Use a file target, or pass --allow-raw (DESTROYS data on it).")
        mp = subprocess.run(["lsblk", "-nro", "NAME,MOUNTPOINTS", t], capture_output=True, text=True).stdout
        if any(len(l.split()) > 1 for l in mp.splitlines()): die(f"{t} (or a partition) is mounted:\n{mp}")
        if input(f"This will OVERWRITE {t}. Type the device path to confirm: ").strip() != t: die("not confirmed")
        return
    if re.search(r"(?i)physicaldrive|\\\\\.\\", t): die("raw Windows devices are not supported by this driver (too dangerous); use a file on a volume")
    if not t.endswith(".fio-testfile"): die("file target must end with .fio-testfile (prevents pointing fio at a real file)")
    d = os.path.dirname(U)
    if not os.path.isdir(d): die(f"directory {d} does not exist. Create it first (Windows: mkdir C:\\ssdtest)")
    if not WIN:
        fs = subprocess.run(["df", "--output=fstype", d], capture_output=True, text=True).stdout.split()[-1]
        if fs in ("tmpfs", "ramfs", "overlay"): die(f"{d} is on {fs}: not a real SSD filesystem")
        print(f"target file OK: {t} on {fs}")
    else:
        print(f"Windows target OK: {t}  (unix view {U})")
        if t.upper().startswith("C:"): print("NOTE: C: is normally the system drive: OS and background activity share the SSD and the result is not a quiet-device measurement. Say so in the report.")
        r = subprocess.run([FIO, "--version"], capture_output=True, text=True) if (shutil.which(FIO) or os.path.exists(FIO)) else None
        if r is None or r.returncode != 0: die(f"cannot run '{FIO}'. Install fio for Windows (https://bsdio.com/fio/) and pass --fio '/mnt/c/Program Files/fio/fio.exe' if it is not on PATH")
        print("fio:", r.stdout.strip())
    free = shutil.disk_usage(d).free; need = int((SIZE + STATE_SIZE) * 1.1)
    if free < need: die(f"need about {need >> 30} GiB free in {d}, have {free >> 30} GiB (reduce --size/--state-size)")
    if free < 0.2 * shutil.disk_usage(d).total: print(f"WARNING: only {100 * free / shutil.disk_usage(d).total:.0f}% of the volume is free; steady-state results depend on free space. Report it.")

PS_TEMP = ("$d = Get-PhysicalDisk | Where-Object { $_.FriendlyName -like '*SN740*' -or $_.Model -like '*SN740*' } | Select-Object -First 1; "
           "if(-not $d){ $d = Get-PhysicalDisk | Select-Object -First 1 }; ($d | Get-StorageReliabilityCounter).Temperature")
_temp_ok = [not A.no_temp]
def temp_c():
    if not _temp_ok[0]: return float("nan")
    try:
        if WIN:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", PS_TEMP], capture_output=True, text=True, timeout=20)
            v = re.findall(r"\d+", r.stdout)
            if not v: _temp_ok[0] = False; print("NOTE: SSD temperature not readable from PowerShell (may need an Administrator terminal); temperature disabled. Record it manually (CrystalDiskInfo/HWiNFO).")
            return float(v[0]) if v else float("nan")
        for p in glob.glob("/sys/class/nvme/*/hwmon*/temp1_input"): return int(open(p).read()) / 1000
    except Exception: _temp_ok[0] = False
    return float("nan")

def fio_cmd(name, rw, bs, qd, jobs=1, mix=None, runtime=None, ramp=None, engine=None, direct=1, size=None, target=None, extra=(), local=False):
    win = WIN and not local
    tgt = target or (A.target if not local else A.wsl_target)
    c = [A.fio or ("fio.exe" if win else "fio"), f"--name={name}", f"--filename={fio_path(tgt) if win else tgt}", f"--direct={direct}", f"--ioengine={engine or ('libaio' if local else ENGINE)}",
         f"--rw={rw}", f"--bs={bs}", f"--iodepth={qd}", f"--numjobs={jobs}", "--group_reporting", f"--size={size or A.size}", "--randrepeat=0", "--norandommap",
         "--refill_buffers", "--buffer_compress_percentage=0", "--allow_file_create=1", "--output-format=json", "--percentile_list=" + ":".join(map(str, PCT)), "--clat_percentiles=1"]
    if win: c.append("--thread")
    if runtime != 0: c += ["--time_based", f"--runtime={runtime or A.runtime}", f"--ramp_time={A.ramp if ramp is None else ramp}"]
    if mix is not None: c += [f"--rwmixread={mix}"]
    if A.fio and local: c[0] = "fio"
    return c + list(extra)

def parse(j):
    job = j["jobs"][0]; row = {}; tot_ios = 0; lat_w = 0
    for d in ("read", "write"):
        r = job[d]; ios = r["total_ios"]; row[f"{d}_iops"] = r["iops"]; row[f"{d}_bw_MiBs"] = r["bw"] / 1024.0
        cl = r.get("clat_ns", {}); row[f"{d}_clat_mean_us"] = cl.get("mean", float("nan")) / 1e3; row[f"{d}_clat_std_us"] = cl.get("stddev", float("nan")) / 1e3
        lm = r.get("lat_ns", {}).get("mean", cl.get("mean", float("nan"))); row[f"{d}_lat_mean_us"] = lm / 1e3
        pm = {round(float(k), 3): v for k, v in cl.get("percentile", {}).items()}
        for p in PCT: row[f"{d}_p{p}_us"] = pm.get(float(p), float("nan")) / 1e3
        if ios: tot_ios += ios; lat_w += ios * lm / 1e3
    row["iops"] = row["read_iops"] + row["write_iops"]; row["bw_MiBs"] = row["read_bw_MiBs"] + row["write_bw_MiBs"]; row["lat_mean_us"] = lat_w / tot_ios if tot_ios else float("nan")
    return row

def run(exp, name, rw, bs, qd, jobs=1, mix=None, rep=0, **kw):
    cmd = fio_cmd(f"{exp}-{name}", rw, bs, qd, jobs, mix, **kw)
    if A.dry_run: print(" ".join(cmd)); return dict(exp=exp, name=name, rw=rw, bs=bs, qd=qd, numjobs=jobs, rwmix=mix if mix is not None else -1, rep=rep)
    t0 = temp_c(); p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0: sys.exit(f"fio failed: {' '.join(cmd)}\n{p.stderr}\n{p.stdout[:500]}")
    js = p.stdout[p.stdout.index("{"):]; open(f"{RAW}/json/{exp}-{name}-r{rep}.json", "w").write(js)
    row = dict(exp=exp, name=name, rw=rw, bs=bs, qd=qd, numjobs=jobs, rwmix=mix if mix is not None else -1, rep=rep, engine=kw.get("engine") or ENGINE, direct=kw.get("direct", 1), temp_before_c=t0, temp_after_c=temp_c())
    row.update(parse(json.loads(js))); print(f"  {exp} {name} rep{rep}: {row['iops']:.0f} IOPS {row['bw_MiBs']:.0f} MiB/s lat {row['lat_mean_us']:.0f} us  T={row['temp_after_c']}C", flush=True); return row
def save(name, rows):
    if A.dry_run: return
    pd.DataFrame(rows).to_csv(f"{RAW}/{name}.csv", index=False); print("wrote", name, len(rows))
def reps(exp, name, rw, bs, qd, **kw): return [run(exp, name, rw, bs, qd, rep=r, **kw) for r in range(A.repeats)]

def prefill():   # real writes everywhere: reading never-written space can return zeros without touching the NAND
    print("prefill: sequential write of the whole test range"); run("prep", "seqfill", "write", "1M", 32, runtime=0, rep=0, extra=["--end_fsync=1"])
def precondition():
    for i in range(A.precond_passes):
        print(f"precondition: random 4K write pass {i + 1}/{A.precond_passes}"); run("prep", f"randfill{i}", "randwrite", "4k", 32, runtime=0, rep=0, extra=[f"--io_size={A.size}", "--end_fsync=1"])

def zero_queue():
    rows = []
    for name, rw, bs in (("rr4k", "randread", "4k"), ("rw4k", "randwrite", "4k"), ("sr128k", "read", "128k"), ("sw128k", "write", "128k")): rows += reps("zero_queue", name, rw, bs, 1, runtime=A.runtime * 2)
    save("zero_queue", rows)
def bs_sweep():
    rows = []
    for bs in ("4k", "16k", "32k", "64k", "128k", "256k"):
        for pat, rwr, rww in (("rand", "randread", "randwrite"), ("seq", "read", "write")):
            for qd in (1, 32):
                for d, rw in (("read", rwr), ("write", rww)): rows += reps("bs_sweep", f"{pat}-{d}-{bs}-qd{qd}", rw, bs, qd)
    for qd in (1, 32):
        for d, rw in (("read", "read"), ("write", "write")): rows += reps("bs_sweep", f"seq-{d}-1m-qd{qd}", rw, "1m", qd)
    save("bs_sweep", rows)
def rw_mix():
    rows = []
    for mix in (100, 70, 50, 0): rows += reps("rw_mix", f"rand4k-mix{mix}", "randrw", "4k", 32, mix=mix)
    save("rw_mix", rows)
def qd_sweep():
    rows = []
    for qd in (1, 2, 4, 8, 16, 32, 64, 128, 256):
        rows += reps("qd_sweep", f"rr4k-qd{qd}", "randread", "4k", qd); rows += reps("qd_sweep", f"rw4k-qd{qd}", "randwrite", "4k", qd); rows += reps("qd_sweep", f"sr128k-qd{qd}", "read", "128k", qd)
    for j in (1, 2, 4, 8, 16): rows += reps("jobs_sweep", f"rr4k-jobs{j}", "randread", "4k", 1, jobs=j)
    save("qd_sweep", rows)
def knee_qd():
    if A.knee_qd: return A.knee_qd
    p = f"{RAW}/qd_sweep.csv"
    if not os.path.exists(p): return 32
    d = pd.read_csv(p); d = d[(d.exp == "qd_sweep") & (d.name.str.startswith("rr4k"))].groupby("qd").iops.median(); return int(d[d >= 0.9 * d.max()].index.min())
def tail():
    k = knee_qd(); mid = max(2, k // 4); print(f"tail: mid QD={mid}, knee QD={k}"); rows = []
    for qd in sorted({1, mid, k}):
        for name, rw in (("rr4k", "randread"), ("rw4k", "randwrite")): rows += reps("tail", f"{name}-qd{qd}", rw, "4k", qd, runtime=A.runtime * 3)
    save("tail", rows)

class TempLogger(threading.Thread):
    def __init__(s, path): super().__init__(daemon=True); s.path = path; s.stop = False
    def run(s):
        t0 = time.time()
        with open(s.path, "w") as f:
            f.write("t_s,temp_c\n")
            while not s.stop: f.write(f"{time.time() - t0:.0f},{temp_c()}\n"); f.flush(); time.sleep(5)
def timeseries(name, rw, bs, qd, secs, loops=1, runtime_is_cap=False):
    ldir = wdirname(A.target) + ("\\" if WIN else "/") + "logs"; os.makedirs(to_unix(ldir), exist_ok=True); prefix = ldir + ("\\" if WIN else "/") + name
    ex = [f"--write_bw_log={prefix}", f"--write_iops_log={prefix}", f"--write_lat_log={prefix}", "--log_avg_msec=1000"]
    if runtime_is_cap: cmd = fio_cmd(f"state-{name}", rw, bs, qd, runtime=0, size=A.state_size, target=A.target + ".state", extra=ex + [f"--runtime={secs}", f"--loops={loops}"])
    else: cmd = fio_cmd(f"state-{name}", rw, bs, qd, runtime=secs, ramp=0, size=A.state_size, target=A.target + ".state", extra=ex)
    if A.dry_run: print(" ".join(cmd)); return
    tl = TempLogger(f"{RAW}/logs/{name}_temp.csv"); tl.start(); p = subprocess.run(cmd, capture_output=True, text=True); tl.stop = True; time.sleep(0.1)
    if p.returncode != 0: sys.exit(p.stderr + p.stdout[:500])
    open(f"{RAW}/json/state-{name}.json", "w").write(p.stdout[p.stdout.index("{"):])
    for f in glob.glob(to_unix(prefix) + "*"): shutil.move(f, f"{RAW}/logs/{os.path.basename(f)}")
    print("  state", name, "done", flush=True)
def state():
    st = U + ".state"
    print("NOTE: for a 'fresh' state the freed space should be TRIMmed: Windows does this on file delete for SSDs; to force it run (Administrator PowerShell) Optimize-Volume -DriveLetter C -ReTrim -Verbose, then idle a few minutes.")
    if os.path.exists(st) and not A.dry_run: os.remove(st)
    timeseries("randwrite4k_fresh", "randwrite", "4k", 32, A.state_secs)
    loops = max(1, -(-A.slc_gib * 2**30 // STATE_SIZE))
    timeseries("seqwrite1m_slc", "write", "1m", 32, max(A.state_secs, 900), loops=loops, runtime_is_cap=True)   # total about slc-gib GiB, capped by time
    if not A.dry_run:
        print("preconditioning state file (full sequential write + random 4K pass)")
        for nm, rw, bs, ex in (("state-precond", "write", "1M", ["--end_fsync=1"]), ("state-precond2", "randwrite", "4k", [f"--io_size={A.state_size}", "--end_fsync=1"])):
            p = subprocess.run(fio_cmd(nm, rw, bs, 32, runtime=0, size=A.state_size, target=A.target + ".state", extra=ex), capture_output=True, text=True)
            if p.returncode != 0: sys.exit(p.stderr + p.stdout[:500])
    timeseries("randwrite4k_steady", "randwrite", "4k", 32, A.state_secs)
def make_sparse(path_fio, size_bytes):   # a file that exists but was never written: reads should return zeros without touching the NAND
    u = to_unix(path_fio)
    if os.path.exists(u): os.remove(u)
    if WIN:
        try:
            r = subprocess.run(["cmd.exe", "/c", "fsutil", "file", "createnew", path_fio, str(size_bytes)], capture_output=True, text=True)
            if r.returncode == 0 and os.path.exists(u): return True
        except FileNotFoundError: pass
        print("NOTE: fsutil createnew unavailable; falling back to truncate (NTFS may or may not leave the data unwritten: check that the 'never written' result is implausibly fast)")
    try: subprocess.run(["truncate", "-s", str(size_bytes), u], check=True); return True
    except Exception: return False
def pitfalls():
    rows = []
    small = A.target + ".small"
    sparse = A.target + ".sparse"

    if not A.dry_run:
        if os.path.exists(to_unix(small)):
            os.remove(to_unix(small))

    # Prepare a 1 GiB test file.
    run(
        "prep", "smallfill", "write", "1M", 8,
        runtime=0, size="1G", target=small,
        extra=["--end_fsync=0"]
    )

    # Buffered read to warm the system file cache.
    run(
        "prep", "cachewarm", "read", "1M", 1,
        runtime=0, size="1G", target=small,
        direct=0, engine="sync"
    )

    # Attempt to create a file that has not been written.
    have_sparse = A.dry_run or make_sparse(sparse, SIZE)

    if not have_sparse:
        print(
            "NOTE: Could not create an unwritten file; "
            "the unwritten-file pitfall is skipped."
        )

    for r in range(A.repeats):

        # Baseline: direct I/O with asynchronous Windows I/O,
        # using queue depth 32.
        rows.append(
            run(
                "pitfall", "correct_direct_async_qd32",
                "randread", "4k", 32, rep=r
            )
        )

        # Buffered synchronous reads: cache effects may make
        # reported latency much lower than actual SSD latency.
        rows.append(
            run(
                "pitfall", "buffered_sync_1GiB",
                "randread", "4k", 32, rep=r,
                engine="sync", direct=0,
                size="1G", target=small
            )
        )

        # Direct I/O control test: use windowsaio on Windows
        # because Windows does not support direct=1 with sync.
        rows.append(
            run(
                "pitfall", "direct_windowsaio_1GiB_same_file_control",
                "randread", "4k", 1, rep=r,
                engine="windowsaio", direct=1,
                size="1G", target=small
            )
        )

        # Buffered asynchronous reads at queue depth 32.
        rows.append(
            run(
                "pitfall", "buffered_async_qd32_1GiB",
                "randread", "4k", 32, rep=r,
                direct=0, size="1G", target=small
            )
        )

        # Synchronous I/O with requested queue depth 32.
        # The sync engine does not provide true asynchronous
        # queue-depth behavior; direct=0 avoids the Windows error.
        rows.append(
            run(
                "pitfall", "buffered_sync_iodepth32_ignored",
                "randread", "4k", 32, rep=r,
                engine="sync", direct=0
            )
        )

        # Read from a file that may never have been written.
        if have_sparse:
            rows.append(
                run(
                    "pitfall", "read_never_written_file",
                    "randread", "4k", 32, rep=r,
                    target=sparse
                )
            )

        if A.wsl_target:
            rows.append(
                run(
                    "pitfall", "wsl2_virtual_disk_direct_qd32",
                    "randread", "4k", 32, rep=r,
                    local=True, target=A.wsl_target,
                    engine="libaio"
                )
            )

    save("pitfalls", rows)

    # Remove temporary test files.
    if not A.dry_run:
        for f in (small, sparse):
            if os.path.exists(to_unix(f)):
                os.remove(to_unix(f))

if __name__ == "__main__":
    safety()
    EXPS = dict(zero_queue=zero_queue, bs_sweep=bs_sweep, rw_mix=rw_mix, qd_sweep=qd_sweep, tail=tail, state=state, pitfalls=pitfalls)
    sel = A.only.split(",") if A.only else list(EXPS)
    if not A.dry_run and any(s in sel for s in ("zero_queue", "bs_sweep", "rw_mix", "qd_sweep", "tail")): prefill(); precondition()
    for n in sel: print("==", n, flush=True); EXPS[n]()
    print("done")
