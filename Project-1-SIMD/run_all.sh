#!/usr/bin/env bash
# Usage: CPU=2 ./run_all.sh [--quick|--tiny]
# CPU = logical CPU to pin to (see `lscpu -p=CPU,CORE`; keep its SMT sibling idle). Run on AC power with background apps closed.
set -euo pipefail; cd "$(dirname "$0")"
./collect_env.sh simd
./build.sh
./verify_vec.sh || echo "WARNING: verify_vec.sh failed; continuing so the experiments still run (rerun it separately)"
python3 run_experiments.py "$@"
python3 plot_all.py
python3 make_results_tables.py
