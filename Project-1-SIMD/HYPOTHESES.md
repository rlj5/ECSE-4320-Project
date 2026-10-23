# Pre-experiment hypotheses (Project 1, SIMD advantage profiling)

Platform: AMD Ryzen 7 5825U (Zen 3, 8C/16T), AVX2 + FMA, **no AVX-512**, running under **WSL2** (Ubuntu 24.04, GCC 13.3.0).
Predictions include rationale and an observation that would contradict them.

## 0. Benchmarking
| fact | value | source / how to check |
|---|---|---|
| L1D / L2 / L3 | 32 KiB per core / 512 KiB per core / 16 MiB shared (mobile Zen 3 has a unified 16 MiB L3) | your `env/simd_env.txt` (`lscpu`); Wikipedia "Zen 3" |
| Latencies (desktop Zen 3) | L2 about 12 cycles, L3 about 46 cycles | Wikipedia "Zen 3" (the 5825U's L3 may differ; unverified) |
| FP pipes | 4 FP pipes; 2 can do 256-bit FMA; FMA latency 4 cycles; FADD latency about 3 cycles | AMD ISSCC "Zen 3" slides; verify in the AMD optimization guide |
| Load/store | up to 3 loads and 2 stores per cycle, but only about one 256-bit store per cycle; cache paths 32 B/cycle | AMD ISSCC slides; Illinois CS433 Zen slides (sources vary: treat as approximate) |
| Peak f32 FMA | 2 pipes x 8 lanes x 2 FLOP = **32 FLOP/cycle** (f64: 16) | derived |
| Cache line | 64 B | standard x86 |
| Vector codegen | from your own `reports/disasm_saxpy_f32_native.txt`: one 256-bit `vfmadd213ps` per loop trip, **no unrolling, no alignment peeling** (unaligned `vmovups`), then a 128-bit step and a scalar tail | your files |

Clock caveat: under WSL2 you cannot read or set the core clock, and Windows Energy Saver may cap it. Ratios (speedups) are mostly clock independent in cache; absolute GFLOP/s and GiB/s are not.
Derive the effective clock from the measured FMA peak: `f_eff = peak_f32_GFLOPs / 32` (assumes 2 FMA pipes; state this assumption).
`tsc_cyc_per_elem` is in *TSC* cycles (a fixed reference clock, probably about 2 GHz on this part), not core cycles.

## 1. Builds
`scalar` = `-O3 -fno-tree-vectorize -fno-tree-slp-vectorize` (baseline x86-64, no FMA); `auto` = `-O3` (128-bit SSE2); `native` = `-O3 -march=native` (AVX2+FMA, strict FP); `native_fm` = `native -ffast-math`.

## 2. Predictions
**H1. In-cache SIMD gain (working set at most 32 KiB, speedup over `scalar`).**
- SAXPY, multiply, stencil, f32, `native`: **4x to 8x** (best guess about 6x). Reason: the scalar loop costs about 1 cycle per element (one store per element plus loop overhead), while one 256-bit iteration handles 8 elements in about 1 cycle (store-bound). The gain stays below 8x because the vector loop is not unrolled and the loop branch costs the same as in the scalar loop.
- `auto` (128-bit): about **2x to 4x**, roughly half of `native`.
- f64: about **half the f32 gain** (4 lanes instead of 8): 2x to 4x.
- *Wrong if:* f32 gain is under 3x (the loop is limited by something other than the store port, e.g. clock/Energy Saver artifacts or a poorly pinned vCPU) or above 8x (the scalar baseline is loop-overhead bound; check cycles/element).

**H2. Locality: the gain compresses as the working set leaves L1.**
- Beyond 32 KiB, SAXPY needs about 12 B of L2-to-L1 traffic per element at 32 B/cycle, so about 0.4 cycles/element: speedup falls to **about 2x to 3x in L2**, **1.3x to 2.5x in L3**, and **1.0x to 1.3x in DRAM**.
- In DRAM the scalar loop (about 1 cycle/element, i.e. 12 B per cycle) already demands more than one core's DRAM bandwidth, so SIMD cannot help much. Expected single-core DRAM-resident SAXPY: **roughly 15-30 GB/s of nominal traffic, i.e. 2.5-5 GFLOP/s**.
- Visible steps near 32 KiB, 512 KiB and about 16 MiB (the L3 is shared and virtualized, so its effective edge may sit earlier).
- *Wrong if:* the speedup stays above 3x past 16 MiB (the working set is not actually DRAM-resident) or there is no step at 32 KiB.

**H3. Dot product (reduction): the negative example.**
- Strict `dot` (`native`, no fast-math): GCC reports "vectorized", but only the multiplies are vector; the additions stay in source order. Predicted speedup **0.9x to 1.3x** at every size (both versions are bound by the 3-4 cycle add/FMA latency chain, about 3 cycles/element).
- `native_fm` dot: single vector accumulator, latency bound at 3-4 cycles per 8 elements: **5x to 8x in L1**, compressing to about 1x to 1.5x in DRAM.
- f64: roughly half of the f32 numbers.
- *Wrong if:* strict `dot` shows more than 2x (then the compiler did unroll with several accumulators; read the disassembly).

**H4. Alignment (SAXPY, f32, `native`).**
- A 32 B access that starts at an offset which is not a multiple of 32 B crosses a 64 B line on every second access. I predict: offsets that are multiples of 32 B (0, 32): **no penalty**; offsets 4, 8, 16, 60 B: **similar penalty to each other** (about 50% of accesses split), **10% to 50% slower in L1/L2**, **under 5% in DRAM**. Stores are more costly to split than loads, so misaligning `y` (read and written) hurts more than misaligning `x`.
- The `scalar` build is unaffected (**within 3%**): 4 B accesses at 4 B-multiple offsets never split.
- *Wrong if:* the penalty differs between offsets 4 and 16 (a 16 B boundary effect rather than a line-split effect), or L1 shows no penalty (split loads are fully hidden on this core).

**H5. Tail handling.**
- From the compiler output: N of 7 or fewer skips the vector loop; larger N runs the 8-wide loop, then a 4-wide step, then up to 3 scalar iterations. Expected: fixed cost per call of **roughly 10-30 cycles**; for N of 1 to 16 the cost per element is **several times** the long-loop value; a **sawtooth in N mod 8** of a few cycles amplitude below N of about 64.
- WSL2 timer noise (about 1 ns or more) may hide the sawtooth; if so, mention in report.
- *Wrong if:* the cost per call is under 5 cycles (then call overhead is being optimized away; check the harness).

**H6. Stride and gather.**
- Strides of 2 and more: the compiler's verdict "vectorized" refers to the unit-stride version of the loop; the strided path stays scalar ("no vectype" in the missed-report). Predicted speedup of `native` over `scalar` at stride 2, 4, 8, 16: **0.9x to 1.1x**.
- Useful bandwidth in DRAM falls roughly with 1/stride up to 16 floats (one new 64 B line per element): time per element grows about **2x, 4x, 6-8x, 8-16x** at strides 2, 4, 8, 16. In L1/L2 the drop is much smaller (about 1.5x to 3x from stride 1 to 16).
- Gather (random index over the whole array): GCC reports it as vectorized, but Zen 3 gathers are slow and my own znver3 compile contained **no hardware gather instruction**, so any "vectorization" is element-wise loads. Predicted speedup **0.8x to 1.5x**; DRAM-resident gather: **under 3 GB/s useful bandwidth** (latency bound, partly hidden by out-of-order overlap).
- *Wrong if:* gather speeds up more than 2x (check for `vgatherdps` in the disassembly).

**H7. Data type (f32 vs f64).**
- In cache: f64 speedup about half of f32 (lanes 4 vs 8) and half the FLOP/s (same instruction rate, half the lanes). In DRAM: both limited by bytes/second, so **the same speedup (about 1x to 1.3x)**; arithmetic intensity halves for f64 (SAXPY 0.167 to 0.083 FLOP/B).

**H8. Roofline.**
- Measured single-core f32 FMA peak: **at least 85% of 32 FLOP/cycle x f_eff** (10 independent chains cover latency 4 x 2 pipes = 8). f64 about half.
- Arithmetic intensities (nominal): SAXPY 0.167, multiply 0.083, dot 0.25, stencil 0.625 FLOP/B. With a ridge point of peak/bandwidth of roughly **3 to 6 FLOP/B**, all four kernels sit left of the ridge: **memory-bound beyond L2, load/store-bound (not FMA-bound) in L1**; L1 SAXPY should reach only about **40% to 60% of the FMA peak**; the best kernel in DRAM reaches 70% to 100% of the measured-bandwidth roof.
- *Wrong if:* a kernel above 70% of FMA peak in L1 (compute-bound claim would need justification) or DRAM kernels far below the bandwidth roof (the "bandwidth" probe was weak).

**H9. Measurement quality under WSL2.**
- Median coefficient of variation: **under 5% in cache**, **10% to 30% in DRAM-size runs**, with occasional outliers when Windows schedules other work. Pinning is only to a *virtual* CPU, so migration is possible; Energy Saver may lower the clock between runs. I expect to see this as larger spread, not as a systematic bias in the ratios.

## 3. Anomalies that might appear
A dip or bump near 16-32 KiB (L1 conflict/associativity), an early L3 step (shared/virtualized L3), speedup below 1.0 for DRAM-sized sweeps within noise, and slow first-touch behaviour for the largest sizes in a VM.

## 4. Resources
- https://en.wikipedia.org/wiki/Zen_3 (L2 512 KiB/12 cycles, L3 46 cycles, mobile unified 16 MiB L3, FMA latency 4)
- https://www.slideshare.net/slideshow/zen-3-amd-2nd-generation-7nm-x8664-microprocessor-core/251610640 (AMD ISSCC "Zen 3" summary: 3 loads and 2 stores per cycle, FMAC latency 4, 32 B/cycle)
- https://courses.physics.illinois.edu/cs433/fa2022/projects/AMD-Zen.pdf (course slides: 32 KiB 8-way L1D, 512 KiB 8-way L2, single 256-bit store per cycle)
- https://7-cpu.com/cpu/Zen2.html (Zen 2 measurements, used only for the idea that split accesses cost an extra cycle; Zen 3 not separately verified)
