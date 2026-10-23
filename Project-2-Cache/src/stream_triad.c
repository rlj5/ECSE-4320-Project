// Independent cross-check of membw: STREAM-style triad a[i] = b[i] + s*c[i] (f64), OpenMP, first-touch init, best-of-N timing.
// Counted bytes = 24 B per element (no write-allocate counted), the STREAM convention.
// Usage: OMP_NUM_THREADS=T OMP_PROC_BIND=true OMP_PLACES="{0},{2},..." ./stream_triad [bytes_per_array=268435456] ; CSV on stdout
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
#include <time.h>
static double now(void){ struct timespec t; clock_gettime(CLOCK_MONOTONIC_RAW,&t); return t.tv_sec+1e-9*t.tv_nsec; }
int main(int argc,char**argv){
  if(argc>1&&argv[1][0]=='-'){ puts("threads,bytes_per_array,best_GBps,median_GBps"); return 0; }
  size_t bytes=argc>1?strtoull(argv[1],0,10):268435456ULL, n=bytes/8; double *a=aligned_alloc(4096,n*8),*b=aligned_alloc(4096,n*8),*c=aligned_alloc(4096,n*8); if(!a||!b||!c){ fprintf(stderr,"alloc\n"); return 2; }
  #pragma omp parallel for schedule(static)
  for(size_t i=0;i<n;i++){ a[i]=0; b[i]=1.0+i%7; c[i]=2.0+i%5; }
  double t[12]; int T=omp_get_max_threads();
  for(int it=0;it<12;it++){ double t0=now();
    #pragma omp parallel for schedule(static)
    for(size_t i=0;i<n;i++) a[i]=b[i]+3.0*c[i];
    t[it]=now()-t0; }
  for(int i=1;i<12;i++) for(int j=i;j>1&&t[j]<t[j-1];j--){ double x=t[j]; t[j]=t[j-1]; t[j-1]=x; }   // sort t[1..11] (t[0] = warm-up, excluded)
  double chk=0; for(size_t i=0;i<n;i+=n/64) chk+=a[i];
  printf("%d,%zu,%.3f,%.3f\n",T,bytes,24.0*n/t[1]/1e9,24.0*n/t[6]/1e9); if(chk<0) puts("x"); return 0; }
