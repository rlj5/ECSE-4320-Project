# ECSE 4320/6320 Project 3: SSD Performance Profiling

This project measures a WD PC SN740 512 GB NVMe SSD with Windows fio 3.43 (`windowsaio`, direct I/O) against a disposable 4 GiB file on NTFS. fio ran from WSL2 through Windows interop. The results describe the Windows storage stack and filesystem on the SSD, not raw-device performance. The host was an AMD Ryzen 7 5825U laptop running Windows 11 Version 26H2, Build 26300.9711; its two 8 GiB SO-DIMMs reported 3200 MT/s on channels A and B. DDR4 is inferred from the SO-DIMM form factor; memory type is DDR4.

## Results

The completed analysis is in [REPORT.md](REPORT.md), with pre-experiment predictions in [HYPOTHESES.md](HYPOTHESES.md). The QD1 baseline was 9.4k 4 KiB random-read IOPS; the 4 KiB random-read sweep reached 123k IOPS at QD32. The measured 128 KiB sequential-read ceiling was 1,491 MiB/s at QD32. The estimated read knee was QD32 by Kneedle and QD10 using the simple `Xmax × QD1 latency` estimate.

The drive had only about 7% free space during the run. Results are specific to a nearly full system volume with OS and background I/O sharing the SSD. CrystalDiskInfo reports the SN740 link as **PCIe 3.0 x4 current | PCIe 4.0 x4 supported**. The separate `Get-NetAdapterHardwareInfo` output is for Wi-Fi (5.0 GT/s x1), not the SSD. No WSL2 virtual-disk comparison was run.

## Experiment design

| Experiment | Workload |
|---|---|
| QD1 baseline | 4 KiB random read/write and 128 KiB sequential read/write; p50 through p99.9 |
| Block size and pattern | Random and sequential read/write, 4-256 KiB, QD1 and QD32; additional 1 MiB sequential points |
| Read/write mix | 4 KiB random mix at QD32: 100%, 70%, 50%, and 0% reads |
| Queue depth and parallelism | 4 KiB random read/write and 128 KiB sequential read, QD1-256; 4 KiB read with 1-16 jobs |
| Tail latency | 4 KiB random read/write at QD1, QD8, and QD32 |
| Device state | Fresh and preconditioned random writes; 1 MiB sequential writes, with temperature and throughput logging |
| Misleading setups | Buffered/direct comparisons, synchronous engine with requested depth 32, and reading a never-written file |

## Repository contents

| Path | Description |
|---|---|
| `run_fio.py` | FIO workload driver, safety checks, and generated per-run FIO JSON |
| `plot_fio.py` | Aggregation, knee calculation, tables, and figures |
| `run_all.sh` | Environment capture, experiment driver, and plotting entry point |
| `HYPOTHESES.md` | Predictions recorded before the measurements |
| `REPORT.md` | Methodology, results, analysis, limitations, and evidence index |
| `data/raw/*.csv` | Raw per-run metrics |
| `data/raw/json/` | Per-run fio JSON with effective workload options and full result records |
| `data/raw/logs/` | Throughput, IOPS, latency, and temperature time series for device-state runs |
| `data/processed/` | Aggregated tables used by the report |
| `plots/` | Figures referenced by the report |
| `env/ssd_info.txt` | SSD, filesystem, temperature, power-plan, and fio environment capture |
| `ssdtest/` | Retained copies of the 4 GiB primary target and 4 GiB state target; these are fio workload files, not result data (both match `.gitignore`) |

## Reproducing the run

The recorded full run was launched from WSL2 with Windows fio 3.43 using:

```bash
./run_all.sh 'C:\ssdtest\bench.fio-testfile' --fio "$FIO" 2>&1 | tee run.log
```

`FIO` must be set to the Windows fio executable path available through WSL2. `run_all.sh` runs `ssd_info.sh`, invokes `run_fio.py` for the experiment suite, then runs `plot_fio.py`; `tee` captures both standard output and errors in `run.log`. The current driver defaults now match the recorded run: 4 GiB main target, 4 GiB state target, three repetitions, 20 s runtime, 3 s ramp, 600 s device-state traces, and 200 GiB total sequential state writes. QD1 baselines used 40 s and tail tests 60 s. Per-run JSON under `data/raw/json/` records effective fio options. `run_fio.py --help` lists overrides; the driver requires a disposable filename ending in `.fio-testfile` and refuses raw Windows devices.

The original run started with about 35.1 GB free on C:. Repeating the full suite issues substantial writes, including the 200 GiB sequential state test. Check free space and account for C: being the system volume. Before testing, important files were copied to a separate folder on the Desktop as a backup precaution. The benchmark used disposable files and did not target a raw device or partition. The primary target and state target persist after the run unless removed manually. Copies of both 4 GiB files are now in `ssdtest/`; these are workload artifacts, not measurement results, and add 8 GiB to a manual archive. `.gitignore` excludes them from Git, but a manually created archive will include them unless they are omitted.

## Interpretation limits

The SSD was tested through Windows and NTFS on the C: system volume, not as a raw block device. Both the captured `powercfg` scheme and confirmed Windows Settings report Balanced; Energy Saver was off. AC power was connected and Defender real-time protection was on (operator-confirmed, not script-captured). CrystalDiskInfo reports a current Gen3 x4 link and supported Gen4 x4 mode for the SSD. The workload did not establish an SLC cliff or isolate thermal throttling. The optional WSL2 virtual-disk comparison was not run. See [REPORT.md](REPORT.md) for full limitations and evidence.
