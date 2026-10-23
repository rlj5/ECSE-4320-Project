#!/usr/bin/env bash
# Usage: ./run_all.sh [--quick] [--tag NAME]       (CPUS=0,2,4,... overrides the auto-detected physical-core CPU list)
set -euo pipefail; cd "$(dirname "$0")"
./preflight.sh
./collect_env.sh cache
./build.sh
python3 run_experiments.py "$@"
python3 plot_all.py
python3 make_results_tables.py
