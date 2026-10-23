# Pre-experiment hypotheses (Project 2, cache and memory profiling)

Platform: AMD Ryzen 7 5825U (Zen 3, 8C/16T) under **WSL2** (Ubuntu 24.04, GCC 13.3.0), laptop memory type: DDR4-3200
Every prediction has a reason and a "wrong if".

## 0. Benchmarking
| fact | value | source / how to check |
|---|---|---|
| Caches | L1D 32 KiB (8-way), L2 512 KiB per core, L3 16 MiB shared, 64 B lines | `lscpu`; Illinois CS433 Zen slides |
| Latency (desktop Zen 3) | L2 about 12 cycles, L3 about 46 cycles (mobile L3 may differ) | Wikipedia "Zen 3" |
| L1 miss concurrency | about 22 to 24 outstanding L1 misses per core (miss address buffers) | Illinois slides (24); 7-cpu.com Zen/Zen 2 (22) |
| Cache-to-cache bandwidth (Zen/Zen 2 measurements) | L2 to L1 about 2.0 cycles per line (32 B/cycle datapath), L3 to L1 about 2.65 cycles per line | 7-cpu.com; treat as approximate for Zen 3 |
| TLB | L1 DTLB 64 entries, L2 DTLB 2048 entries (4 KiB and 2 MiB pages); 2 page walkers | Illinois slides; 7-cpu.com |
| Memory | CPU supports DDR4-3200 or LPDDR4x-4266, 2 channels: DDR4-3200 theoretical 51.2 GB/s; LPDDR4x-4266 x 128 bit about 68 GB/s (my arithmetic) | cpu-monkey / notebookcheck spec pages; **check your laptop** (PowerShell `Get-CimInstance Win32_PhysicalMemory`) |
| Clock | 2.0 GHz base, up to 4.5 GHz single-core boost, about 3.5 GHz all-core | spec pages; Project 1 inferred about 4.0 to 4.5 GHz during single-core loops |

Little's Law (used throughout): bytes in flight = bandwidth x latency; with 64 B lines, lines in flight = (GB/s / 0.064) x latency in microseconds.
Using WSL2 adds two limitations: Nested paging (a TLB miss walks guest and host page tables, so 4 KiB-page results can be worse than native), and no hardware perf counters (cache/TLB statements must use the AMAT model and timing; this is stated in the report).
Core clock cannot be read in the guest; the tools estimate it from dependent-ADD and dependent-IMUL chains and cycle numbers inherit that uncertainty.

## 1. Predictions
**H1. Zero-queue latency (random single-chain chase, transparent huge pages on).**
- L1 (16 KiB): **about 4 cycles** (3 to 5), i.e. about 1 ns at 4 GHz.
- L2 (256 KiB): **12 to 14 cycles**, about 3 ns.
- L3 (8 MiB): **about 46 to 55 cycles**, 10 to 14 ns (L3 is shared and virtualized; may read higher).
- DRAM (1 GiB): **80 to 140 ns** (a laptop LPDDR4x/DDR4 part plus VM overhead). Without huge pages (huge=0) DRAM latency is **20% to 80% higher** (nested page walks).
- *Wrong if:* L2 is outside 10 to 16 cycles, or DRAM is under 60 ns (the buffer is not really DRAM-resident, or a prefetcher is active) or over 250 ns.

**H2. Working-set sweep (random chase).** Steps near 32 KiB (L1 to L2), about 512 KiB (L2 to L3) and about 16 MiB (L3 to DRAM); each transition is smeared over about a factor of 2 in size (random placement), the L3 to DRAM step may start earlier than 16 MiB because the L3 is shared. Sequential chase (64 B nodes) is **at least 5x lower than random at DRAM size** (prefetchers), roughly 5 to 30 ns.

**H3. Pattern and granularity.**
- Random chase latency is flat across node granularity 64, 256, 1024 B (within 10%).
- Sequential chase latency rises with granularity: 64 B lowest (**under 20 ns**), 256 B **15 to 50 ns**, 1024 B **50% to 100% of random** (a 1024 B stride puts only 4 accesses in each 4 KiB page, so stream prefetch has little to train on).
- Single-thread bandwidth, 100% read: sequential 64 B stride **15 to 30 GB/s** (bounded by about 24 outstanding misses: 24 x 64 B / 100 ns is about 15 GB/s, prefetching lifts it); random **10 to 16 GB/s** (MLP-limited).
- Multi-thread (all 8 physical cores) sequential read: **65% to 90% of the theoretical peak** of the installed memory (about 33 to 46 GB/s for DDR4-3200).
- Useful bandwidth (64 B per touched line) at stride 256 B and 1024 B: **40% to 80%** and **20% to 60%** of the stride-64 value (DRAM row locality and prefetch accuracy fall).
- *Wrong if:* sequential chase at DRAM size is within 2x of random (the prefetcher is not engaging, or the buffer is small).

**H4. Read/write mix.** Counted bandwidth (64 B per operation, write-allocate fills not counted): write-only is **50% to 70%** of read-only (a written line costs a read-for-ownership plus a write-back); 70/30 and 50/50 lie between, monotonically. Latency seen by a probe under load rises with write share, **+10% to +50%** at 50/50 compared with 100% read at the same offered load.
*Wrong if:* write-only is as fast as read-only (the stores became non-temporal or the lines never left cache).

**H5. Throughput-latency tradeoff and Little's Law.**
- Probe latency stays within about 1.2x of its unloaded value up to roughly **60% to 70%** of the maximum bandwidth, then rises: **knee near 70% to 85% of maximum bandwidth**; at maximum load latency is **2x to 4x** unloaded for under 10% extra bandwidth.
- Lines in flight (bandwidth/64 x latency) at the knee is a **few tens** (about 40 to 120) and stays below 8 x 24 = 192 (the sum of per-core miss buffers).
- Single core, K independent chains: throughput grows about linearly with K up to **K of 12 to 16**, then flattens (miss-buffer limit near 22 to 24); plateau about 10 to 16 GB/s equivalent (K x 64 B / latency).
- *Wrong if:* the single-core curve is still linear at K = 16 (the miss limit is higher than assumed) or flattens below K = 6.

**H6. Cache-miss impact (counter-free).** Runtime per 64 B operation rises with footprint at the same capacities as H2; the miss fraction implied by measured AMAT matches the capacity model (1 - C_L3/W) **within +-25%** for working sets over 32 MiB and deviates smoothly near each capacity. If perf counters turn out to work, L1 misses per operation should be near 0 below 32 KiB and near 1 per line-touch (sequential: 1 per 64 B line) above it.

**H7. TLB reach (one node per 4 KiB page, random order).**
- 4 KiB pages: a step of about **+1.5 to 3 ns** (about 7 cycles) when pages exceed **64** (L1 DTLB), and a larger step of **+5 to 15 ns natively (up to +60 ns under nested paging)** beyond **2048** pages (L2 DTLB reach 8 MiB).
- With huge pages: no step at 64 or 2048 pages (64 x 2 MiB = 128 MiB; 2048 x 2 MiB = 4 GiB); difference to 4 KiB pages at 4096 or more pages **at least 20%**.
- Caveat built into the design: beyond about 8192 pages the touched lines (1 per page) no longer fit in L2, and near 262144 pages (16 MiB of lines) they approach the L3 edge, so the 4 KiB curve mixes TLB and cache effects; the huge-page curve at the same footprint is the control.
- *Wrong if:* the two curves coincide. That means huge pages were not applied: check `thp_kb > 0` in `data/raw/tlb.csv`.

**H8. Pitfalls (each is a demonstration, so I predict the size of the error).**
- Cache-resident buffer reported as DRAM bandwidth: 1 to 8 MiB buffers read **3x to 6x faster** than DRAM-sized ones; 32 MiB (over the L3) is close to DRAM.
- Unpinned runs: the median is similar; the spread (coefficient of variation) is **2x to 10x larger** and occasional runs are 20% to 50% slower. Under WSL2 "pinned" means a virtual CPU, so the difference may be small (I cannot predict this well).
- Sequential chase at DRAM size understates latency by **5x or more**.
- Power mode (optional repeat with `--tag`): core-clocked levels (L1, L2, L3) change in nanoseconds with the clock (**up to 1.5x to 2x**), DRAM latency changes **under about 15%**; cycle counts for L1/L2 stay roughly constant.

**H9. Cross-check.** The membw 70/30 sequential bandwidth is within **+-25%** of an independent STREAM-style triad at every thread count, and both saturate at about the same thread count (4 or more cores).

**H10. Measurement quality under WSL2.** Coefficient of variation: under 3% for cache-resident latency, 3% to 15% for DRAM-sized bandwidth and latency; multi-thread loaded-latency points are noisier (up to 20%).

## 2. Anomalies that might appear
THP not actually applied in the VM (`thp_kb` = 0), a shared/virtualized L3 smaller than 16 MiB, the clock estimators disagreeing, other Windows work stealing a vCPU during multi-thread runs, and Energy Saver changing the clock between experiments.

## 3. Resources
- https://en.wikipedia.org/wiki/Zen_3 (L2 512 KiB and 12 cycles, L3 46 cycles)
- https://courses.physics.illinois.edu/cs433/fa2022/projects/AMD-Zen.pdf (32 KiB 8-way L1, 24 outstanding misses, L1 DTLB 64, L2 DTLB 2048)
- https://7-cpu.com/cpu/Zen2.html and https://7-cpu.com/cpu/Zen.html (22 outstanding misses, 2 page walkers, 2.0 cycles per line L2 to L1, 2.65 to 2.7 cycles per line L3 to L1; Zen and Zen 2 measurements, not Zen 3)
- https://www.cpu-monkey.com/en/cpu-amd_ryzen_7_5825u and https://www.notebookcheck.net/AMD-Ryzen-7-5825U-Processor-Benchmarks-and-Specs.590117.0.html (memory support, 51.2 GB/s DDR4-3200 dual channel, 2.0 to 4.5 GHz)
