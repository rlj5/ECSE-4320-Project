# ECSE 4320/6320 Project 1: SIMD Advantage Profiling (Ryzen 7 5825U, WSL2)

Single-thread study of scalar vs SSE2 vs AVX2/FMA code for SAXPY, element-wise multiply, dot product and a 3-point stencil (f32 and f64):
working-set sweep (L1 to DRAM), alignment and tail handling, stride/gather, data type, vectorization verification, roofline, and negative examples.

| file | purpose |
|---|---|
| `HYPOTHESES.md` | pre-experiment predictions |
| `REPORT.md` | methodology, results, interpretation, limitations, and evidence index |
| `src/bench.c` | kernels + harness (one process = one configuration; correctness check against a plain `-O0` double-precision reference before timing) |
| `src/peak_flops.c` | single-core AVX2 FMA peak, selecting the best of 8, 10, or 12 independent chains |
| `build.sh` | builds `scalar`, `auto`, `native`, `native_fm` plus aligned twins including `auto_al`; writes GCC vectorization reports to `reports/` |
| `verify_vec.sh` | disassembly instruction counts, per-kernel GCC verdicts, excerpts, loop alignment -> `reports/` |
| `loop_alignment.py` | start address and 64-byte straddling of each hot loop -> `reports/loop_alignment*.csv` |
| `run_experiments.py` | all experiments, pinned with `taskset`, raw CSV -> `data/raw/` |
| `plot_all.py` | processed CSV -> `data/processed/`, figures -> `plots/` |
| `make_results_tables.py` | `RESULTS_TABLES.md`: every number quoted in the report |
| `collect_env.sh` | records CPU/OS/compiler/power/SMT info -> `env/` |
| `run_all.sh` | everything above in order |

## Reproduce (Windows 11 + WSL2 Ubuntu 24.04)
```bash
sudo apt update && sudo apt install -y build-essential python3-pandas python3-matplotlib python3-tabulate binutils
git clone <your repo> && cd <repo>
lscpu -p=CPU,CORE | grep -v '^#' | head -8        # pick CPU 2; its SMT sibling is CPU 3: keep it idle
CPU=2 ./run_all.sh --quick                        # about 5-10 min: smoke test, check plots/ look sane
CPU=2 ./run_all.sh                                # full run, about 20-40 min
```
The measurements were captured with AC power, Windows Best performance mode, and Energy Saver off. Close background workloads and do not use the laptop while benchmarking.


## Reproduce
```bash
chmod +x *.sh *.py                              # zip/Windows may drop the executable bits
CPU=2 ./run_all.sh                              # collect env, build (incl. the aligned *_al builds), verify vectorization, all experiments, plots, tables
# or step by step:
./build.sh && ./verify_vec.sh                   # builds, GCC verdicts, instruction counts, disassembly excerpts, loop addresses
objdump -d build/peak_flops | grep -c vfmadd    # sanity check of the FMA benchmark: register-only vfmadd in the hot loops
CPU=2 python3 run_experiments.py --only sweep,align,tail,stride,peak,loopalign
python3 plot_all.py && python3 make_results_tables.py
```
Pin to one logical CPU (`lscpu -p=CPU,CORE`; here CPU 2, SMT sibling CPU 3 not used), AC power, nothing else running. WSL2 cannot set the governor or read the clock; 

## Where things are
* `REPORT.md`: the final report; every number comes from `RESULTS_TABLES.md` (generated).
* `data/raw/`: raw measurements; `peak_v1_INVALID.csv` is the first, invalid FMA-peak measurement, kept for the record (see report Appendix D); `loopalign.csv` is the loop-placement test.
* `data/processed/`, `plots/` (`e1`..`e5`, `e7`, `e8`), `reports/` (GCC verdicts, instruction counts, disassembly, loop addresses), `env/simd_env.txt`.
* `HYPOTHESES.md`: predictions and rationale for the experiments.

## Notes and limitation
* No hardware counters under WSL2 (`perf` has no kernel support): vector-instruction evidence comes from disassembly and GCC reports only.
* Pinning is to a virtual CPU; cpufreq/governor and boost are not visible from the guest. Cycle numbers marked `tsc_` use the TSC reference clock, not core cycles.
* Bandwidths are nominal (no write-allocate traffic counted), like most STREAM-style reports; the report states this wherever it matters.
* Environment captured so far: `env/simd_env.txt` (from your first run: WSL2, GCC 13.3.0, Ryzen 7 5825U). Re-run `./collect_env.sh simd` on the day of the final run.
