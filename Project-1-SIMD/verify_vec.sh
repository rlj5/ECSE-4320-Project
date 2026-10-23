#!/usr/bin/env bash
# Counts packed-FP / ymm / FMA instructions inside each kernel function of each build -> reports/vec_counts.csv
set -eu   # deliberately NO pipefail: awk/head exit early, objdump gets SIGPIPE, and pipefail+set -e would abort the script
cd "$(dirname "$0")"
echo "variant,function,total_insn,packed_fp,ymm,xmm_packed,fma" > reports/vec_counts.csv
for v in scalar auto native native_fm; do
  objdump -d --no-show-raw-insn build/bench_$v | awk -F'\t' -v v=$v '
    /^[0-9a-f]+ <k_[A-Za-z0-9_.]+>:/ { match($0,/<[^>]+>/); fn=substr($0,RSTART+1,RLENGTH-2); next }
    /^$/ { fn="" ; next }
    fn!="" && NF>=2 { split($2,a," "); m=a[1]; tot[fn]++;
        if (m ~ /(ps|pd)$/ && m !~ /^v?(cvt|comis|ucomis|unpck|movmsk)/) pk[fn]++;
        if ($2 ~ /ymm/) ym[fn]++; if ($2 ~ /xmm/ && m ~ /(ps|pd)$/) xm[fn]++; if (m ~ /fmadd|fnmadd|fmsub/) fm[fn]++ }
    END { for (f in tot) printf "%s,%s,%d,%d,%d,%d,%d\n", v,f,tot[f],pk[f]+0,ym[f]+0,xm[f]+0,fm[f]+0 }' | sort >> reports/vec_counts.csv
done
# dump disassembly to files first (no early-exiting pipelines), then slice out one function
for b in native native_fm; do objdump -d --no-show-raw-insn build/bench_$b > build/disasm_$b.txt; done
ex(){ awk -v f="<$2>:" 'index($0,f){p=1} p{print} p&&/^[[:space:]]*[0-9a-f]+:[[:space:]]+ret/{exit}' build/disasm_$1.txt | head -$3 > reports/$4 || true; }
ex native k_saxpy_f32 60 disasm_saxpy_f32_native.txt
ex native k_dot_f32 40 disasm_dot_f32_native_strict.txt
ex native_fm k_dot_f32 60 disasm_dot_f32_native_fastmath.txt
# Per-kernel gcc loop-vectorizer verdicts, mapped from source line -> kernel via the KERNEL_LINE markers
{ echo "variant,kernel,dtype,gcc_verdict"
  for v in scalar auto native native_fm; do
    grep -nE "// KERNEL_LINE [a-z]+ f[0-9]+$" src/bench.c | while IFS=: read ln rest; do set -- $rest; k=$4; d=$5
      if grep -qE "bench.c:$ln:[0-9]+: optimized: loop vectorized using ([0-9]+) byte" reports/vec_all_$v.txt; then
        w=$(grep -E "bench.c:$ln:[0-9]+: optimized: loop vectorized using" reports/vec_all_$v.txt | grep -oE "[0-9]+ byte" | sort -n | tail -1)
        echo "$v,$k,$d,vectorized ($w vectors)"
      else echo "$v,$k,$d,NOT vectorized"; fi; done; done; } > reports/gcc_verdicts.csv
{ for v in native native_fm; do echo "[$v: missed-reason lines for the dot kernels]"; L=$(grep -n "KERNEL_LINE dot f32" src/bench.c | cut -d: -f1)
    grep -E "bench.c:$L:[0-9]+: missed" reports/vec_all_$v.txt | sort -u | head -5; done; } > reports/vec_report_excerpt.txt
cat reports/gcc_verdicts.csv | sed 's/,/\t/g'
python3 loop_alignment.py || echo "loop_alignment.py failed (non-fatal)"
