# Project 3: SSD Performance Profiling of a WD PC SN740 512 GB

ECSE 4320/6320 Advanced Computer Systems. Host: AMD Ryzen 7 5825U laptop, Windows 11/WSL2. Device: PC SN740 NVMe WD 512GB, firmware 73914107. fio 3.43. Companion files: [HYPOTHESES.md](HYPOTHESES.md).
## Summary

At QD1, 4 KiB random reads measured 9,430 IOPS with 105 us mean and 140 us p99 latency; random writes measured 17,828 IOPS with 55 us mean and 62 us p99. The separate QD32 block-size sweep measured 123,361 4 KiB random-read IOPS and 1,491 MiB/s for 128 KiB sequential reads. The queue-depth sweep's maxima were lower (101,568 IOPS and 1,113 MiB/s, respectively), so the two suites are reported separately rather than treated as one reproducible maximum. In the queue-depth sweep, Kneedle placed the random-read knee at QD32, while Xmax times QD1 latency predicted QD10. Read p99.9 rose from 151 us at QD1 to 489 us at QD32; write tails were far more severe at higher depths. Sequential-write throughput varied around 500-650 MiB/s in the sampled long run, but did not establish a cache cliff or post-SLC rate. Reading a never-written file returned 2.09x the direct-I/O QD32 IOPS; buffered synchronous I/O reached 17.7x its matched same-file direct synchronous control. These are file-on-NTFS results from a nearly full system volume. Windows power mode was Balanced, Energy Saver was off, AC power was connected, and Defender real-time protection was on. CrystalDiskInfo reported PCIe 3.0 x4 current and PCIe 4.0 x4 supported for the SSD; the supplied PowerShell PCIe result is for Wi-Fi.

## 1. Introduction

An SSD behaves like a queueing system: throughput rises with outstanding requests until saturation, while latency increases as work queues. This study varies block size, access pattern, read/write mix, queue depth, and device state. Little's Law relates in-flight work to throughput and latency; here its Xmax times unloaded-latency knee estimate is compared with the measured curve.

## 2. Platform, safety, and method

| Item | Captured setting |
|---|---|
| SSD | PC SN740 NVMe WD 512GB; firmware 73914107; health Healthy; 44 C in environment snapshot |
| Host | AMD Ryzen 7 5825U laptop; Windows 11 Version 26H2, Build 26300.9711 (operator-reported); WSL2 kernel 6.6.87.2. The environment file's `10.0.26100` value is the BitLocker utility version, not the Windows build. |
| Host memory | 16 GiB total: two 8 GiB modules, each reported at 3200 MT/s in `P0 CHANNEL A` and `P0 CHANNEL B`; FormFactor 12 (SO-DIMM). WMI MemoryType is 0 (unknown); DDR4-3200 is inferred from the SO-DIMM form factor and platform. The configured memory clock was not captured. |
| fio | fio 3.43 Windows binary, launched through WSL2 interop; `windowsaio`; direct I/O |
| Target | `C:\ssdtest\bench.fio-testfile`, a 4 GiB file on NTFS on C:, the system volume; a separate 4 GiB `.state` target was used for device-state runs |
| Retained target copies | `ssdtest/bench.fio-testfile` and `ssdtest/bench.fio-testfile.state` are each 4 GiB workload artifacts copied into this project folder after the measurements; they are not fio result files |
| Volume space | About 35.1 GB free of 490.9 GB (about 7%) in captured environment; run log warns only 7% free |
| Data pattern | Incompressible buffers; `--refill_buffers`, 0% buffer compression, random maps disabled, random repeat disabled |
| Workload range and timing | 4 GiB test file for the main sweeps; three repetitions per configuration; ordinary jobs ran 20 s after a 3 s ramp, QD1 baselines 40 s, and tail tests 60 s. FIO JSON captures the effective options. |
| Device-state workloads | 4 GiB state file; fresh and steady random-write traces ran 600 s each. Sequential write overwrote the 4 GiB file for 50 loops (200 GiB total) and completed in about 409 s. |
| Preconditioning | One sequential fill and one random 4 KiB write pass, per run log |
| Temperature | PowerShell/Storage Reliability Counter values recorded during experiments; environment snapshot reported 44 C, experiment values reached roughly 82 C |
| BitLocker/TRIM | C: fully decrypted; NTFS TRIM enabled (`DisableDeleteNotify=0`) |
| Power/security | The environment capture and operator-confirmed Windows Settings both report **Balanced** power mode; **Energy Saver was off**. AC power was connected and Defender real-time protection was on (operator-confirmed; not captured by the environment script). The script's Defender query failed. |
| PCIe link | CrystalDiskInfo Transfer Mode: **PCIe 3.0 x4 current | PCIe 4.0 x4 supported** for the SN740. The separately supplied `Get-NetAdapterHardwareInfo` result identifies the Wi-Fi adapter at 5.0 GT/s x1 and is not the SSD's link. |

The benchmark used files on NTFS through the Windows storage stack, not raw block access. C: is the system volume, so operating-system and background I/O shared the SSD. The run log notes low free space, which affects steady-state and dynamic SLC behavior. The primary target and state target persist after the run; 4 GiB copies of each are now retained under `ssdtest/`. Before testing, important files were copied to a separate folder on the Desktop as a backup precaution (operator-confirmed; the exact folder name was not provided). The benchmark itself was confined to disposable files and did not write to a raw device or partition.

The suite covered QD1 baselines; random/sequential block sizes at QD1 and QD32; 4 KiB random read/write mixes at QD32; queue-depth sweeps from QD1 to QD256 and jobs from one to sixteen; latency tails at QD1/QD8/QD32; three device-state workloads; and selected misleading setups. Random workloads select from the 4 GiB file range; sequential workloads traverse that range. Tables report medians across repetitions; `std` columns represent sample standard deviation. Latency percentiles come from fio completion-latency histograms.

## 3. Hypotheses

The predictions were recorded in [HYPOTHESES.md](HYPOTHESES.md). Selected expectations included 70-130 us mean 4 KiB QD1 read latency, 0.9-1.5 GB/s QD1 128 KiB reads, QD16-64 for the random-read knee, and a 5-50x buffered-read inflation. Outcomes are summarized in section 6.

## 4. Results

### 4.1 QD1 baselines

| Workload | IOPS | MiB/s | Mean us | p50 us | p95 us | p99 us | p99.9 us |
|---|---:|---:|---:|---:|---:|---:|---:|
| 4 KiB random read | 9,430 | 36.8 | 105.0 | 91.6 | 125.4 | 140.3 | 228.4 |
| 4 KiB random write | 17,828 | 69.6 | 54.9 | 21.9 | 40.2 | 62.2 | 399.4 |
| 128 KiB sequential read | 2,724 | 340.5 | 365.5 | 333.8 | 428.0 | 493.6 | 725.0 |
| 128 KiB sequential write | 5,414 | 676.8 | 178.8 | 97.8 | 378.9 | 913.4 | 2,342.9 |

The 128 KiB QD1 transfer rates are limited by having only one request in flight and the measured file/storage path. They are not evidence of a PCIe ceiling. QD1 throughput times mean completion latency is approximately one outstanding operation for all four rows (0.97-1.00), as expected for these closed-loop QD1 jobs. This checks internal consistency between the reported throughput and latency, but does not independently verify the SSD or Windows counters. Read mean and p99 and write mean/p99 fall within the hypothesis ranges; write p99.9 nevertheless exposes a long tail hidden by the averages.

### 4.2 Block size and access pattern

At QD32, 4 KiB random reads reached 482 MiB/s, rising to 1,388 MiB/s at 64 KiB and 1,491 MiB/s at 128 KiB. For random reads, throughput increases about 2.9x from 4 KiB to 16 KiB, then largely plateaus: 16-256 KiB results cluster around 1.3-1.5 GiB/s. This is consistent with fixed per-request overhead dominating small transfers and a shared path limit dominating larger ones; it does not identify which layer imposes that limit. The 128 KiB sequential-read result is about 1.46 GiB/s, with no gain at larger blocks. Latency rises alongside request size: QD32 random-read mean latency moves from about 211 us at 4 KiB to 2.87 ms at 128 KiB, while throughput changes only slightly after 16 KiB. Thus the larger transfer size increases bytes per request, but does not improve the saturated byte rate proportionally. Writes are irregular across repeats and block sizes; e.g., 4 KiB random write had roughly 62% IOPS coefficient of variation, so fine-grained comparisons should not be overinterpreted. See [block-size figure](plots/bs_sweep.png) and `data/processed/bs_sweep_agg.csv`. The confirmed Gen3 x4 link is consistent with a lower interface ceiling than Gen4, but the measured sequential rate is well below the Gen3 x4 theoretical ceiling; this benchmark cannot attribute the gap to one cause.

### 4.3 Read/write mix

| Read mix | Total IOPS | Read mean us | Write mean us |
|---:|---:|---:|---:|
| 100% | 104,873 | 246.8 | - |
| 70% | 88,754 | 298.0 | 159.3 |
| 50% | 52,709 | 767.2 | 207.9 |
| 0% | 13,585 | - | 2,150.0 |

Compared with read-only, the 70% read mix reduced total IOPS by about 15%, and the 50% mix reduced it by about 50%. The all-write point was about 13% of read-only IOPS. Read p99 grew from 510 us at 100% reads to 1.27 ms at 70% and 3.72 ms at 50%; at 0% reads, write p99 was about 100 ms. This supports the prediction that write service and shared device resources lower mixed-workload performance. See [read/write mix figure](plots/rw_mix.png).

### 4.4 Queue depth, knee, and Little's Law

| Test | Xmax | QD1 mean us | Predicted knee Xmax x L1 | Kneedle QD | QD at 90% Xmax |
|---|---:|---:|---:|---:|---:|
| 4 KiB random read | 101,568 IOPS | 100.8 | 10.2 | 32 | 32 |
| 4 KiB random write | 22,194 IOPS | 78.3 | 1.7 | 4 | 64 |
| 128 KiB sequential read | 1,113 MiB/s | 336.9 | 3.0 | 4 | 16 |

The 4 KiB random-read Kneedle point is QD32, approximately three times the QD10 Little's Law estimate; QD32 is also the first sampled point reaching 90% of the queue sweep's maximum. The sequential-read Kneedle point is QD4, near its QD3 prediction, while its 90% threshold occurs at QD16. The random-write curve is non-monotonic and variable; its 90% threshold at QD64 is later than its Kneedle point and should not be treated as a stable knee. These are operational estimates, not intrinsic device constants: Kneedle depends on the sampled points and curve shape, while Xmax depends on the observed maximum and unloaded latency. Also, the queue sweep and block-size sweep do not produce the same maxima (101.6k versus 123.4k random-read IOPS; 1,113 versus 1,491 MiB/s sequential-read), which indicates session/workload sensitivity and cautions against quoting one maximum without its test context. Increasing `numjobs` from 1 to 16 raised 4 KiB read throughput from roughly 8.5k to 100k IOPS while mean latency rose from about 116 to 158 us, indicating substantial benefit from host-side concurrency. In a closed-loop workload, IOPS times mean latency approximates in-flight work by construction, so that identity is a consistency check rather than independent validation. See [queue-depth figure](plots/qd_sweep_knee.png) and [jobs figure](plots/jobs_sweep.png).

### 4.5 Tail latency

| Workload | p50 us | p95 us | p99 us | p99.9 us | p99.99 us |
|---|---:|---:|---:|---:|---:|
| 4 KiB read QD1 | 93.7 | 103.9 | 117.2 | 150.5 | 362.5 |
| 4 KiB read QD8 | 106.0 | 181.2 | 226.3 | 305.2 | 1,597 |
| 4 KiB read QD32 | 195.6 | 309.2 | 387.1 | 489.5 | 626.7 |
| 4 KiB write QD1 | 21.9 | 33.5 | 48.4 | 675.8 | 51,118 |
| 4 KiB write QD8 | 66.0 | 158.7 | 1,384 | 63,701 | 179,306 |
| 4 KiB write QD32 | 276.5 | 1,204 | 66,847 | 109,576 | 227,541 |

Read p99.9 grew about 3.3x from QD1 to QD32. The p99-to-median ratio rose from 1.25x at QD1 to about 2.0x at QD32, showing a broader latency distribution under load. Read p99.99 peaked at QD8 and then fell at QD32, so the most extreme read percentile is not monotonic and is sensitive to rare samples. Write tails are much more severe: p99/p50 grows from 2.2x at QD1 to about 242x at QD32, and QD32 write p99.9 is about 110 ms. This makes a mean-only comparison particularly misleading for writes. The pattern is consistent with intermittent write stalls plus queued work, although the data do not isolate garbage collection, cache folding, thermal control, or background activity as the cause. Percentiles this far into the tail also depend on sample count and repeat variability. See [tail-latency figure](plots/tail_latency.png) and `data/processed/tail_table.csv`.

### 4.6 Device state, SLC, and temperature

The fresh random-write run began around 70-74 C and showed brief high-throughput bursts followed by a noisy baseline mostly around 50-150 MiB/s. The steady-state random-write trace was similarly bursty, with a long-run baseline around 40-60 MiB/s and temperatures declining from about 72 C to 66 C. The sequential-write trace covered 200 GiB in about 409 s: throughput rose from roughly 70 MiB/s to short peaks near 700 MiB/s, then varied mostly around 500-650 MiB/s while temperature approached 82 C. No clear sustained SLC cliff or post-cache rate was established. Although 200 GiB was written, the trace cannot identify cache capacity or a post-cache rate on a drive with only about 7% free space, nor does it isolate thermal throttling. Windows TRIM was enabled, but the log only recommends `Optimize-Volume -ReTrim`; it does not confirm that it was run before the fresh test. See [device-state figure](plots/device_state_timeseries.png).

### 4.7 Misleading setups

| Setup | IOPS | Ratio to direct async QD32 | Interpretation |
|---|---:|---:|---|
| Correct direct async QD32 | 125,775 | 1.00x | Reference |
| Buffered async QD32, 1 GiB | 121,379 | 0.97x | Similar to the direct reference in this sample |
| Buffered sync, 1 GiB | 177,829 | 1.41x | About 17.7x the same-file direct sync control, showing the cache effect |
| Direct windowsaio same-file sync control | 10,040 | 0.08x | Unbuffered control for the buffered-read comparison |
| Sync engine with iodepth 32 | 9,725 | 0.077x | About QD1-like; requested depth did not provide async concurrency |
| Read never-written file | 262,929 | 2.09x | Reads may be served as zero/sparse data and do not represent written flash |
| WSL2 virtual-disk test | not present | - | P4 was not run; no result claimed |

Buffered asynchronous QD32 was not faster than the direct QD32 reference here. The buffered synchronous comparison demonstrates a cache effect only when compared with the matched same-file direct synchronous control. The never-written file produced roughly twice the reference IOPS and is not a valid SSD read baseline. See [pitfalls figure](plots/pitfalls.png) and `data/processed/pitfalls_agg.csv`.

## 5. Analysis and interpretation

### 5.1 What the measurements establish

The tested file path can deliver low-latency QD1 random reads, substantial gains from added concurrency, and roughly 1.3-1.5 GiB/s read throughput for large requests in the block-size sweep. The queue-depth data place the random-read saturation region around QD32, while the sequential-read curve reaches its bend earlier. Mixed writes reduce the read-heavy throughput and broaden latency, and queued random writes have a particularly severe tail. These are observations about this drive, host, Windows file path, volume state, and measurement session; they should not be generalized as the SN740's raw-device specification.

The QD1 throughput-latency products are close to one request, and requested synchronous depth 32 behaves near the single-request control. Together with the per-run fio JSON options and the matched buffered/direct controls, these checks support that the intended queueing and I/O-mode contrasts were captured. They are consistency checks rather than an independent correctness benchmark: the submission has no second tool or known-good device result against which to validate absolute performance.

### 5.2 Why results change with workload

Small random requests pay a larger per-operation cost; increasing request size increases bytes transferred per operation and brings random-read bandwidth close to the sequential result. Past roughly 16 KiB, the additional block size yields little random-read bandwidth improvement, while per-request completion latency grows into milliseconds at QD32. That is the expected trade-off when a workload is already near a shared throughput ceiling: larger requests do not remove the bottleneck, and more outstanding work increases time spent waiting.

Read-only traffic performs better than mixed traffic in these measurements. As writes enter the mix, read throughput falls and read p99 rises; with 50% reads, total IOPS is about half the read-only result and read p99 is about 7.3x the read-only p99. The all-write case is lower still and has an approximately 100 ms p99. This is evidence of interference between request classes on the tested path, but it does not identify whether the mechanism is flash-media service, controller scheduling, cache management, Windows background I/O, or their combination.

### 5.3 Queueing interpretation and cross-sweep variation

The Xmax-times-QD1-latency estimate is a useful first approximation for the amount of concurrency needed to reach throughput saturation. For random reads it predicts QD10, while the measured curve's Kneedle and 90%-of-maximum criteria both select QD32. The gap means the simple estimate underpredicts the observed transition for this workload. For sequential reads the QD3 prediction and QD4 Kneedle agree more closely, though the 90% point is QD16. Reporting the method matters: a single value called “the knee” would conceal threshold choice and curve sensitivity.

The block-size and queue-depth sweeps also disagree on their maxima: 123,361 versus 101,568 random-read IOPS and 1,491 versus 1,113 MiB/s sequential reads. Both used QD32, but they were separate runs/configurations and the device/system state was not held constant across sessions. This spread is material (about 21% and 25%, respectively). It means claims should use the result from the specific figure/table and avoid treating a peak from one sweep as a stable drive limit. Repeated trials within a sweep reduce short-run noise but do not eliminate between-run changes in free space, temperature, background I/O, or SSD internal state.

### 5.4 Tail behavior and practical meaning

Average latency alone would understate the cost of queued writes. At QD32, the write median is about 276 us, but p99 is about 66.8 ms and p99.9 about 109.6 ms. This wide separation means most operations can complete quickly while a small fraction take orders of magnitude longer. Read tails increase more gradually, and the non-monotonic p99.99 values warn that the rarest quantiles are less stable than central percentiles. For latency-sensitive use, the measured write-tail behavior is more informative than the peak IOPS number.

### 5.5 Device state, thermal interpretation, and limits

The device-state traces demonstrate variability, but they do not identify a stable SLC-cache boundary or thermal throttle point. The sequential write trace averages about 500 MiB/s across 200 GiB with short bursts near 700 MiB/s; because the drive began with only about 7% free space and the trace did not show a clear persistent transition, neither the cache capacity nor a post-cache speed can be extracted. Temperature approaching 82 C is a correlation with the workload, not evidence that throttling caused the throughput pattern. A controlled thermal test would require repeatable starting temperature and workload, temperature/frequency or throttling telemetry, and a matched cooler-condition run. A cache estimate would require a reproducible rate transition over a sufficiently long, known-free-space target and repeat runs after a documented reset/preconditioning procedure. These are follow-up methods, not claims made from the current data.

The SSD reports Gen3 x4 active link while supporting Gen4 x4. This rules out treating Gen4 bandwidth as available to the benchmark, but Gen3 x4's theoretical interface bandwidth is still above the measured file-read ceiling. The measurements do not separate PCIe transfer limits from controller/flash behavior, host processing, NTFS and Windows storage-stack overhead, system-volume contention, or SSD state. The observed gap from vendor sequential ratings therefore cannot be assigned to one cause with this experiment.

### 5.6 Misleading configurations

The never-written-file result is the clearest invalid baseline as it reads 2.09x the direct-I/O QD32 reference, consistent with zero/sparse-file handling bypassing ordinary flash reads. The synchronous-engine result is also a useful configuration check: requesting depth 32 does not create 32 simultaneous requests with a synchronous engine, and the measured rate stays near the QD1 scale. Buffered synchronous I/O exceeded its same-file direct synchronous control by 17.7x, demonstrating the effect of the Windows file cache for that paired comparison. Buffered asynchronous QD32, however, was similar to direct asynchronous QD32 in this sample; the data do not support a general claim that buffered asynchronous I/O inflated throughput. The separate WSL2 virtual-disk comparison was not run and is not used to support any conclusion.

### 5.7 Validation and evidence limits

The run log documents the 4 GiB target, preconditioning, and repetition procedure; fio JSON preserves effective options. The QD1 Little's Law products (about 0.97-1.00 requests) and pitfall controls provide internal checks. No independent reference benchmark, per-run target-byte counter, or separate raw-device measurement is present. Therefore this report validates configuration consistency and interprets the observed file-I/O data, but does not claim independent validation of the absolute device performance or exact physical NAND traffic.

## 6. Expectations against outcomes

| Topic | Expected | Observed | Verdict |
|---|---|---|---|
| 4 KiB QD1 read mean/p99 | 70-130 / 90-250 us | 105 / 140 us | Within range |
| 4 KiB QD1 write mean | 20-60 us | 55 us | Within range |
| 128 KiB QD1 read/write | 0.9-1.5 / 1.0-2.0 GB/s | 341 / 677 MiB/s | Below range |
| Sequential-read ceiling | 3.0-3.5 GB/s if Gen3 | 1,491 MiB/s at QD32 | Below prediction despite confirmed Gen3 x4; host, file-system, workload, and device-state limits remain possible |
| 4 KiB QD32 random read | 150k-400k IOPS | 123k IOPS | Below range |
| Mixed IOPS loss vs read-only | 20-50% lower | 15% at 70% reads; 50% at 50% reads | Partial; mix-dependent |
| Random-read knee / prediction | QD16-64 / QD20-40 | QD32 / QD10 | Observed in range; prediction lower |
| 128 KiB sequential knee | QD2-8 | QD4 Kneedle; QD16 at 90% max | Kneedle in range |
| p99.9 / mean near knee | 5-15x | Read QD32 about 2.3x; write QD32 about 66x | Read below; write far above |
| Random-write burst-to-steady drop | 30-60% | Bursty trace, no robust single ratio | Not quantified |
| Sequential write after SLC cliff | 1.0-1.6 GB/s | No clear cliff; observed mostly 500-650 MiB/s | Not established |
| Buffered vs direct (P1) | 5-50x | 17.7x matched sync control | Within range |
| Sync engine at requested QD32 (P2) | Behaves like QD1 | 9.7k vs 125.8k async QD32 | Consistent |
| Never-written read (P3) | 10-100x | 2.09x | Direction consistent, smaller effect |
| WSL2 virtual disk (P4) | At least 20% difference | Not run | Not tested |

## 7. Limitations

This measures a file on NTFS on the C: system volume through Windows, not raw SSD access. Only about 7% of the volume was free, and background OS activity shared the device. CrystalDiskInfo reports the SN740's current PCIe link as Gen3 x4 and supported mode as Gen4 x4; the provided `Get-NetAdapterHardwareInfo` output is for Wi-Fi and was not used to infer the SSD link. AC power was connected and Defender real-time protection was on (operator-confirmed, not captured by the environment script). The captured `powercfg` scheme and confirmed Windows Settings both report Balanced; Energy Saver was off. The thermal traces reached about 82 C, but no controlled throttling test was performed. The sequential run did not establish an SLC cliff or post-cache rate. One device, host, and session were measured. The WSL2 virtual disk pitfall was not run. The main target file and state target remain after the run; copies are retained under `ssdtest/` (4 GiB each). The project driver does not remove the primary target. Important files were copied to a separate folder on the Desktop as a backup precaution (operator-confirmed; exact folder name not supplied). The test workload was isolated to disposable files rather than raw-device writes. These binary target files are ignored by Git but add 8 GiB to a manually assembled submission archive.

## Appendix A. AI use

Claude (Anthropic) and OpenAI Codex were used to plot the raw data into a visual graph, generate the report structure, organize report formatting, and answered any general debugging questions. They assisted in developing the FIO scripts and generating result logs, as well as sanity checks, general setup instructions, and initial hypothesis brainstorming. 

## Appendix B. Reproduction and evidence

The run was launched with `./run_all.sh 'C:\ssdtest\bench.fio-testfile' --fio "$FIO" 2>&1 | tee run.log`; `FIO` pointed to Windows fio 3.43. The wrapper captured environment information, ran the `run_fio.py` suite (including zero-queue and queue-depth workloads), and invoked `plot_fio.py`. The log records one random-write preconditioning pass and three repetitions. Per-run fio JSON in `data/raw/json/` records effective job options, including the 4 GiB range and timings. Result CSVs, processed tables, plots, logs and environment capture are in this project directory. The copied target payloads in `ssdtest/` are not result data. See `run.log`, `data/raw/*.csv`, and `data/raw/logs/`; processed tables are under `data/processed/` and figures are under `plots/`.

| Claim | Figure | Table / raw data |
|---|---|---|
| QD1 baselines | - | `zero_queue_table.csv`, `zero_queue.csv` |
| Block size and pattern | `bs_sweep.png` | `bs_sweep_agg.csv`, `bs_sweep.csv` |
| Read/write mix | `rw_mix.png` | `rw_mix_agg.csv`, `rw_mix.csv` |
| Queue-depth knee | `qd_sweep_knee.png`, `jobs_sweep.png` | `knee_summary.csv`, `qd_sweep.csv` |
| Tail latency | `tail_latency.png` | `tail_table.csv`, `tail.csv` |
| Device state | `device_state_timeseries.png` | `data/raw/logs/` |
| Pitfalls | `pitfalls.png` | `pitfalls_agg.csv`, `pitfalls.csv` |
