# Project 2: Cache and Memory Performance Profiling on an AMD Ryzen 7 5825U (Zen 3, WSL2)

ECSE 4320/6320 Advanced Computer Systems, class-wide project 2. Results/environment captures: 2026-11-01 to 2026-11-03, including the later tagged power comparison.
Companion files: [HYPOTHESES.md](HYPOTHESES.md) (pre-experiment predictions), [RESULTS_TABLES.md](RESULTS_TABLES.md) (generated summary tables).

## Summary
On one Zen 3 laptop core, a dependent-load pointer chase gives about **1.0 ns in L1, 3.1 ns in L2, 12 to 14 ns in smaller L3-resident footprints, and 123 to 143 ns in DRAM**. The retained clock estimate is 4.280 GHz (add chain) and 4.251 GHz (imul chain); this is an estimate, not a directly read core clock. Regular 4 KiB pages add about 20% in DRAM (172 vs 143 ns in the baseline zero-queue capture).
A sequential chase is 31x faster than a random one in DRAM (4.2 vs 129 ns): prefetchers hide latency. TLB reach shows up where the hardware sizes predict: with 4 KiB pages a step of about 2 ns at 64 pages (L1 DTLB) and 5 to 9 ns at 2048 pages (L2 DTLB), absent with transparent huge pages.
Sequential bandwidth reaches 16.5 GB/s with one thread and saturates at **26 to 27 GB/s with 8 threads, only about 52% of the 51.2 GB/s theoretical dual-channel DDR4-3200 peak**; under that load the latency seen by a probe rises to 598 ns, 4.6x the unloaded value.
Sequential write-only traffic reaches only 29% of read-only bandwidth, and random loads from my generator are **concurrency-limited** (about 4 to 7 lines in flight per thread, far below the roughly 24 miss buffers of a core), so they never saturate DRAM.
An independent STREAM-style triad agrees with the bandwidth tool within 13%. A later tagged WSL2 follow-up did collect numeric cycles, instruction, L1 data-cache, generic cache, and DTLB events for the cache-footprint and TLB workloads (`data/raw/cache_miss_counters.csv`, `data/raw/tlb_counters.csv`). These counters add direct evidence to the timing/AMAT analysis; the follow-up is kept separate from the original measurements because its preflight reported AC power offline.

## 1. Introduction
Latency, bandwidth and concurrency are linked by Little's Law: bytes in flight equal bandwidth times latency, so a core with a fixed number of outstanding misses cannot exceed (misses x 64 B)/latency, and offering more load than the memory system can serve only adds queueing delay.
This study measures the memory hierarchy of one Zen 3 laptop CPU with purpose-built micro-benchmarks and explains the results with Little's Law and the average memory access time, AMAT = sum over levels of (fraction of accesses served there) x (latency there).

## 2. Platform and methodology
Table 1. Platform (`env/cache_env.txt`, `env/preflight.txt`, original captures 2026-11-01; user-confirmed Windows mode settings apply to the experiment runs).

| item | setting |
|---|---|
| CPU | AMD Ryzen 7 5825U (Zen 3), 8 cores / 16 threads, 2.0 GHz base, up to 4.5 GHz boost ([AMD official specifications](https://www.amd.com/en/support/downloads/drivers.html/processors/ryzen/ryzen-5000-series/amd-ryzen-7-5825u.html)); **estimated clock 4.280 GHz (dependent-add chain) and 4.251 GHz (dependent-imul chain)**, in agreement within 0.7% |
| Caches | L1D 32 KiB/core, L2 512 KiB/core, L3 16 MiB shared, 64 B lines (`lscpu`) |
| Memory | 2 x 8 GiB, rated 3200 MT/s, banks `P0 CHANNEL A` and `P0 CHANNEL B` (**dual channel**), form factor 12 (SO-DIMM). WMI reports MemoryType 0 (unknown); an SO-DIMM on this CPU is DDR4, so the module is DDR4-3200. **Theoretical peak 3200 MT/s x 8 B x 2 channels = 51.2 GB/s.** The configured (running) speed was not recorded |
| OS | Windows 11 Version 26H2 (Build 26300.9711) hosting WSL2, kernel 6.6.87.2-microsoft-standard-WSL2, Ubuntu 24.04.4 LTS; 7.4 GiB visible to WSL2 (6.8 GiB available at start) |
| Tools | GCC 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1), Python 3.12.3, pandas 2.1.4, matplotlib 3.6.3 |
| Power | Main experiment settings: Windows **Best performance**, **Energy Saver off** (operator-confirmed; not recorded by WSL2). A zero-queue comparison was captured with **Balanced** and **Energy Saver on** (`zero_queue_saver.csv`; user-confirmed). The preflight immediately preceding the Nov. 3 tagged counter follow-up reported AC power offline (`AC power online: 0`); Windows power mode and Energy Saver state for that follow-up were not recaptured. |
| SMT, pinning | SMT on (16 logical, 8 physical cores); threads pinned (`taskset`, `pthread_setaffinity_np`) to the first logical CPU of each physical core (0, 2, 4, ..., 14); load average at start 0.09 |
| THP | mode `madvise`; huge pages requested with `madvise(MADV_HUGEPAGE)` and **verified active** (`thp_kb` is greater than zero in every huge-page row: 2,048 kB for the small buffers, 1,048,576 kB for the 1 GiB buffer) |
| Counters | Original full-suite capture had no usable hardware counters. In the later WSL2 follow-up, the preflight detected `perf` and all event columns in the tagged cache/TLB CSVs contain numeric values: cycles, instructions, L1-dcache loads/misses, cache references/misses, and dTLB loads/misses. |
| NUMA | single node |

**Tools (custom: Intel MLC is Intel-only).**
`memlat` follows one random single-cycle permutation (Sattolo shuffle) of nodes spaced `gran` bytes apart, so every load depends on the previous one; time per step is the load-to-use latency of the level that holds the footprint. Options: sequential pattern, K independent chains (K outstanding misses), page-granular nodes (TLB test), huge pages on/off.
`membw` runs N pinned threads, each streaming over its own private 256 MiB buffer with 64 B line operations (explicit 2 x 32 B AVX2 loads/stores), sequential or random, stride 64/256/1024 B, read share 100/70/50/0%, an injected delay (offered-load control), and an optional probe thread that chases pointers over its own 256 MiB buffer while the load runs (loaded latency).
`stream_triad` is an independent OpenMP STREAM-style triad used as a cross-check.
**Repetitions.** Latency points: 7 repetitions per process (3 for the TLB runs), median with standard deviation as error bars. Bandwidth and loaded-latency points: one 3 s run per point, so **no error bars**. Pinning pitfall: 12 processes per mode.
**Benchmark validation (before measuring).** The compiled hot loops were audited in the disassembly: the chase loops are serial `mov (%rax),%rax` chains; the random-access path of `membw` originally contained a 64-bit `div` per access and scalar 8 x 8 B line operations (replaced by a multiply-high range reduction and AVX2 operations); the first clock estimator used `add $imm` chains, which some cores collapse (it printed 13 GHz in testing) and was replaced by register-add and `imul` chains that must agree (Appendix D).
**Footprints.** L1 16 KiB, L2 256 KiB, L3 8 MiB, DRAM 1 GiB for the zero-queue test; 4 KiB to 1 GiB (half-octave steps) for the working-set sweep; DRAM-sized tests use 256 MiB to 512 MiB per thread (about 2 GiB in total for 8 threads, well below the 6.8 GiB available).
**Known limits.** WSL2 (nested paging); the tagged counter follow-up is supplementary and has a different power-state record from the main suite. One machine (with a power-mode comparison session), regular stores (no non-temporal stores), write-allocate fills not counted as "useful" bandwidth, and configured memory speed not recorded.

## 3. Hypotheses
Predictions with their reasons are in [HYPOTHESES.md](HYPOTHESES.md). Outcomes are compared in section 6.

## 4. Results
### 4.1 Zero-queue baselines
*Question.* What is the load-to-use latency of each level without queueing? *Expectation (H1).* L1 about 4 cycles, L2 12 to 14, L3 about 46 to 55, DRAM 80 to 140 ns; 20% to 80% higher in DRAM without huge pages.
*Method.* Random chase, 1 chain, footprints 16 KiB, 256 KiB, 8 MiB, 1 GiB, huge pages on and off, 7 repetitions (`zero_queue.csv`); cycle conversions use the estimated 4.280 GHz add-chain value.

Table 2. Zero-queue latency (median of 7 +- standard deviation; RESULTS_TABLES section 1).

| level | huge pages: ns (cycles) | 4 KiB pages: ns (cycles) | note |
|---|---|---|---|
| L1 (16 KiB) | 1.67 +- 0.44 (7.1) | **1.05 +- 0.03 (4.5)** | the huge-page row was disturbed (repetitions from 1.1 to 2.3 ns); the working-set sweep gives 1.0 ns for the same case |
| L2 (256 KiB) | **3.14 +- 0.08 (13.4)** | 3.17 +- 0.05 (13.6) | stable |
| L3 (8 MiB) | 14.75 +- 4.70 (63.1) | 23.0 +- 9.0 (98.5) | noisy and near the L3 edge; the sweep gives **12.0 ns (48 cycles) at 2 MiB and 14.1 ns (57 cycles) at 4 MiB** |
| DRAM (1 GiB) | **142.9 +- 14.2 (611)** | 171.7 +- 16.6 (735) | the sweep gives 123 to 137 ns for 128 MiB to 1 GiB; the first repetition was slower |

*Result.* The 4 KiB-page L1 and L2 medians are 1.05 and 3.17 ns; the huge-page L2 value is 3.14 ns. L3 values are noisy at 8 MiB, while the working-set sweep gives about 12 to 14 ns for 2 to 4 MiB and rises at the measured L3 edge. DRAM latency is 123 to 137 ns in the working-set sweep and 143 ns in the baseline zero-queue table; huge pages lower the zero-queue median by 17% (172 to 143 ns), below the predicted 20% to 80%. Cycle conversions use the 4.280 GHz estimated clock (about 4.5 cycles for L1, 13.5 for L2, 51 to 60 for 2 to 4 MiB L3 footprints, and 611 cycles for the huge-page 1 GiB point).
*Explanation.* The L1 (huge pages) and L3 rows carry transient disturbances (large standard deviations): WSL2 can move a virtual CPU or change its clock between repetitions (hypothesis, not isolated); the stable rows (L2, DRAM) and the sweep points are consistent. DRAM latency above the 80 to 100 ns typical of native systems is plausible for DDR4 SO-DIMMs plus virtualization (hypothesis).
The 17% gain from huge pages is small compared with the TLB penalty in 4.5 because this chase touches every line of 1 GiB, so most of its cost is the DRAM access itself.
*Implication.* Quote latency in cycles with the estimated clock, use several independent points, and distrust the first rows of a run.

### 4.2 Working-set sweep, pattern and granularity
*Expectation (H2, H3).* Steps near 32 KiB, 512 KiB and 16 MiB; sequential at least 5x lower than random at DRAM size; random flat across granularity; sequential latency rising with granularity (256 B: 15 to 50 ns, 1024 B: 50% to 100% of random); one-thread sequential read 15 to 30 GB/s, random 10 to 16 GB/s; all-core sequential read 65% to 90% of the memory peak; useful bandwidth at stride 256/1024 B 40% to 80% / 20% to 60% of stride 64.

Table 3. Chase latency (ns) versus working set, huge pages (`ws_sweep.csv`, `plots/ws_sweep_latency.png`).

| working set | 16 KiB | 64 KiB | 512 KiB | 724 KiB | 2 MiB | 8 MiB | 11.6 MiB | 32 MiB | 256 MiB | 1 GiB |
|---|---|---|---|---|---|---|---|---|---|---|
| random chase | 1.00 | 3.02 | 3.20 | 8.24 | 11.96 | 20.30 | **97.8** | 105.8 | 127.7 | 136.8 |
| sequential chase | 1.01 | 1.08 | 1.04 | 1.13 | 1.13 | 1.29 | 2.38 | 4.22 | 4.19 | 4.19 |

Table 4. Pattern and granularity (DRAM-sized chase latency in ns, median of 7; bandwidth in GB/s, one 3 s run per point; `pattern_lat.csv`, `pattern_bw.csv`).

| | 64 B | 256 B | 1024 B |
|---|---|---|---|
| random chase latency | 129.2 | 130.7 | 120.7 |
| sequential chase latency | 4.21 | 4.53 | 12.85 |
| 1 thread, sequential read, by stride | 16.53 | 10.94 | 9.00 |
| 8 threads, sequential read, by stride | 26.06 | 14.18 | 17.19 |
| 1 thread, random read | 3.41 | 3.42 | 3.41 |
| 8 threads, random read | 11.09 | 11.63 | 11.46 |

*Result.* The latency steps occur at the predicted places: L1 to L2 between 32 and 64 KiB (1.0 to 3.0 ns), L2 to L3 between 512 and 724 KiB (3.2 to 8.2 ns), and L3 to DRAM between 8.4 and 11.6 MiB (20 to 98 ns), **earlier than the 16 MiB nominal capacity**. Random latency is flat across granularity (121 to 131 ns). The sequential chase is **31x lower than random in DRAM** (4.2 vs 129 ns), 4.5 ns at 256 B and **12.9 ns (10% of random) at 1024 B**.
One-thread sequential read reaches 16.5 GB/s (low end of the predicted range); **8 threads reach 26.1 GB/s, 1.58x one thread and 51% of the 51.2 GB/s theoretical peak (below the predicted 65% to 90%)**. Useful bandwidth at stride 256 B and 1024 B is 66% and 54% of stride 64 for one thread (within the predicted bands) and 54% and 66% for 8 threads.
Random reads reach only **3.4 GB/s per thread (53 M lines/s) and 11.1 GB/s with 8 threads**, regardless of stride (below the predicted 10 to 16 GB/s for one thread).
*Explanation.* The sequential chase and stream are served by hardware prefetchers; even a 1 KiB stride, which places only four accesses in each 4 KiB page, is prefetched well (12.9 ns), contrary to my prediction. The early L3 edge (8 to 12 MiB) may mean that part of the shared L3 is not available to this thread (other cores, the GPU, virtualization; hypothesis, not tested; test: repeat with other activity stopped).
The measured 26 to 30 GB/s stream ceiling is about half of the theoretical DDR4-3200 peak. **Cross-check with Project 1:** its current processed roofline input is 28.3 GB/s for a single-thread two-array read stream, within about 9% of the 26.1 GB/s 8-thread aggregate here. This supports a platform ceiling near 27 GB/s (possibly a lower configured memory speed, which was not recorded, or another platform limit) rather than a limit of this tool; test: record the configured clock speed and repeat with a two-stream read loop.
Random bandwidth is limited by the generator: 3.41 GB/s with a 130 ns latency means 53.3 M lines/s x 130 ns = **6.9 lines in flight** per thread, against about 22 to 24 L1 miss buffers (and 16 lines in flight reached by the 16-chain test in 4.4); the cause is not established (hypothesis: the instruction window fills with the loop's roughly 20 instructions per line; test: batch the address generation or unroll the loop).
*Implication.* Prefetching makes streaming access nearly latency-free, and random access depends on the concurrency the code exposes, not only on the memory.

### 4.3 Read/write mix
*Expectation (H4).* Write-only counted bandwidth 50% to 70% of read-only, mixes in between, latency under load up 10% to 50% at 50/50.
*Method.* 7 load threads plus 1 probe thread, 256 MiB per thread, 100/70/50/0% reads, sequential and random, one 3 s run each.

Table 5. Read/write mix (`rw_mix.csv`; lines in flight = lines/s x probe latency).

| pattern | reads | bandwidth (GB/s) | vs read-only | probe latency (ns) | lines in flight |
|---|---|---|---|---|---|
| sequential | 100% | 27.1 | 1.00 | 598 | 253 |
| sequential | 70% | 16.9 | 0.62 | 517 | 137 |
| sequential | 50% | 13.7 | 0.51 | 570 | 122 |
| sequential | 0% | 7.9 | **0.29** | 613 | 76 |
| random | 100% | 10.6 | 1.00 | 182 | 30 |
| random | 70% | 8.9 | 0.84 | 227 | 32 |
| random | 50% | 8.1 | 0.76 | 253 | 32 |
| random | 0% | 6.4 | 0.60 | 308 | 31 |

*Result.* Bandwidth falls monotonically with write share. **Sequential write-only reaches only 29% of read-only** (below the predicted 50% to 70%), random write-only 60% (inside it). Under sequential load the probe latency is 517 to 613 ns, 4.0x to 4.7x the unloaded 130 ns, without a trend; under random load it rises from 182 to 308 ns (+39% at 50/50, within the predicted band).
*Explanation.* A written line costs a read-for-ownership and a write-back, so a counted write consumes about twice the bus traffic of a read: write-only moves 7.9 GB/s counted, about 15.8 GB/s of actual traffic, still below the 27 GB/s read-only rate, so read/write bus turnaround and write handling add to the cost (hypothesis, untested).
In the random runs the lines in flight stay at 30 to 32 at every mix: **the load is concurrency-limited, so bandwidth is about 31 x 64 B divided by latency and falls as latency rises** (Little's Law at fixed concurrency). Under sequential load the product falls from 253 to 76 as bandwidth falls, i.e. the memory system, not the generator, is the limit.
At 100% sequential read the Little's Law product with the probe latency, 253 lines, exceeds 7 threads x 24 L1 miss buffers = 168: hardware prefetch must supply additional outstanding requests, or the stream's own latency is lower than the probe's (hypothesis, untested).
*Implication.* Budget writes at about double their counted cost, and expect the write share to matter more than the CPU once the bus is the bottleneck.

### 4.4 Throughput-latency tradeoff, knee and Little's Law
*Expectation (H5).* Probe latency within 1.2x of unloaded up to 60% to 70% of maximum bandwidth, a knee at 70% to 85%, 2x to 4x latency at saturation, 40 to 120 lines in flight at the knee (below 8 x 24 = 192), and a single-core chain test that flattens at K of 12 to 16.
*Method.* Offered load varied by injected delay and by 1, 2, 4 and 7 load threads with either random (`intensity.csv`) or sequential (`intensity_seq.csv`) 100%-read patterns; probe latency was measured concurrently. K independent chains on one core are in `chains.csv`. Knee = Kneedle point (farthest from the chord of the normalised curve); the estimator is unreliable for nearly flat curves.

Table 6. Random-load sweep (RESULTS_TABLES section 5; `plots/intensity_knee.png`).

| load threads | max bandwidth (GB/s) | unloaded latency (ns) | latency at max load (ns) | ratio | lines in flight at max |
|---|---|---|---|---|---|
| 1 | 3.07 | 124.5 | 126.9 | 1.02 | 6.1 |
| 2 | 5.52 | 123.9 | 133.6 | 1.08 | 11.5 |
| 4 | 8.13 | 126.8 | 150.0 | 1.18 | 19.0 |
| 7 | 9.93 | 130.2 | 190.4 | 1.46 | 29.5 |

Table 7. One core, K independent chains (`chains.csv`; lines in flight equal K by construction; `plots/chains_mlp.png`).

| K | 1 | 2 | 3 | 4 | 6 | 8 | 12 | 16 |
|---|---|---|---|---|---|---|---|---|
| throughput (M loads/s) | 7.6 | 15.7 | 23.5 | 22.8 | 41.5 | 47.3 | 66.7 | 86.1 |
| latency (ns) | 131.5 | 127.7 | 127.6 | 175.5 | 144.7 | 169.2 | 179.9 | 185.8 |
| equivalent GB/s | 0.49 | 1.00 | 1.50 | 1.46 | 2.66 | 3.03 | 4.27 | 5.51 |

Table 7b. Sequential-load sweep at the maximum offered load (zero injected delay; `intensity_seq.csv`; see `plots/intensity_knee_seq.png`).

| load threads | max throughput (GB/s) | probe latency at max (ns) | Kneedle throughput (GB/s) | Kneedle latency (ns) |
|---:|---:|---:|---:|---:|
| 1 | 16.66 | 150 | 0.38 | 125 |
| 2 | 21.56 | 236 | 1.47 | 125 |
| 4 | 29.79 | 339 | 6.72 | 138 |
| 7 | 25.95 | 617 | 10.69 | 156 |

The one- and two-thread Kneedle points are not meaningful saturation estimates: their curves are mostly flat in latency until offered bandwidth collapses at high injected delay.

*Result.* **The random-load sweep never saturates the memory system.** Its largest latency (7 threads) is 190 ns (1.46x unloaded) at 9.9 GB/s, 19% of the theoretical peak and 37% of what sequential streams reach, so no 2x to 4x latency and no knee at 70% to 85% of the maximum appears. With 7 threads the latency is flat at 130 to 133 ns up to 2.8 GB/s and then rises (152 ns at 3.9 GB/s, 190 ns at 9.9 GB/s); the only knee-like feature is near 3 to 4 GB/s with about 9 lines in flight (the Kneedle point for 7 threads is 2.8 GB/s; for 1 to 4 threads the curves are too flat for the method to mean anything).
The single-core test scales almost linearly up to K = 16 (86 M loads/s, 5.5 GB/s, 11x the throughput of K = 1 for 16x the chains); **it has not flattened** (K = 12 to 16 still gives +29%), so the miss-buffer limit is above 16 and was not reached. The latency is flat at 128 to 131 ns for K up to 3 and 145 to 186 ns for K of 4 or more, with an unexplained dip at K = 4 (throughput below K = 3).
**Saturation is visible only in the sequential data:** 8 threads give 1.58x the bandwidth of one thread (diminishing returns at 26 to 27 GB/s), and with 7 sequential load threads the probe latency is 598 ns, 4.6x unloaded, at 27.1 GB/s (Table 5).
*Explanation.* Little's Law explains both shapes. Random loads from my generator keep only 4 to 6 lines in flight per thread (Table 6 divided by the thread count), so their bandwidth is bounded by concurrency divided by latency (1 thread: 6.1 x 64 B / 125 ns = 3.1 GB/s), and adding threads adds bandwidth almost linearly without reaching DRAM's limit. Streams are served by prefetchers with much more concurrency (253 lines in flight at saturation), which does reach the memory limit and produces the 4.6x latency.
The sequential-load sweep (`intensity_seq.csv`, `plots/intensity_knee_seq.png`) fills the previous data gap. With zero injected delay, throughput is 16.7, 21.6, and 29.8 GB/s at 1, 2, and 4 threads, then falls to 26.0 GB/s at 7 threads; probe latency at those points is 150, 236, 339, and 617 ns. Kneedle identifies 10.7 GB/s and 156 ns at 7 threads, but the 1- and 2-thread knee estimates are near-zero/low because their curves are nearly flat. Treat these algorithmic knee points as approximate; the high-load data show saturation and rising latency, with the strongest result at 7 threads. The K = 4 irregularity in the independent-chain test remains unexplained.
*Implication.* More outstanding requests raise throughput until a shared resource saturates, after which they only raise latency; whether a program reaches that point depends on how much concurrency its access pattern exposes.

### 4.5 Working set, cache-miss impact and TLB reach
*Expectation (H6, H7).* The miss fraction implied by measured AMAT matches the capacity model within 25% above 32 MiB; with 4 KiB pages a step of +1.5 to 3 ns beyond 64 pages and +5 to 15 ns (up to +60 under nested paging) beyond 2048 pages, absent with huge pages; a difference of at least 20% at 4096 or more pages.
*Method.* Footprint sweep with 64 B operations, 1 thread, sequential and random (`cache_miss.csv`); AMAT capacity model with the zero-queue latencies and capacities 32 KiB, 512 KiB, 16 MiB (`amat_model.csv`); TLB test with one node per 4 KiB page, 4 KiB pages against huge pages, 3 repetitions (`tlb.csv`). The original run had no usable counters. A later tagged run collected counters for these two experiments; see Tables 10a-10b. The TLB counter values are process totals from `perf stat` around each three-repetition `memlat` process, repeated on each `rep` row in the raw CSV. Rates below use the event counts from one process/configuration, not three independent counter samples.

Table 8. Footprint sweep, ns per 64 B operation, 1 thread (`plots/cache_miss_inferred.png`).

| working set | 4 KiB | 32 KiB | 512 KiB | 8 MiB | 16 MiB | 64 MiB | 1 GiB |
|---|---|---|---|---|---|---|---|
| sequential | 1.70 | 1.57 | 1.61 | 1.68 | 2.89 | 3.54 | 3.64 |
| random | 1.53 | 1.58 | 2.44 | 3.33 | 11.91 | 17.50 | 19.58 |

Table 9. AMAT: measured chase latency against the capacity model, huge pages (`plots/amat_model.png`; RESULTS_TABLES section 11). Implied fraction = (measured - L1) / (DRAM - L1).

| working set | measured (ns) | model (ns) | fraction going to DRAM, implied by measurement | fraction, capacity model |
|---|---|---|---|---|
| 4 MiB | 14.1 | 13.3 | 0.09 | 0 |
| 8 MiB | 20.3 | 14.0 | 0.13 | 0 |
| 11.3 MiB | 97.8 | 14.2 | **0.68** | 0 |
| 16 MiB | 98.0 | 14.4 | **0.68** | 0 |
| 22.6 MiB | 104.7 | 52.0 | 0.73 | 0.29 |
| 32 MiB | 105.8 | 78.6 | 0.74 | 0.50 |
| 64 MiB | 118.0 | 110.7 | 0.82 | 0.75 |
| 256 MiB | 127.7 | 134.8 | 0.89 | 0.94 |
| 1 GiB | 136.8 | 140.8 | 0.96 | 0.98 |

Table 10. TLB: random chase with one node per 4 KiB page (median of 3; `plots/tlb_impact.png`, `data/processed/tlb_delta.csv`).

| distinct pages | 32 | 64 | 90 | 512 | 1448 | 2048 | 2896 | 8192 | 23170 | 131072 | 262144 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 4 KiB pages (ns) | 0.98 | 0.99 | 2.96 | 2.75 | 5.03 | 9.59 | 13.55 | 25.59 | 32.92 | 169.35 | 172.68 |
| huge pages (ns) | 1.05 | 0.98 | 0.98 | 2.04 | 4.98 | 4.83 | 4.95 | 13.40 | 24.35 | 127.42 | 132.87 |
| difference (ns) | -0.07 | 0.01 | +1.97 | +0.71 | +0.06 | +4.76 | +8.60 | +12.19 | +8.57 | +41.93 | +39.81 |

*Result.* **TLB steps match the hardware sizes.** With 4 KiB pages the latency rises from 0.99 to 2.96 ns between 64 and 90 pages (+2.0 ns, about 8 cycles: the 64-entry L1 DTLB) and by another +4.8 to +8.6 ns at 2048 to 2896 pages (the 2048-entry L2 DTLB, 8 MiB of reach); with huge pages neither step appears (the huge-page curve rises only where the touched lines leave L1, at about 512 pages). From about 92,000 pages up, regular pages are 20% to 33% slower (+24 to +42 ns, within the +60 ns nested-paging bound).
The footprint sweep reproduces the capacity steps: sequential flat near 1.6 ns per line up to 8 MiB, then 2.9 to 3.9 ns; random rising from 1.5 ns to 3.3 ns at 8 MiB, 11.9 ns at 16 MiB and 19.6 ns beyond. The inferred DRAM-access fraction follows the capacity model within 25% from 64 MiB upward (0.82 vs 0.75, 0.89 vs 0.94, 0.96 vs 0.98) but sits far above it from 11 to 32 MiB (0.68 vs 0, 0.74 vs 0.50): **the effective L3 capacity is about 8 to 12 MiB**, not 16 MiB.
*Explanation.* The page-chase footprint is one line per page, so up to 512 pages (32 KiB of lines) it fits in L1 and the huge-page curve measures pure cache behaviour: that curve is the control, and the 4 KiB minus huge-page difference isolates the TLB cost. Beyond about 8192 pages the lines no longer fit in L2, so both curves also include L3 and DRAM effects; the difference column removes them to first order. The single reversal at 65536 pages (-20 ns) falls in the L3-to-DRAM transition and is probably noise at the capacity edge.
The in-cache bandwidth values (1.5 to 1.7 ns per 64 B line, about 40 GB/s even for an L1-resident buffer) are **limited by the tool's own per-line cost (about 6.4 cycles)**, not by the caches: only the DRAM-resident values (17.5 to 19.6 ns random, 3.5 to 3.9 ns sequential per line) are meaningful bandwidths.
The two measurements are consistent through Little's Law: at 1 GiB a random line costs 19.6 ns although a dependent miss costs 137 ns; the ratio, about 7, is the number of lines in flight (6.9, from 4.2).
*Implication.* Huge pages matter once a working set exceeds the 8 MiB TLB reach (here up to 40 ns, 25% to 30% of the access time), and cache-capacity edges should be taken from measurement, not from the specification sheet.

**Follow-up hardware-counter evidence (Nov. 3, 2026).** The user ran `python3 run_experiments.py --only cache_miss,tlb --tag counters` in WSL2. All eight counter columns in both tagged CSVs are numeric. Table 10a shows the random-footprint slowdown accompanied by an increase in the generic cache-miss/reference ratio. The cache-resident 64 KiB bandwidth remains tool-limited, as discussed above. These event ratios are reported as Linux `perf` aliases; their exact hardware mapping is platform-dependent.

Table 10a. Selected cache-footprint counter results from tagged 3 s `membw` runs (one run per point; no error bars). Miss ratios are computed from the raw event counts.

| pattern | working set | measured bandwidth (GB/s) | L1D load misses / loads | generic cache misses / references |
|---|---:|---:|---:|---:|
| random | 64 KiB | 40.45 | 16.98% | 0.04% |
| random | 8 MiB | 22.36 | 33.26% | 62.54% |
| random | 16 MiB | 5.43 | 33.19% | 65.97% |
| random | 1 GiB | 3.34 | 30.98% | 74.04% |
| sequential | 1 GiB | 19.43 | 24.70% | 1.10% |

The increase in cache-miss ratio across the random working-set points tracks the throughput drop, while the 1 GiB sequential stream has a low generic cache-miss ratio and higher throughput, consistent with spatial locality and prefetching. These are process-level counter totals; they support the trend but should not be treated as isolated counts for each timed inner-loop iteration.

Table 10b. Selected TLB footprint points from tagged `memlat` runs. The THP column gives the actual huge-page backing reported by the run; miss ratio is dTLB-load-misses / dTLB-loads.

| working set | 4 KiB pages: latency; dTLB miss ratio | THP backing | huge pages: latency; dTLB miss ratio |
|---|---:|---:|---:|
| 8 MiB (2,048 pages) | 9.051 ns; 35.04% | 8,192 KiB | 4.733 ns; 0.04% |
| 64 MiB (16,384 pages) | 29.497 ns; 88.81% | 65,536 KiB | 20.646 ns; 63.85% |
| 1 GiB (262,144 pages) | 171.663 ns; 96.17% | 1,048,576 KiB | 152.915 ns; 93.14% |

At these points, lower dTLB miss ratios with THP accompany lower measured latency, especially at 8 MiB; at 1 GiB, the miss ratios remain high and latency falls by only about 11%, consistent with DRAM latency dominating. Counter ratios are descriptive rather than causal: `perf stat` wraps the whole process, so counts include setup as well as the repeated chase, and WSL2 adds nested-virtualization effects.

### 4.6 Cross-check of the bandwidth tool
*Expectation (H9).* `membw` 70/30 sequential bandwidth within 25% of an independent STREAM-style triad, both saturating at about the same thread count.

Table 11. Counted bandwidth, GB/s (`crosscheck.csv`; triad counts 24 B per element, no write-allocate).

| threads | 1 | 2 | 4 | 8 |
|---|---|---|---|---|
| STREAM-style triad | 12.9 | 16.6 | 16.9 | 14.7 |
| `membw` 70/30 sequential | 11.3 | 16.0 | 17.5 | 14.9 |
| ratio | 0.87 | 0.97 | 1.04 | 1.01 |

*Result.* The two tools agree within 13% at every thread count (ratio 0.87 to 1.04) and both saturate at 2 to 4 threads at about 17 GB/s; both decline at 8 threads (14.7 and 14.9 GB/s), which I cannot explain (hypothesis: bus turnaround or scheduling with all physical cores busy; untested).
*Implication.* The bandwidth tool is trustworthy to about 15% for a mixed workload; this does not validate its random-load concurrency (4.2).

## 5. Benchmark pitfalls demonstrated
**(a) A cache-resident buffer reported as DRAM bandwidth.** One-thread sequential read measured 38.2, 37.0 and 37.9 GB/s for 1, 4 and 8 MiB buffers against 18.7, 18.4 and 17.5 GB/s for 32, 128 and 512 MiB: a buffer that fits in cache would be reported as DRAM at **2.0x to 2.2x** the true value (`pitfall_cachereuse.csv`; the inflation is understated because the cache-resident rate is itself limited by the tool at about 40 GB/s).
**(b) Not pinning.** 12 processes per mode: pinned median 126 ns, spread (coefficient of variation) 3.15% with one outlier at 147 ns; unpinned median 126 ns, 1.97%. **No measurable effect** here: under WSL2 "pinned" means a virtual CPU and the system was nearly idle (load average 0.09), so the predicted larger spread was not observed (`pitfall_pin.csv`).
**(c) A sequential chase understates latency.** 4.2 ns against 129 ns for the random chase of the same buffer: **31x** too low if used as "DRAM latency".
**(d) Measuring only the first run.** The first rows of the zero-queue run (L1 with huge pages, L3) have standard deviations of 26% to 39%; later measurements of the same levels (working-set sweep) are stable. Taking the first row alone would have given a 60% too high L1 latency (1.67 vs 1.05 ns).
**(e) Power mode.** The same zero-queue test was captured in the normal Best performance / Energy Saver off mode and again in Balanced / Energy Saver on mode (`zero_queue_best.csv`, `zero_queue_saver.csv`, and `freq_estimate_best.txt` / `freq_estimate_saver.txt`). Across the huge-page rows, the Best performance vs Balanced/Energy Saver medians were L1 0.98 vs 2.36 ns, L2 2.91 vs 8.14 ns, L3 16.44 vs 30.06 ns, and DRAM 169.22 vs 191.07 ns. The two-chain clock estimates averaged 4.212 GHz vs 1.939 GHz. The cache-level changes are consistent with the much lower estimated clock under the power-saving setting; DRAM changes less. This is a two-condition comparison of the zero-queue test, not a full repeat of every Project 2 workload.

## 6. Expectations against outcomes
| topic | expected (HYPOTHESES.md) | observed | verdict |
|---|---|---|---|
| L1 / L2 / L3 latency (cycles) | about 4 / 12-14 / 46-55 | about 4.5 / 13.5 / 51-60 at the listed footprints | broadly matched; L3 is footprint-sensitive and noisy |
| DRAM latency, THP on; THP off | 80-140 ns; +20% to +80% | 123-143 ns; +17% (172 vs 143 ns) | matched (upper edge); THP gain just below range |
| steps in the sweep | 32 KiB, about 512 KiB, about 16 MiB | 32-64 KiB, 512-724 KiB, 8.4-11.6 MiB | matched; L3 edge earlier |
| sequential vs random chase, DRAM | at least 5x lower | 31x lower | matched |
| random chase vs granularity | flat (+-10%) | 121-131 ns | matched |
| sequential chase 256 B / 1024 B | 15-50 ns / 50-100% of random | 4.5 ns / 12.9 ns (10%) | not matched (prefetch handles the strides) |
| 1-thread sequential / random read | 15-30 / 10-16 GB/s | 16.5 / 3.4 GB/s | sequential matched; random not (generator limit) |
| all-core sequential read | 65-90% of memory peak | 26.1 GB/s = 51% | not matched |
| stride 256 / 1024 useful bandwidth | 40-80% / 20-60% of stride 64 | 66% / 54% (1 thread) | matched |
| write-only vs read-only | 50-70% | sequential 29%, random 60% | sequential not matched |
| probe latency vs write share | +10% to +50% at 50/50 | random +39%; sequential no trend | partly matched |
| knee at 70-85% of max BW; 2-4x latency | | random: no saturation; sequential: 29.8 GB/s peak at 4 threads, 26.0 GB/s at 7 threads with 4.9x probe latency | not matched for random; sequential saturation visible with contention at 7 threads |
| lines in flight at the knee | 40-120 (below 192) | random: about 6 at the Kneedle point (flat/noisy); sequential: about 26 at the 7-thread Kneedle point and about 250 at maximum offered load | random generator remains concurrency-limited; stream knee is approximate and saturation exceeds the prediction |
| single-core MLP plateau | K of 12-16 | still rising at K = 16 (86 M loads/s) | not matched (limit above 16) |
| TLB steps, 4 KiB pages | +1.5-3 ns at 64 pages; +5-15 ns at 2048 | +2.0 ns at 64-90 pages; +4.8 to +8.6 ns at 2048-2896 | matched |
| huge pages remove the steps; gap at 4096+ pages | yes; at least 20% | yes; +20% to +33% from about 92,000 pages | matched |
| AMAT model vs implied misses | within 25% above 32 MiB | within 25% from 64 MiB; effective L3 about 8-12 MiB | partly matched |
| cache-resident bandwidth reported as DRAM | 3x to 6x | 2.0x to 2.2x (tool-limited) | not matched |
| unpinned spread | 2x to 10x larger | none (1.97% vs 3.15%) | not matched |
| membw vs triad | within 25% | within 13% | matched |
| variability | cache latency under 3%; DRAM 3% to 15% | L2 1.5-2.7%, L1 (4 KiB pages) 2.4%; L1 (huge pages) and L3 26-39%; DRAM 10% | partly matched |
| power-mode repeat (H8) | core-level times may rise up to 1.5-2x; DRAM changes under 15% | Best performance vs Balanced/Energy Saver: 1.8-2.8x cache-level latency; DRAM +13% | qualitatively matched; L1/L2 exceed the predicted range |

## 7. Limitations / Notable Outlier Analysis
**Anomalies Examples (observation, hypothesis, test).**
1. **Random-load generator concurrency:** 4 to 7 lines in flight per thread (3.4 GB/s per thread) against about 24 miss buffers; the 16-chain test reaches 16. Hypothesis: instruction-window limit of the loop; test: unrolled or batched address generation.
2. **8-thread bandwidth ceiling:** 26 to 27 GB/s (51% to 53% of 51.2 GB/s), close to Project 1's 28.3 GB/s single-thread two-stream result. Hypothesis: platform cap or a lower configured memory speed; test: record `ConfiguredClockSpeed`, run a two-stream read at 1 to 8 threads.
3. **Write-only sequential 29% of read-only** (predicted 50% to 70%). Hypothesis: bus turnaround and write handling beyond the read-for-ownership cost; test: non-temporal stores.
4. **Early L3 edge** at 8 to 12 MiB. Hypothesis: part of the shared L3 unavailable; test: repeat with other activity stopped.
5. **K = 4 chains** has lower throughput and higher latency than K = 3 (and latency steps up from K = 4). Unexplained; test: inspect the loop code for K = 4 and its alignment (Project 1 found code placement changing speed by 2x).
6. **Disturbed first rows** of the zero-queue test (L1 with huge pages, L3). Hypothesis: transient WSL2 scheduling or clock effect; test: repeat the table in a second session.
7. **Triad and `membw` both fall at 8 threads** (to 14.7 and 14.9 GB/s from about 17). Untested.
8. **TLB point at 65536 pages** where huge pages are slower than 4 KiB pages (85 vs 65 ns): a one-point reversal in the L3-to-DRAM transition, probably noise.
9. **Sequential 1024 B chase at 10% of random** instead of 50% to 100%: the prefetcher handles long constant strides.

**Limitations.**
* **WSL2:** nested paging can inflate TLB-miss cost (the +24 to +42 ns at large footprints may differ on native Linux). The original suite had no usable counters; tagged follow-up cache/TLB runs returned numeric events, but were collected under a separate, incompletely documented power condition and process-level counts include setup. The clock is estimated with dependent chains, not read.
* **Configured memory speed** was not recorded, so the 51.2 GB/s theoretical peak is for the rated 3200 MT/s.
* Bandwidth and loaded-latency points are single 3 s runs without error bars; in-cache bandwidth is limited by the tool (about 6.4 cycles per line).
* The power-mode comparison covers zero-queue latency only; the original other workloads were run with Best performance and Energy Saver off. Windows settings were confirmed for those runs but are not captured inside WSL2. The Nov. 3 counter preflight reported AC offline; the power mode for that follow-up is unknown.
* One host; power-mode comparison adds a second measurement condition, but this does not replace independent machine/session replication.

## Appendix A. AI-use note
Benchmark code, build, script debugging, and initial project plan outline are assisted with using Claude, with Gemini used for debugging command lines and general topic questions. OpenAI Codex confirmed the deliverables by checking claims against retained results, and generated an organized processed tables and figures from supplied raw data.

## Appendix B. Reproduction
```
chmod +x *.sh *.py
./preflight.sh
./run_all.sh                       # build, environment, all experiments, plots, tables (about 40 min)
python3 run_experiments.py --only intensity_seq && python3 plot_all.py && python3 make_results_tables.py   # streaming-load throughput-latency sweep
python3 run_experiments.py --only cache_miss,tlb --tag counters   # supplementary counter capture (tag preserves prior CSVs)
```
Raw data `data/raw/*.csv`, processed `data/processed/*.csv`, figures `plots/`, tables `RESULTS_TABLES.md`, environment `env/`.

## Appendix C. Evidence index
| claim / figure | plot | table | raw data |
|---|---|---|---|
| zero-queue latency (4.1) | | RESULTS_TABLES 0, 1 | zero_queue.csv, zero_queue_best.csv, zero_queue_saver.csv; freq_estimate_*.txt |
| working-set sweep (4.2) | ws_sweep_latency | 2 | ws_sweep.csv |
| pattern, granularity, bandwidth (4.2) | pattern_granularity | 3a, 3b | pattern_lat.csv, pattern_bw.csv |
| read/write mix (4.3) | rw_mix | 4 | rw_mix.csv |
| knee, Little's Law (4.4) | intensity_knee, chains_mlp | 5, 6 | intensity.csv, chains.csv |
| footprint, AMAT (4.5) | cache_miss_inferred, amat_model | 7, 11 | cache_miss.csv, ws_sweep.csv |
| TLB (4.5) | tlb_impact | 8 | tlb.csv, processed/tlb_delta.csv |
| tagged counter follow-up (4.5) | - | 10a, 10b | cache_miss_counters.csv, tlb_counters.csv, freq_estimate_counters.txt |
| cross-check (4.6) | crosscheck | 10 | crosscheck.csv |
| pitfalls (5) | pitfalls | 9a, 9b | pitfall_pin.csv, pitfall_cachereuse.csv |

## Appendix D. Errors in the measurement tool-chain found before and during the study
* `membw` random path used `rs % nl` (a 64-bit division per access) and scalar 8 x 8 B line operations; found by disassembly; replaced with a multiply-high reduction and AVX2 line operations.
* The first clock estimator used `add $imm` chains, which some cores fold in the renamer (13 GHz printed in testing); replaced by register-add and `imul` chains that must agree (they agree within 0.1%).
* Sequential-stride chases staggered node offsets, which made a "256 B stride" irregular; the stagger now applies only to page-sized granules.
* The initial `perf` availability check found no usable counters in the original capture. The tagged follow-up produced numeric values for the listed cache and DTLB events; the existing timing-based plots remain for the original result set.
* The `--tag` option originally tagged experiment CSVs but overwrote the shared clock-estimate file. The driver now tags that file too; the original estimate in `freq_estimate_ghz.txt` was restored from the generated `RESULTS_TABLES.md`, and the follow-up estimate is retained as `freq_estimate_counters.txt`.
* The random-load intensity sweep did not reach saturation because the generator is concurrency-limited (4.4); this is a limitation of the experiment design, documented rather than hidden.
* Errors found and fixed before the measurements: a 64-bit division per access and scalar line operations in the bandwidth tool, an invalid clock estimator, irregular strides in the sequential chase, and a counter preflight that checked installation rather than whether a cycles event could be counted; at the analysis stage, empty counter panels in two figures were replaced and the random-load sweep was recognized as concurrency-limited.
