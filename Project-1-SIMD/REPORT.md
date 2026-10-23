# Project 1: SIMD Advantage Profiling on an AMD Ryzen 7 5825U (Zen 3, WSL2)

ECSE 4320/6320 Advanced Computer Systems, class-wide project 1
Companion files: [HYPOTHESES.md](HYPOTHESES.md), [RESULTS_TABLES.md](RESULTS_TABLES.md) (generated summary of raw measurements).

## Summary
On one Zen 3 core under WSL2, the compiler-targeted `native_fm` AVX2/FMA build speeds up f32 SAXPY by **7.1x** and multiply by **6.7x** in the 16 KiB sweep point; the fast-math dot reaches **8.7x**. The gain compresses toward 1x in DRAM as memory bandwidth dominates.
The dot product is the negative example: GCC reports vectorization, yet the strict build is about **1.0x** because additions stay in source order; allowing reassociation gives 8.7x in the f32 L1 sweep and 2.65x in DRAM.
**Code layout changed some results by up to 2x.** Two builds with identical SAXPY instructions differed by about 1.8x, and scalar f64 SAXPY ran about 2.0x slower than scalar f32 in the unaligned build. The loop-placement experiment reproduced these effects for selected loops; its impact was not uniform across every kernel or build:
- **f32 SAXPY `auto` vs `auto_al`:** 0.137 ns/elem as built (crosses 64B) vs **0.0857 ns/elem** aligned (1.60x speedup).
- **f32 SAXPY `native` vs `native_al`:** 0.0747 ns/elem (crosses 64B) vs **0.0422 ns/elem** aligned (1.77x speedup).
- **f64 SAXPY `scalar` vs `scalar_al`:** 0.550 ns/elem (crosses 64B) vs **0.275 ns/elem** aligned (2.00x speedup). Controlling placement adjusts the measured f64 SAXPY SIMD gain from 6.17x as built down to 3.60x aligned—exactly matching the theoretical ~3.5x lane-count limit.
- **f32 Stride `auto` vs `auto_al`:** 0.138 ns/elem as built (crosses 64B) vs **0.0849 ns/elem** aligned (1.63x speedup).
- **f32 Stencil `auto` vs `auto_al`:** 0.205 ns/elem as built vs **0.161 ns/elem** aligned (1.27x speedup).
The retained peak run measured **109.91 GFLOP/s** (f32) and **55.10 GFLOP/s** (f64); with the processed 28.32 GB/s stream this gives a ridge point of **3.88 FLOP/B**. The detailed roofline values below use these current inputs.
Alignment effects were smaller and less regular than predicted, tails cost a few cycles per call, and stride and gather are not helped by SIMD in DRAM. No hardware counters were available.

## 1. Introduction
A programmer who vectorizes a loop expects a speedup close to the lane count (8 for f32 with AVX2, 4 for f64). This study measures how much of that survives on one core for four simple kernels and why: working-set size (L1 to DRAM), arithmetic intensity,
loop-carried dependences, alignment, stride, data type, and even where the compiler happens to place the loop.
*Background used.* Arithmetic intensity (AI) is FLOP per byte moved; a roofline bounds performance by min(peak FLOP rate, AI x bandwidth); the ridge point (peak/bandwidth) separates memory-bound from compute-bound kernels.
Floating-point addition is not associative, so a compiler may not reorder a strict sum; a strictly ordered reduction is a chain of dependent adds whose speed is set by add latency, not by vector width.

## 2. Platform and methodology
Table 1. Platform and measurement settings (from `env/simd_env.txt`).

| item | setting |
|---|---|
| CPU | AMD Ryzen 7 5825U with Radeon Graphics (family 25, model 80: Zen 3), 8 cores / 16 threads, BogoMIPS 3992. AMD's [official specifications](https://www.amd.com/en/support/downloads/drivers.html/processors/ryzen/ryzen-5000-series/amd-ryzen-7-5825u.html) list the same core/thread count and Zen 3 architecture. |
| ISA used | SSE2 (`auto`), AVX2 + FMA (`native`); no AVX-512 |
| Caches (`lscpu`) | L1D 32 KiB/core, L2 512 KiB/core, L3 16 MiB shared |
| Host Memory | 16 GB Dual-Channel DDR4-3200 (2 x 8GB SODIMM, Channel A + B); 7.4 GiB visible inside WSL2 |
| OS / Host | Windows 11 Home/Pro Version 26H2 (Build 26300.9711) hosting WSL2, kernel 6.6.87.2-microsoft-standard-WSL2, Ubuntu 24.04.4 LTS |
| Tools | GCC 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1), Python 3.12.3, pandas 2.1.4, matplotlib 3.6.3, numpy 1.26.4 |
| Frequency policy | Windows power mode **Best performance**, **Energy Saver OFF**. AC power is recorded. Guest exposes no cpufreq governor. Clock inferred at ~3.9 to 4.2 GHz |
| SMT | enabled; pinned with `taskset -c 2`; CPU 3 is SMT sibling (`lscpu -p`) and left idle |
| Counters | none: `perf` unavailable under WSL2 kernel |
| Timing | `clock_gettime(CLOCK_MONOTONIC_RAW)` and `rdtsc` (TSC frequency taken as BogoMIPS/2 = 1.996 GHz) |
| Repetitions | 11 per point, median with standard deviation error bars |

Table 2. Builds.

| build | flags | role |
|---|---|---|
| `scalar` | `-O3 -fno-tree-vectorize -fno-tree-slp-vectorize` | scalar baseline (x86-64 baseline ISA, no FMA) |
| `auto` | `-O3` | default auto-vectorization (128-bit SSE2) |
| `native` | `-O3 -march=native` | AVX2 + FMA, strict FP semantics |
| `native_fm` | `-O3 -march=native -ffast-math` | allows reassociation |
| `*_al` (new) | same flags plus `-falign-loops=64` | loop-placement test (5.7c) |

**Timing method.** Each process (1) checks the kernel against a plain `-O0` double-precision reference on 20,001 elements (odd length, so the tail path runs) with the same offsets and strides, aborting on failure (tolerances 2e-5 f32, 1e-12 f64; dot 2e-3 and 1e-9 because summation order differs);
(2) touches all arrays; (3) calls the kernel once to warm up and once to calibrate an inner loop of about 20 ms; (4) times 11 repetitions. Each call is `noinline` and followed by a memory-clobber barrier, with results accumulated in a `volatile` sink, so a pure `dot` call cannot be hoisted. All runs passed the correctness check (the sweep aborts otherwise).
**Regimes.** Tables use the sweep point nearest to 16 KiB (L1), 256 KiB (L2), 8 MiB (L3) and the largest point (128-384 MiB depending on kernel and type) for DRAM. The working set counts all arrays. The sweep has 33 sizes from 2^9 to 2^24 elements.
**Variability** (all sweep points, std/median over 11 repetitions): median 2.4% at or below 32 KiB, 2.5% from 32 KiB to 16 MiB, 5.4% from 16 to 64 MiB, 4.2% above 64 MiB; 90th percentile 10% to 13%; isolated outliers up to 220%. Single-cell differences below about 10% should not be interpreted.
**Known limits:** nominal bytes (no write-allocate traffic), TSC (reference) cycles, one machine and session.

## 3. Hypotheses
Predictions are in [HYPOTHESES.md](HYPOTHESES.md). Comparisons are presented in Section 6.

## 4. Vectorization verification
GCC loop reports (`-fopt-info-vec-all`, `reports/vec_all_*.txt`) and `objdump` (`reports/vec_counts.csv`, `reports/disasm_*.txt`). A "vectorized" verdict only says that *some* loop version was vectorized; instruction inspection decides what runs.

Table 3. GCC verdict per kernel and build.

| kernel | dtype | scalar | auto | native | native_fm |
|---|---|---|---|---|---|
| dot | f32 | no | yes, 16 B | yes, 32 B | yes, 32 B |
| dot | f64 | no | yes, 16 B | yes, 32 B | yes, 32 B |
| gather | f32 | no | yes, 16 B | yes, 32 B | yes, 32 B |
| gather | f64 | no | yes, 16 B | yes, 32 B | yes, 32 B |
| mul | f32 | no | yes, 16 B | yes, 32 B | yes, 32 B |
| mul | f64 | no | yes, 16 B | yes, 32 B | yes, 32 B |
| saxpy | f32 | no | yes, 16 B | yes, 32 B | yes, 32 B |
| saxpy | f64 | no | yes, 16 B | yes, 32 B | yes, 32 B |
| stencil | f32 | no | yes, 16 B | yes, 32 B | yes, 32 B |
| stencil | f64 | no | yes, 16 B | yes, 32 B | yes, 32 B |
| stride | f32 | no | yes, 16 B | yes, 32 B | yes, 32 B |
| stride | f64 | no | yes, 16 B | yes, 32 B | yes, 32 B |

Table 4. Instruction counts inside each kernel function (whole function, including remainder and scalar paths).

| variant | function | instr | packed FP | ymm | packed xmm | FMA |
|---|---|---|---|---|---|---|
| auto | dot_f32 | 56 | 7 | 0 | 8 | 0 |
| native | dot_f32 | 83 | 13 | 3 | 14 | 3 |
| native_fm | dot_f32 | 74 | 19 | 4 | 16 | 4 |
| scalar | dot_f32 | 19 | 2 | 0 | 2 | 0 |
| auto | mul_f32 | 39 | 6 | 0 | 6 | 0 |
| native | mul_f32 | 59 | 6 | 3 | 3 | 0 |
| native_fm | mul_f32 | 59 | 6 | 3 | 3 | 0 |
| scalar | mul_f32 | 13 | 0 | 0 | 0 | 0 |
| auto | saxpy_f32 | 49 | 12 | 0 | 12 | 0 |
| native | saxpy_f32 | 66 | 7 | 4 | 4 | 5 |
| native_fm | saxpy_f32 | 66 | 7 | 4 | 4 | 5 |
| scalar | saxpy_f32 | 14 | 0 | 0 | 0 | 0 |

**SAXPY (`reports/disasm_saxpy_f32_native.txt`).** The `native` main loop is six instructions for eight floats: `vmovups (x)`, `vfmadd213ps (y)` (fused multiply-add with a memory operand), `vmovups` store, and loop control. It is **not unrolled** and has **no alignment prologue** (unaligned `vmovups`).
For N of 7 or fewer the loop is skipped (`cmp $0x6`); a 128-bit step handles a remainder of 4 to 7, then a scalar epilogue handles the last 1 to 3 elements. `native` and `native_fm` have identical SAXPY instruction streams (`diff` of the two functions is empty apart from addresses): `-ffast-math` changes nothing for SAXPY.
**Dot product, strict (`reports/disasm_dot_f32_native_strict.txt`).** One `vmulps` per eight elements, then the product vector is taken apart with `vshufps`, `vunpckhps`, `vextractf128` and added into one scalar register with **eight dependent `vaddss`** per trip (3750 to 37a3).
So only the multiply is vector code; the sum is a serial chain of 8 adds per 8 elements.
**Dot product, fast-math (`reports/disasm_dot_f32_native_fastmath.txt`).** Loop at 3aa0 to 3ab5: `vmovups`, `vmulps (mem)`, **`vaddps %ymm0,%ymm1,%ymm1`** (one 8-lane accumulator), `cmp`, `jne`; a horizontal reduction follows the loop. GCC chose separate `vmulps` + `vaddps` rather than `vfmadd231ps` in the loop.
With a single accumulator the loop-carried dependence is one `vaddps` per trip. *Hypothesis (untested):* GCC's Zen tuning avoids FMA in reduction chains because FADD latency (about 3 cycles) is below FMA latency (about 4).
For the `scalar` build the strict loop is `mulss/addss` with a single accumulator.
**Stride and gather.** The loop report says "vectorized" for `stride` and `gather`; for `stride` the same report contains "not vectorized: no vectype for stmt", so the verdict refers to a unit-stride version of the loop. No hardware gather is used: `objdump` finds **0** `vgather*` instructions in the `gather` kernels of both `native` and `native_fm`.

## 5. Results
All "as built" numbers come from the main sweeps, whose binaries were built without loop alignment; Table 7 in section 5.1 gives the placement-controlled values for SAXPY, multiply and dot.
### 5.1 Scalar vs auto-vectorized, all kernels
*Question.* How close does SIMD get to the lane count, per kernel, type and working-set regime? *Expectation (H1, H3).* f32 SAXPY, multiply, stencil 4x to 8x in L1 with `native`; `auto` 2x to 4x; f64 about half; strict dot about 1x, fast-math dot 5x to 8x.
*Method.* 33-point sweep, four builds, four kernels, two types. Speedup is scalar time over variant time at the same N.

Table 5. Speedup over `scalar` (`auto` / `native` / `native_fm`), f32.

| kernel | L1 (16 KiB) | L2 (256 KiB) | L3 (8 MiB) | DRAM (largest) |
|---|---|---|---|---|
| saxpy | 1.89 / 3.72 / 7.14 | 2.43 / 4.94 / 5.09 | 2.18 / 3.31 / 3.50 | 1.20 / 1.27 / 1.27 |
| mul | 3.74 / 6.74 / 6.66 | 3.28 / 3.40 / 3.69 | 2.52 / 2.48 / 2.56 | 1.09 / 1.06 / 1.04 |
| dot | 1.00 / 1.02 / 8.65 | 1.03 / 0.96 / 7.76 | 1.02 / 1.07 / 7.28 | 1.05 / 1.03 / 2.65 |
| stencil | 2.58 / 6.07 / 5.63 | 2.80 / 4.29 / 4.21 | 2.79 / 3.92 / 3.94 | 1.12 / 1.24 / 1.20 |

Table 6. Same, f64.

| kernel | L1 (16 KiB) | L2 (256 KiB) | L3 (8 MiB) | DRAM (largest) |
|---|---|---|---|---|
| saxpy | 1.98 / 7.19 / 7.15 | 2.01 / 3.86 / 3.83 | 1.86 / 2.97 / 2.97 | 1.04 / 1.17 / 1.16 |
| mul | 1.94 / 3.61 / 3.60 | 1.78 / 2.05 / 1.91 | 1.45 / 1.43 / 1.35 | 0.99 / 1.03 / 1.00 |
| dot | 0.99 / 1.03 / 3.93 | 0.99 / 0.98 / 3.41 | 1.00 / 0.92 / 3.36 | 1.01 / 1.04 / 1.50 |
| stencil | 1.89 / 3.40 / 3.42 | 1.80 / 2.52 / 2.50 | 1.72 / 2.14 / 2.14 | 1.07 / 1.11 / 1.03 |

Figures: `plots/e1_sweep_f32.png`, `plots/e1_sweep_f64.png` (one color per build in both rows).
*Result.* In the current L1 sweep, the fastest f32 builds reach **7.14x (SAXPY), 6.66x (multiply), and 5.63x (stencil)**; fast-math dot reaches **8.65x**. The 128-bit `auto` gains range from about 1.0x for strict dot to 3.7x for multiply. The strict dot remains close to 1x across regimes and types; f32 `native` in DRAM is 1.03x, within the variability. In f64, fast-math dot reaches 3.93x in L1; multiply and stencil reach about 3.6x and 3.4x. As-built SAXPY f64 also reports 7.15x, but the independent loop-placement check shows this is not a lane-count result: its aligned speedup is 3.6x (Table 7).
Table 7. Speedup over scalar at N = 1024 (L1-resident), as built and with every loop padded to a 64-byte boundary (`-falign-loops=64`, builds `*_al`); median of 11 repetitions (RESULTS_TABLES section 11c, figure `plots/e8_loop_placement.png`).
Each aligned speedup divides `scalar_al` by the aligned vector build.

| kernel | type | as built: native / native_fm | aligned loops: native_al / native_fm_al | scalar vs scalar_al (ns per element) |
|---|---|---|---|---|
| saxpy | f32 | 3.83 / 7.11 | 6.57 / 6.52 | 0.269 vs 0.256 |
| saxpy | f64 | 7.31 / 7.36 | 3.63 / 3.62 | 0.531 vs 0.258 |
| mul | f32 | 5.82 / 6.96 | 6.51 / 6.97 | 0.265 vs 0.268 |
| mul | f64 | 3.66 / 3.74 | 3.54 / 3.52 | 0.265 vs 0.258 |
| dot | f32 | 1.04 / 10.14 | 1.01 / 9.92 | 0.743 vs 0.725 |
| dot | f64 | 1.01 / 4.02 | 1.03 / 4.44 | 0.727 vs 0.735 |

The independent as-built numbers at N = 1024 are in the same range as the current sweep (SAXPY f32 `native` 3.83x vs 3.72x, `native_fm` 7.11x vs 7.14x). The N=1024 multiply f32 `native` cell (5.82x as built) is noisy (repetitions from 0.038 to 0.068 ns per element); compare it with the current sweep (6.74x) and aligned value (6.51x). Section 5.7c discusses the placement evidence.
*Effective clock.* Because the guest hides the clock, two latency-bound loops give a consistency check (RESULTS_TABLES section 10): the strict scalar dot chain (assumed 3 cycles per add) implies about **4.0 GHz**, the single-accumulator fast-math dot (assumed 3 cycles per 8 elements) about **4.5 GHz**.
Both are plausible for this part's boost range and suggest that Energy Saver did not pin the clock low during these loops; this is an inference, not a measurement.
*Explanation.* In L1 SAXPY `native_fm` takes 0.0684 TSC cycles per element; at about 4.0 to 4.5 GHz that is **1.1 to 1.2 core cycles per eight-element loop trip**, close to one trip per cycle, which fits a store-port limit of one 256-bit store per cycle (*hypothesis*, no counters; test: a load-only and a store-only variant).
The fast-math dot gains slightly more than the lane count (8.65x in the current f32 sweep) because the scalar baseline is latency-bound at about 3.3 cycles per element while the vector loop needs about 3 cycles per 8 elements. The strict dot gains nothing because both builds execute the same chain of dependent adds (Table 3 and section 4).
*Implication.* Quote SIMD speedups per regime and state the scalar baseline's cycles per element; lane count predicts the gain only when the scalar loop leaves most of the load/store capability idle.

### 5.2 Locality sweep (SAXPY f32)
*Question.* Where does the SIMD gain compress and why? *Expectation (H2).* Steps at 32 KiB, 512 KiB and about 16 MiB; speedup about 2x to 3x in L2, 1.3x to 2.5x in L3, 1.0x to 1.3x in DRAM; DRAM SAXPY 2.5 to 5 GFLOP/s.
*Result* (`native_fm`, `plots/e2_locality_saxpy.png`): current processed data give 52.8 GFLOP/s at 16 KiB, 37.0 at 32 KiB, about 28 at 256 KiB, 21.0 at 8 MiB, 15.2 at 11.3 MiB, 8.0 at 16 MiB, and 3.1 at 64 MiB. The largest measured point is 128 MiB at 2.8 GFLOP/s.
The speedup over scalar is 7.14x at the L1 target, 5.09x at 256 KiB, 3.50x at 8 MiB, and 1.27x at the largest point. The scalar throughput falls from 7.39 to 2.19 GFLOP/s across those points. At the largest point, vectorized SAXPY reaches about 2.8 GFLOP/s, or 15.6 GiB/s of nominal traffic.
*Explanation.* The vector loop is faster than each lower level can feed it. In L2 the loop takes 0.131 TSC cycles per element, about 2.1 to 2.4 core cycles per trip (4.0 to 4.5 GHz); the trip needs 64 B of fills (x and y), so that is about 27 to 30 B per core cycle of fill traffic, near a 32 B/cycle L2 fill rate (*hypothesis, not tested*; write-backs seem to overlap, because my prediction of 2x to 3x assumed they did not).
In DRAM the nominal 12 B per element understates traffic: if write-allocate adds a 4 B line-fill share, estimated traffic becomes 16 B per element. That raises the largest-point estimate from 15.6 GiB/s nominal to about **20.8 GiB/s**, below the measured 28.3 GB/s read stream. This traffic estimate is not directly measured; the near-1x SIMD gain at the largest point is consistent with a bandwidth limit but does not prove the exact traffic mix.
*Implication.* Beyond L1, blocking for L2 or L3 will not rescue a streaming loop on one core; reduce bytes per element or add cores.

### 5.3 Alignment and tail handling
*Question.* What do misaligned starts and short or ragged loops cost? *Expectation (H4, H5).* No penalty at 0 and 32 B; 10% to 50% at other offsets in L1/L2, under 5% in DRAM; scalar unaffected. Tail: fixed cost 10 to 30 cycles and a visible N mod 8 sawtooth.
*Method.* SAXPY and multiply f32 at N = 2048 (L1) and 2^22 (DRAM) with (x, y) offsets in bytes; tails for N = 3 to 72 and N = 4096 + r (r = 0 to 15). Offsets are applied to x and y only; the output array of multiply stays at offset 0.
*Result, L1, SAXPY `native` (time relative to (0,0); `plots/e3_alignment.png`, RESULTS_TABLES section 2).* y only shifted: 4 B **1.19**, 8 B 1.09, 16 B 1.08, 32 B 1.04, 60 B 1.09; both shifted equally: **0.93 to 0.97** (slightly *faster*). Multiply (output unshifted): y only shifted **1.35** at 4, 8, 16 and **32** B, 1.44 at 60 B; both shifted equally 1.46 to 1.49 at 4, 8, 16, 60 B but **0.99 at 32 B**. The `scalar` build stays within 0.98 to 1.07.
*Result, DRAM, SAXPY `native`.* y only shifted 0.99 to 1.11 (no clear penalty). Both shifted: (32,32) 0.97; (16,16) **1.34** with stable repetitions; (4,4) median 1.43 but 11 repetitions range 0.62 to 1.50 ns/element; (8,8) median 2.07 but the repetitions are **non-stationary** (first four 0.63 to 0.72 ns, then 1.03 to 1.48 ns), which looks like external interference, not alignment.
Multiply in DRAM is 0.85 to 0.96 of the aligned case for every offset. The scalar control varies 0.87 to 1.18 in DRAM, so DRAM cells carry about 10% to 20% noise.
*Result, tails (`plots/e3_tail.png`).* Affine fit over N = 32 to 72: `native` 0.064 ns per element plus **1.86 ns** per call (about 8 cycles at 4 to 4.5 GHz), `auto` 0.144 ns + 0.97 ns, `scalar` 0.299 ns + 1.20 ns; residual standard deviation 0.26 ns (`native`), 0.30 ns (`auto`), 1.23 ns (`scalar`).
For N = 1 to 16 the cost is 0.46 to 2.37 TSC cycles per element for `native` against 0.13 for long loops (3.6x to 18x). For N = 4096 + r the time spread across r is 8.7% (`native`), 10.7% (`auto`), 9.4% (`scalar`) with **no pattern in r** (e.g. `native` 283 ns median; r = 0 and r = 7 are equal within noise).
*Explanation.* The predicted line-split story is only partly supported: it cannot explain the 35% penalty at y offset 32 B for multiply (all accesses 32 B-aligned, none crossing a line), nor the absence of any penalty when x and y are shifted together in SAXPY. The data suggest that the **relative** offsets between streams matter, not only each stream's own alignment.
*Hypothesis (untested):* the effect comes from how loads and stores of different streams interact (memory disambiguation or bank/port conflicts) rather than from line splits; test: load-only and store-only microbenchmarks over a grid of relative offsets, or hardware counters on a native Linux machine.
Tails: the fixed cost is lower than predicted (about 4 to 8 cycles, not 10 to 30), the remainder loops are invisible (the 128-bit step and scalar epilogue cost less than the noise), and no sawtooth appears; with about 1 ns timer and scheduling noise a sawtooth of a few cycles could be hidden, so "not observed" is the correct claim, not "does not exist".
The single spike in `auto` at N = 21 (0.46 ns/element against about 0.2 for neighbors) is an unexplained outlier.
*Implication.* Align *all* streams identically (and to 32 B), keep the stored array consistent with the loaded ones, and do not tune for remainders; but verify on the target machine, because the sign of the effect varied between kernels.

### 5.4 Stride and gather
*Question.* How do non-unit stride and random gather change SIMD gain and useful bandwidth? *Expectation (H6).* `native` about 1.0x over `scalar` at strides 2 to 16; DRAM time per element about 2x, 4x, 6 to 8x, 8 to 16x at strides 2, 4, 8, 16; gather 0.8x to 1.5x, under 3 GB/s in DRAM.
*Method.* SAXPY with stride 1, 2, 4, 8, 16 and random gather, N = 4096 and 2^22. Note that the **footprint grows with stride**: at N = 4096 f32 it goes from 32 KiB (stride 1) to 512 KiB (stride 16), so the "cache" series crosses from L1 to L2.
*Result (`plots/e4_stride_gather.png`, RESULTS_TABLES section 4), f32, DRAM-size N = 2^22, `native`:* time per element 0.564 ns (stride 1), then **3.3x, 5.0x, 9.1x, 18x** longer at strides 2, 4, 8, 16 (useful bandwidth 19.8, 6.0, 3.9, 2.2, 1.1 GiB/s); `scalar`: 1.8x, 3.3x, 6.4x, 18.8x. Gather: 1.84 GiB/s (`native`), 1.76 GiB/s (`scalar`).
f64 (DRAM): `native` time per element is 16.55 ns at stride 8 and 16.53 ns at stride 16: the curve **flattens at 8 doubles = one 64 B line**. In cache (N = 4096, f32) `native` falls from 229 GiB/s at stride 1 to about 19 GiB/s at strides 2 to 8 and 8.9 GiB/s at stride 16.
`native` over `scalar` at strides 2 to 16 ranges from **0.57x to 1.43x** (f32 L1: 0.57x, 0.65x, 0.97x, 1.0x; f32 DRAM: 0.74x, 0.91x, 0.96x, 1.43x; f64 L1: 1.30x, 1.15x, 0.97x, 1.0x), not a clean 1.0x. Gather: **2.05x** (f32) and 1.6x (f64) faster than scalar in cache, **1.05x** and 1.12x in DRAM.
*Explanation.* The 12x drop in cache from stride 1 to 2 is mostly *code*, not memory: only the unit-stride version is vectorized, so the strided path runs scalar. In DRAM the time per element is set by cache-line traffic: the plateau at stride 8 for f64 confirms the line size. The f32 plateau (stride 16) is not reached in the sweep (strides stop at 16).
In cache `native` is slower than `scalar` at strides 2 and 4 (0.57x to 0.65x for f32) and faster for f64 (1.15x to 1.30x). The compiled loops show a matching difference in placement (RESULTS_TABLES section 11d): the scalar strided loop of the f32 `native` kernel (0x3af0, 7 instructions) straddles a 64 B boundary while the f32 `scalar` loops do not,
and in f64 it is the `scalar` loop (0x3930) that straddles one while the f64 `native` loops do not. The direction of both differences is what the loop-placement result of 5.7c predicts, but the stride experiment was **not** re-run with aligned builds, so this is a consistent observation, not a confirmed cause (anomaly 5 in 5.8).
Gather gains in cache because GCC vectorizes the multiply-add and fills the vector with element-wise loads (no hardware gather is used: 0 `vgather*` instructions in the compiled kernels); in DRAM latency and line traffic dominate and the gain vanishes. Gather useful bandwidth of 1.8 to 2.9 GiB/s matches the prediction (under about 3 GB/s).
*Implication.* Strided and random access forfeit SIMD and, in DRAM, most bandwidth; restructure data (structure of arrays, blocking).

### 5.5 Data type
*Question.* How do f32 and f64 differ? *Expectation (H7).* f64 in-cache gain about half; in DRAM the same gain; arithmetic intensity halves.
*Result (Tables 5 to 7, `plots/e5_dtype.png`).* Current L1 `native_fm` speedups for f32 versus f64 are SAXPY 7.14x vs 7.15x, multiply 6.66x vs 3.60x, dot 8.65x vs 3.93x, and stencil 5.63x vs 3.42x. With loops aligned (Table 7), the lane-count effect is clearer for SAXPY and multiply. In DRAM, current speedups are close to 1x for most kernels and types; fast-math dot is 2.65x for f32 and 1.50x for f64.
For L1 SAXPY, f64 reaches about half the f32 FLOP/s (27.0 vs 52.8 GFLOP/s in the current sweep).
*Explanation.* Lanes (8 vs 4) and bytes per element (4 vs 8; the arithmetic intensity of SAXPY is 0.167 vs 0.083 FLOP/B) explain the factor of two. The **as-built SAXPY exception (7.0x in f64)** was a placement artifact: the f64 scalar baseline was 2.15x slower per element than f32 (1.05 vs 0.489 TSC cycles) because its loop straddles a 64 B boundary, and after alignment the scalar f64 and f32 SAXPY costs are equal (0.258 vs 0.256 ns per element) and the f64 gain falls to half of f32's (5.7c).
In DRAM both types are limited by bytes per second, so gains are similar for SAXPY and the stencil but not for the dot product, whose scalar baseline is latency-bound.

### 5.6 Roofline
*Question.* Which kernels are memory-bound and which compute-bound, at L1 and in DRAM? *Expectation (H8).* Measured f32 peak at least 85% of 32 FLOP/cycle x clock; ridge point about 3 to 6 FLOP/B; all kernels memory-bound beyond L2 and load/store-bound in L1; L1 SAXPY at 40% to 60% of peak; the best DRAM kernel at 70% to 100% of the bandwidth roof.
*Method.* Compute peak: `build/peak_flops` (v2), 8, 10 and 12 independent AVX2 FMA chains held in registers (disassembly checked: register-only `vfmadd` in the loop), best of 3 runs, one thread (`data/raw/peak.csv`). Bandwidth: best single-thread read stream at DRAM size, `dot native_fm` (8 B per element), 28.32 GB/s in the processed inputs.
Arithmetic intensity (nominal, f32): SAXPY 2/12 = 0.167, multiply 1/12 = 0.083, dot 2/8 = 0.25, stencil 5/8 = 0.625 FLOP/B. L1 points use the sweep point nearest 16 KiB, DRAM points the largest working sets.
*Result.* **f32 peak 109.91 GFLOP/s (12 chains), f64 55.10 GFLOP/s (ratio 0.501).** At the assumed 32 FLOP/cycle (two 256-bit FMA pipes, 8 lanes, 2 FLOP), the f32 result corresponds to 3.43 GHz. This is 14% to 24% below the 4.0 to 4.5 GHz inferred from the dot loops; the actual clock and sustained FMA issue rate were not measured. The peak is about 86% of the 4.0 GHz theoretical rate and 76% of the 4.5 GHz rate.
Ridge point = 109.91 / 28.32 = **3.88 FLOP/B**. (The first measurement, 27.8 GFLOP/s, was invalid; Appendix D.)

Table 8. Roofline coordinates, f32 `native_fm` (RESULTS_TABLES section 7; figure `plots/e7_roofline.png`: filled markers DRAM, hollow L1).

| kernel | AI (FLOP/B) | GFLOP/s, L1 | % of peak, L1 | GFLOP/s, DRAM | roof at AI (GFLOP/s) | % of roof, DRAM |
|---|---|---|---|---|---|---|
| saxpy | 0.167 | 52.8 | 48.0 | 2.77 | 4.72 | 58.7 |
| mul | 0.083 | 23.6 | 21.4 | 1.12 | 2.36 | 47.4 |
| dot (fast-math) | 0.25 | 22.6 | 20.5 | 6.30 | 7.08 | 89.1 |
| stencil | 0.625 | 57.2 | 52.0 | 7.78 | 17.7 | 44.0 |

*Explanation.* Every kernel has intensity below the ridge point. The DRAM points reach 89% of the nominal roof for dot, 59% for SAXPY, 47% for multiply, and 44% for stencil. The write-kernel roofs are optimistic because nominal byte counts omit write-allocate traffic.
At the L1 target, SAXPY and multiply reach 48% and 21% of the measured FMA peak. A one-256-bit-store-per-cycle limit is a plausible explanation, but is not verified without counters. Fast-math dot is 21% of peak and has a dependent vector-add chain; stencil reaches 52%. These ratios compare separate runs and the effective clock varied, so they are approximate.
*Implication.* Under this roofline, optimizing arithmetic does nothing for SAXPY, multiply or the stencil beyond L1; reduce bytes per FLOP or use more cores. The strict reduction is a latency problem, not a bandwidth or compute problem.

### 5.7 Negative and misleading examples
**(a) Strict dot product: "vectorized" but not faster.** GCC reports the loop as vectorized for all three SIMD builds, yet speedups remain about 1.0x. Evidence: `vmulps` followed by eight serial `vaddss` per trip (section 4); about 1.5 TSC cycles (about 3 core cycles) per element at every size. Allowing reassociation (`native_fm`) gives 8.65x in the current f32 L1 sweep.
**(b) SAXPY in DRAM: vectorized but memory-bound.** The vector loop is the same code as in L1 (about 7x there) yet gains only 1.2x to 1.3x at the largest 128 MiB working-set point because bandwidth limits it (5.2).
**(c) The same machine code, two speeds (code placement).**
*Observation.* `native` and `native_fm` contain **identical SAXPY f32 instruction streams** (`diff` of the two functions is empty apart from addresses), yet in the current L1 sweep their speedups are 3.72x and 7.14x (27.5 vs 52.8 GFLOP/s). The independent N=1024 run also shows a large difference (Table 7); after loop alignment, the two vector builds agree, consistent with a code-placement effect.
A careless study would conclude that "-ffast-math doubles SAXPY speed". Also the scalar f64 SAXPY ran 2.15x slower per element than scalar f32. The loop addresses (`reports/loop_alignment.csv`) show that the slow loops straddle a 64-byte boundary (`native` f32 0x3530 to 0x3548, scalar f64 0x3770 to 0x378b) and the fast ones do not (`native_fm` f32 0x3890 to 0x38a8, scalar f32 0x3490 to 0x34ab).
*Hypothesis and prediction (written before the test).* A loop body that crosses a 64 B boundary needs two fetch/op-cache windows per trip, doubling the time of a one-trip-per-cycle loop. If so, padding every loop to 64 B should make `native`, `native_al` and `native_fm_al` agree for f32 SAXPY (about 7x) and speed up the scalar f64 SAXPY by about 2x (its SIMD gain falling toward 3.5x).
*Test.* Same source and flags, plus `-falign-loops=64` across all variant families (`auto_al`, `scalar_al`, `native_al`, `native_fm_al`) for all five kernels (`saxpy`, `mul`, `dot`, `stencil`, `stride`), N = 1024, 11 repetitions (Table 7, `plots/e8_loop_placement.png`, RESULTS_TABLES sections 11a to 11c).
*Result.* **The prediction held for selected loops, but the effect was not uniform across all kernels.**
- f32 SAXPY `native`: 0.0747 ns per element as built, **0.0422** aligned (1.77x faster); `native_fm`: 0.0411 as built, **0.0425** aligned; so both vector builds agree and give ~6.2x to 6.6x over scalar.
- f32 SAXPY `auto`: 0.137 ns per element as built (crosses 64B) vs **0.0857 ns** aligned (1.60x speedup).
- f32 Stride `auto`: 0.138 ns per element as built (crosses 64B) vs **0.0849 ns** aligned (1.63x speedup).
- Scalar f64 SAXPY: 0.550 ns as built, **0.275** aligned (2.00x faster), now equal to scalar f32 (0.264 ns); the f64 SIMD gain falls from 6.17x to **3.60x**, half of f32's, as lane count predicts.
Loops that were already inside one 64 B window, or that are latency-bound, did not change significantly: f64 `native`/`native_fm` SAXPY (0.076/0.081 ns aligned), multiply (within 3% except minor noise), strict dot (within 3%), f32 fast-math dot (0.0764 ns aligned).
*What this does and does not show.* The results support a code-placement effect for the identified loops: the aligned builds change timing where loop addresses change, and selected vector builds converge after alignment. The *mechanism* (two fetch/op-cache windows) remains a hypothesis: there are no counters, and `-falign-loops=64` moves every loop, so placement is not isolated to one loop.
One effect is not explained: f64 fast-math dot is ~11% faster aligned (0.199 as built vs 0.177 ns aligned) although that loop is latency-bound.
*Implication.* Check loop placement (or align loops) before comparing builds or reporting a SIMD speedup: as-built numbers can be wrong by 2x in either direction without any change in the instructions.

### 5.8 Anomalies and unresolved items
Each item gives the observation, what is known, and a test.
1. **Loop placement (5.7c): effect reproduced for selected loops.** Padding to 64 B removes the large speed differences for selected SAXPY and stride cases, but is not a uniform speedup across every kernel. The fetch/op-cache explanation remains a hypothesis; test it with counters or identical code placed at controlled offsets.
2. **Invalid first FMA peak (5.6):** The first `peak_flops` kept accumulators in memory and reported 27.8 GFLOP/s; the retained corrected run reports 109.91 GFLOP/s (f32) / 55.10 GFLOP/s (f64) (Appendix D).
3. **Alignment (5.3):** The penalty depends on the kernel and on relative offsets; the cache-line-split explanation fails at (0, 32) for multiply. All offsets of one kernel run in the same binary, so code placement cannot explain differences between offsets. Test: relative-offset grid with load-only and store-only loops, or counters.
4. **Non-stationary DRAM cell:** SAXPY (8, 8) at 2^22 changes level within one run (0.63 to 0.72 ns, then 1.03 to 1.48 ns); probably external interference under WSL2. Test: repeat on a quiet machine with interleaved configurations.
5. **Strided `native` slower than `scalar` in cache (5.4): partially explained by placement.** The N=1024 aligned comparison improves selected SIMD results, but the stride sweep itself was not repeated for all working sets with aligned binaries; treat placement as a plausible contributor, not a fully isolated cause.
6. **Small L2 step (5.2):** Only a 15% step at 512 KiB, then a gradual decline to the L3 edge; possibly prefetching hides L3 latency. Test: a pointer-chase latency curve (Project 2).
7. **Two clock estimates disagree (5.1, 5.6):** The dot loops imply 4.0 to 4.5 GHz; the FMA peak implies about 3.43 GHz if the loop sustains 32 FLOP/cycle (14% to 24% lower). Possible causes include a different clock between programs, a lower sustained FMA issue rate, or an inaccurate assumed FADD latency. Test: repeat both in one session and measure the FMA issue rate independently.
8. **f64 fast-math dot 11% faster when aligned (5.7c):**, mechanism unknown for a latency-bound loop.
9. **Outliers:** dot f64 `native` L1 relative error 102%, a spike at N = 21 for `auto`, an error bar over 20x for multiply f32 near 32 KiB: isolated bad repetitions (WSL2 scheduling); medians are used.

## 6. Expectations against outcomes
| topic | expected (HYPOTHESES.md) | observed | verdict |
|---|---|---|---|
| L1 f32 gain, `native`: SAXPY / multiply / stencil | 4x to 8x | current sweep 3.72x / 6.74x / 6.07x; aligned SAXPY 6.57x, multiply 6.51x | matched for two; SAXPY improves with alignment |
| `auto` gain in L1 | 2x to 4x | 1.89x, 3.74x, 2.58x for SAXPY, multiply, stencil | partly matched; SAXPY slightly under |
| f64 gain in L1 | about half of f32 | multiply 3.61x, stencil 3.40x, dot 3.93x; SAXPY 7.19x as built, about 3.6x aligned | mostly matched; unaligned SAXPY is a placement artifact |
| L2 / L3 / DRAM gain (SAXPY) | 2x to 3x / 1.3x to 2.5x / 1.0x to 1.3x | current sweep 5.09x / 3.50x / 1.27x | not matched in L2 and L3; matched in DRAM |
| DRAM SAXPY rate | 2.5 to 5 GFLOP/s | about 2.8 GFLOP/s at the largest point | matched (low end) |
| steps in the hierarchy | 32 KiB, 512 KiB, about 16 MiB | 32 KiB (large), 512 KiB (15%), 11 to 16 MiB (large) | matched |
| strict dot | 0.9x to 1.3x | 1.00x to 1.05x | matched |
| fast-math dot, L1 / DRAM | 5x to 8x / 1.0x to 1.5x | 8.65x / 2.65x | above prediction; scalar baseline is latency-bound |
| alignment, scalar | within 3% | 0.98 to 1.07 in L1 | matched (DRAM noise 10% to 20%) |
| alignment, vector, L1 | none at 0 and 32 B; 10% to 50% otherwise; y worse than x | SAXPY +4% to +19% (y only), none when equal; multiply +35% to +49% including (0, 32) | partly matched; line-split explanation refuted in part |
| alignment, DRAM | under 5% | none for y only; +34% at (16, 16); one non-stationary cell | not matched |
| tail fixed cost | 10 to 30 cycles | about 4 to 8 cycles (1.86 ns `native`) | not matched (lower) |
| N mod 8 sawtooth | visible | not above noise | not observed |
| stride >= 2, `native` vs `scalar` | 0.9x to 1.1x | 0.57x to 1.43x | not matched (loop placement is consistent with the in-cache cases, untested) |
| DRAM time per element, strides 2/4/8/16 | 2x / 4x / 6x to 8x / 8x to 16x | native 3.3x / 5.0x / 9.1x / 18x; scalar 1.8x / 3.3x / 6.4x / 18.8x | scalar matched, native higher (faster unit-stride baseline) |
| gather | 0.8x to 1.5x; under 3 GB/s in DRAM | 2.05x (f32) and 1.6x (f64) in cache, 1.05x to 1.12x in DRAM; 1.8 to 2.9 GiB/s | in cache above, DRAM matched |
| f64 vs f32 in DRAM | same gain | SAXPY 1.21x vs 1.33x; dot 1.38x vs 2.68x | partly matched |
| measured f32 FMA peak | at least 85% of 32 FLOP/cycle x clock | 109.91 GFLOP/s = 76% to 86% for 4.0 to 4.5 GHz | only consistent with the low end of the inferred clock; first peak invalid |
| ridge point | about 3 to 6 FLOP/B | 3.88 FLOP/B | matched |
| L1 SAXPY share of peak; best DRAM kernel | 40% to 60%; 70% to 100% of roof | 48%; dot 89% (SAXPY 59%) | first matched; dot matched, SAXPY below range |
| variability | under 5% in cache; 10% to 30% in DRAM | median 2.4% to 2.5% in cache; 4.2% in DRAM (p90 12.7%) | better than expected |

## 7. Limitations
- **No hardware counters** (no `perf` under WSL2): vector-instruction, cache-miss and split-access statements rest on disassembly and timing; mechanisms are labelled hypotheses with a proposed test.
- **Virtualized, unpinned clock:** the benchmark is pinned to a *virtual* CPU; Windows may migrate it or use the sibling thread; Windows power mode and Energy Saver settings were user-reported; the guest cannot independently verify them. The effective clock (4.0 to 4.5 GHz from latency loops, 3.43 GHz from the FMA peak under a 32-FLOP/cycle assumption) is inferred, not measured; the peak estimate is 14% to 24% below the dot-loop estimates.
- **TSC cycles, not core cycles**, with the TSC frequency taken as BogoMIPS/2; nominal (not write-allocate) byte counts.
- **Code placement:** Loop-alignment tests (`*_al`) cover all four build families and five kernels at N = 1024 (Table 11b/11c). Full working-set sweeps use the unaligned builds and may retain placement effects at particular sizes.
- Cache sizes come from `lscpu`; the L3 is shared and virtualized. One machine, one session, one compiler (GCC 13.3.0): results may differ on other CPUs, compilers or native Linux.

## Appendix A. AI-use note
Claude (Anthropic) was used for the assisting with the benchmark scripts, general build and experiement program, as well as plot generation and initial setup plan outline. Gemini was used for general debugging questions. OpenAI Codex was used as a second opinion over the calculation and helping with checking report values against the raw and processed data, as well as organizing the report to be more easy to read. 

## Appendix B. Reproduction
```
chmod +x *.sh *.py
CPU=2 ./run_all.sh                                  # build, verify vectorization, experiments, plots, tables
CPU=2 python3 run_experiments.py --only peak,loopalign   # corrected FMA peak and the loop-placement test (also part of the full run)
python3 plot_all.py && python3 make_results_tables.py
```
Raw data `data/raw/*.csv` (the invalid first FMA peak is kept as `peak_v1_INVALID.csv`); processed `data/processed/*.csv`; figures `plots/`; compiler evidence `reports/`; environment `env/simd_env.txt`.

## Appendix C. Evidence index
| claim / figure | plot | table | raw data | compiler evidence |
|---|---|---|---|---|
| speedups (5.1) | e1_sweep_f32/f64 | RESULTS_TABLES 1 | data/raw/sweep.csv | reports/gcc_verdicts.csv, vec_counts.csv |
| clock inference (5.1) | | RESULTS_TABLES 10 | data/raw/sweep.csv | env/simd_env.txt (BogoMIPS) |
| locality (5.2) | e2_locality_saxpy | RESULTS_TABLES 1 | data/raw/sweep.csv | reports/disasm_saxpy_f32_native.txt |
| alignment, tail (5.3) | e3_alignment, e3_tail | RESULTS_TABLES 2, 3 | data/raw/align.csv, tail.csv | reports/disasm_saxpy_f32_native.txt |
| stride, gather (5.4) | e4_stride_gather | RESULTS_TABLES 4, 11d | data/raw/stride.csv | reports/vec_all_native.txt, loop_alignment_stride.csv |
| data type (5.5) | e5_dtype | RESULTS_TABLES 5, 11c | data/raw/sweep.csv, loopalign.csv | reports/vec_counts.csv |
| roofline (5.6) | e7_roofline | RESULTS_TABLES 6, 7 | data/raw/peak.csv, sweep.csv | build/peak_flops disassembly |
| dot negative case (5.7a) | e1_sweep_f32 | RESULTS_TABLES 1, 9 | data/raw/sweep.csv | reports/disasm_dot_f32_native_strict.txt, ..._fastmath.txt |
| loop placement (5.7c, 5.8) | e8_loop_placement | RESULTS_TABLES 11a, 11b, 11c | data/raw/loopalign.csv | reports/loop_alignment.csv |

## Appendix D. Errors in the measurement tool-chain found during this study
* **`peak_flops` v1** kept the accumulators in a stack array (every FMA followed by a store and reload), so it reported 27.8 GFLOP/s. Found by comparing with the kernels and by disassembly; v2 uses named register variables (register-only `vfmadd` in the loop) and the retained peak CSV reports 109.91 GFLOP/s.
* **`verify_vec.sh` v1** aborted early (`pipefail` with an early-exiting `awk | head`), so the first full run stopped before any experiment; fixed.
* **Plot colors:** the lower row of the sweep figure used a different color order from its legend; fixed with one color per build.
* **Initial prediction:** assumed gather would not be vectorized; GCC reports it as vectorized (element-wise loads, no hardware gather), and the data show a 2x in-cache gain.
* **Code placement** (5.7c) is not a tool-chain error but a measurement hazard discovered here: identical instruction streams ran 1.9x apart.
