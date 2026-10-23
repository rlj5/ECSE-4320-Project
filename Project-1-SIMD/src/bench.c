// SIMD benchmark harness. One process = one (kernel,dtype,N,offsets,stride) config, `reps` timed repetitions.
// Usage: bench <saxpy|mul|dot|stencil|stride|gather> <f32|f64> <N> <reps> [offx_bytes offy_bytes stride]
// Build variants (see build.sh) differ ONLY in compiler flags; this file is identical for all.
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include <time.h>
#ifndef VARIANT
#define VARIANT "unknown"
#endif
enum { K_SAXPY, K_MUL, K_DOT, K_STENCIL, K_STRIDE, K_GATHER };
static const char *KN[] = {"saxpy","mul","dot","stencil","stride","gather"};
static double now(void){ struct timespec t; clock_gettime(CLOCK_MONOTONIC_RAW,&t); return t.tv_sec+1e-9*t.tv_nsec; }
static inline uint64_t rdtsc(void){ unsigned lo,hi; __asm__ volatile("rdtsc":"=a"(lo),"=d"(hi)); return ((uint64_t)hi<<32)|lo; }
static uint64_t rs = 88172645463325252ULL;
static inline uint64_t rnd(void){ rs^=rs<<13; rs^=rs>>7; rs^=rs<<17; return rs; }

#define K_SAXPY_D(T,S) __attribute__((noinline)) void k_saxpy_##S(T a,const T*restrict x,T*restrict y,size_t n){ for(size_t i=0;i<n;i++) y[i]=a*x[i]+y[i]; }
#define K_MUL_D(T,S) __attribute__((noinline)) void k_mul_##S(const T*restrict x,const T*restrict y,T*restrict z,size_t n){ for(size_t i=0;i<n;i++) z[i]=x[i]*y[i]; }
#define K_DOT_D(T,S) __attribute__((noinline)) T k_dot_##S(const T*restrict x,const T*restrict y,size_t n){ T s=0; for(size_t i=0;i<n;i++) s+=x[i]*y[i]; return s; }
#define K_STENCIL_D(T,S) __attribute__((noinline)) void k_stencil_##S(T a,T b,T c,const T*restrict x,T*restrict y,size_t n){ for(size_t i=1;i+1<n;i++) y[i]=a*x[i-1]+b*x[i]+c*x[i+1]; }
#define K_STRIDE_D(T,S) __attribute__((noinline)) void k_stride_##S(T a,const T*restrict x,T*restrict y,size_t n,size_t s){ for(size_t i=0;i<n;i++) y[i*s]=a*x[i*s]+y[i*s]; }
#define K_GATHER_D(T,S) __attribute__((noinline)) void k_gather_##S(T a,const T*restrict x,T*restrict y,const uint32_t*restrict idx,size_t n){ for(size_t i=0;i<n;i++) y[i]=a*x[idx[i]]+y[i]; }
// One instantiation per line so that -fopt-info line numbers identify kernel+dtype (verify_vec.sh maps them via KERNEL_LINE markers).
K_SAXPY_D(float,f32)    // KERNEL_LINE saxpy f32
K_MUL_D(float,f32)      // KERNEL_LINE mul f32
K_DOT_D(float,f32)      // KERNEL_LINE dot f32
K_STENCIL_D(float,f32)  // KERNEL_LINE stencil f32
K_STRIDE_D(float,f32)   // KERNEL_LINE stride f32
K_GATHER_D(float,f32)   // KERNEL_LINE gather f32
K_SAXPY_D(double,f64)   // KERNEL_LINE saxpy f64
K_MUL_D(double,f64)     // KERNEL_LINE mul f64
K_DOT_D(double,f64)     // KERNEL_LINE dot f64
K_STENCIL_D(double,f64) // KERNEL_LINE stencil f64
K_STRIDE_D(double,f64)  // KERNEL_LINE stride f64
K_GATHER_D(double,f64)  // KERNEL_LINE gather f64

#define DEF_RUN(T,S) \
static T run_##S(int k,T*x,T*y,T*z,uint32_t*idx,size_t n,size_t s){ \
  switch(k){ \
  case K_SAXPY: k_saxpy_##S((T)1.0000001,x,y,n); return 0; \
  case K_MUL: k_mul_##S(x,y,z,n); return 0; \
  case K_DOT: return k_dot_##S(x,y,n); \
  case K_STENCIL: k_stencil_##S((T)0.25,(T)0.5,(T)0.25,x,y,n); return 0; \
  case K_STRIDE: k_stride_##S((T)1.0000001,x,y,n,s); return 0; \
  case K_GATHER: k_gather_##S((T)1.0000001,x,y,idx,n); return 0; } return 0; }
DEF_RUN(float,f32)
DEF_RUN(double,f64)

// Simple reference: plain loops, double precision, -O0 (never vectorized).
#define DEF_REF(T,S) \
__attribute__((optimize("O0"))) static void ref_##S(int k,const T*x,T*y,T*z,const uint32_t*idx,size_t n,size_t s,double*dot){ \
  const double A=1.0000001; size_t i; \
  switch(k){ \
  case K_SAXPY: for(i=0;i<n;i++) y[i]=(T)(A*(double)x[i]+(double)y[i]); break; \
  case K_MUL: for(i=0;i<n;i++) z[i]=(T)((double)x[i]*(double)y[i]); break; \
  case K_DOT: { double t=0; for(i=0;i<n;i++) t+=(double)x[i]*(double)y[i]; *dot=t; } break; \
  case K_STENCIL: for(i=1;i+1<n;i++) y[i]=(T)(0.25*(double)x[i-1]+0.5*(double)x[i]+0.25*(double)x[i+1]); break; \
  case K_STRIDE: for(i=0;i<n;i++) y[i*s]=(T)(A*(double)x[i*s]+(double)y[i*s]); break; \
  case K_GATHER: for(i=0;i<n;i++) y[i]=(T)(A*(double)x[idx[i]]+(double)y[i]); break; } }
DEF_REF(float,f32)
DEF_REF(double,f64)

static void *A(size_t bytes,size_t off){ size_t sz=((bytes+off+128)+4095)/4096*4096; char*p=aligned_alloc(4096,sz); if(!p){fprintf(stderr,"alloc fail\n");exit(2);} return p+off; }
static inline double u01(void){ return (rnd()>>11)*(1.0/9007199254740992.0); }

#define DEF_MAIN(T,S,TOLD,TOLO) \
static int check_##S(int k,size_t N,size_t offx,size_t offy,size_t s){ \
  size_t n = N<20001?N:20001; size_t se=(k==K_STRIDE)?s:1; size_t span=n*se+8; \
  T*x1=A(span*sizeof(T),offx),*y1=A(span*sizeof(T),offy),*z1=A(span*sizeof(T),0); \
  T*x2=A(span*sizeof(T),offx),*y2=A(span*sizeof(T),offy),*z2=A(span*sizeof(T),0); \
  uint32_t*idx=A(n*4+64,0); \
  for(size_t i=0;i<n;i++) idx[i]=rnd()%n; \
  for(size_t i=0;i<span;i++){ x1[i]=x2[i]=(T)u01(); y1[i]=y2[i]=(T)u01(); z1[i]=z2[i]=0; } \
  T d1=run_##S(k,x1,y1,z1,idx,n,s); double d2=0; ref_##S(k,x2,y2,z2,idx,n,s,&d2); \
  double mr=0; for(size_t i=0;i<span;i++){ double a=y1[i],b=y2[i]; double r=fabs(a-b)/(fabs(b)+1e-30); if(r>mr)mr=r; a=z1[i]; b=z2[i]; r=fabs(a-b)/(fabs(b)+1e-30); if(r>mr)mr=r; } \
  if(k==K_DOT){ double r=fabs((double)d1-d2)/(fabs(d2)+1e-30); if(r>mr)mr=r; } \
  double tol=(k==K_DOT)?TOLD:TOLO; \
  if(mr>tol){ fprintf(stderr,"CHECK FAIL %s %s maxrel=%g tol=%g\n",KN[k],#S,mr,tol); return 1; } \
  fprintf(stderr,"CHECK_OK %s %s n=%zu maxrel=%.3g\n",KN[k],#S,n,mr); return 0; } \
static int main_##S(int k,size_t N,int reps,size_t offx,size_t offy,size_t s){ \
  if(check_##S(k,N,offx,offy,s)) return 1; \
  size_t se=(k==K_STRIDE)?s:1; size_t span=N*se+8; \
  T*x=A(span*sizeof(T),offx),*y=A(span*sizeof(T),offy),*z=A(span*sizeof(T),0); uint32_t*idx=A(N*4+64,0); \
  for(size_t i=0;i<span;i++){ x[i]=(T)u01(); y[i]=(T)u01(); z[i]=0; } \
  for(size_t i=0;i<N;i++) idx[i]=i; for(size_t i=N-1;i>0;i--){ size_t j=rnd()%(i+1); uint32_t t=idx[i]; idx[i]=idx[j]; idx[j]=t; } \
  volatile double sink=0; double r=run_##S(k,x,y,z,idx,N,s); sink+=(double)r; \
  double t0=now(); r=run_##S(k,x,y,z,idx,N,s); sink+=(double)r; double t1=now()-t0; if(t1<1e-9)t1=1e-9; \
  size_t iters=(size_t)(0.02/t1); if(iters<1)iters=1; if(iters>20000000)iters=20000000; \
  for(int rep=0;rep<reps;rep++){ \
    double a=now(); uint64_t c0=rdtsc(); \
    for(size_t it=0;it<iters;it++){ r=run_##S(k,x,y,z,idx,N,s); sink+=(double)r; __asm__ volatile("":::"memory"); } \
    uint64_t c1=rdtsc(); double b=now(); \
    printf("%s,%s,%s,%zu,%zu,%zu,%zu,%d,%.6e,%.1f,%zu,%g\n",VARIANT,KN[k],#S,N,offx,offy,s,rep,(b-a)/iters,(double)(c1-c0)/iters,iters,(double)sink); } \
  return 0; }
DEF_MAIN(float,f32,2e-3,2e-5)
DEF_MAIN(double,f64,1e-9,1e-12)

int main(int argc,char**argv){
  if(argc>1 && !strcmp(argv[1],"--header")){ puts("variant,kernel,dtype,N,offx,offy,stride,rep,sec_per_call,tsc_per_call,iters,sink"); return 0; }
  if(argc<5){ fprintf(stderr,"usage: %s kernel dtype N reps [offx offy stride]\n",argv[0]); return 2; }
  int k=-1; for(int i=0;i<6;i++) if(!strcmp(argv[1],KN[i])) k=i; if(k<0){fprintf(stderr,"bad kernel\n");return 2;}
  size_t N=strtoull(argv[3],0,10); int reps=atoi(argv[4]);
  size_t offx=argc>5?strtoull(argv[5],0,10):0, offy=argc>6?strtoull(argv[6],0,10):0, s=argc>7?strtoull(argv[7],0,10):1;
  if(N<3){ fprintf(stderr,"N>=3\n"); return 2; }
  if(!strcmp(argv[2],"f32")) return main_f32(k,N,reps,offx,offy,s);
  if(!strcmp(argv[2],"f64")) return main_f64(k,N,reps,offx,offy,s);
  fprintf(stderr,"bad dtype\n"); return 2;
}
