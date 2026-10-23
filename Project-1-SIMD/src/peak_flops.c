// Single-core peak FLOP/s estimate with K independent FMA chains held in REGISTERS (AVX2+FMA). Prints CSV (best K per dtype).
// v2: accumulators are named scalar variables, NOT an array. (v1 used a[10] with a runtime inner loop; GCC kept the array in memory,
// so every FMA was followed by a store and reloaded through store forwarding => ~4x too low. Check with: objdump -d build/peak_flops
// -- the hot loop must contain only register-operand vfmadd instructions and no vmovaps stores.)
#include <immintrin.h>
#include <stdio.h>
#include <time.h>
static double now(void){ struct timespec t; clock_gettime(CLOCK_MONOTONIC_RAW,&t); return t.tv_sec+1e-9*t.tv_nsec; }
#define F(a) a=_mm256_fmadd_ps(a,m,c);
#define D(a) a=_mm256_fmadd_pd(a,m,c);
__attribute__((noinline)) static float run8_f32(long n){ __m256 m=_mm256_set1_ps(1.0000001f),c=_mm256_set1_ps(1e-7f),a0=_mm256_set1_ps(0),a1=_mm256_set1_ps(1),a2=_mm256_set1_ps(2),a3=_mm256_set1_ps(3),a4=_mm256_set1_ps(4),a5=_mm256_set1_ps(5),a6=_mm256_set1_ps(6),a7=_mm256_set1_ps(7);
  for(long i=0;i<n;i++){ F(a0)F(a1)F(a2)F(a3)F(a4)F(a5)F(a6)F(a7) }
  __m256 s=_mm256_add_ps(_mm256_add_ps(_mm256_add_ps(a0,a1),_mm256_add_ps(a2,a3)),_mm256_add_ps(_mm256_add_ps(a4,a5),_mm256_add_ps(a6,a7))); float o[8]; _mm256_storeu_ps(o,s); return o[0]; }
__attribute__((noinline)) static float run10_f32(long n){ __m256 m=_mm256_set1_ps(1.0000001f),c=_mm256_set1_ps(1e-7f),a0=_mm256_set1_ps(0),a1=_mm256_set1_ps(1),a2=_mm256_set1_ps(2),a3=_mm256_set1_ps(3),a4=_mm256_set1_ps(4),a5=_mm256_set1_ps(5),a6=_mm256_set1_ps(6),a7=_mm256_set1_ps(7),a8=_mm256_set1_ps(8),a9=_mm256_set1_ps(9);
  for(long i=0;i<n;i++){ F(a0)F(a1)F(a2)F(a3)F(a4)F(a5)F(a6)F(a7)F(a8)F(a9) }
  __m256 s=_mm256_add_ps(_mm256_add_ps(_mm256_add_ps(a0,a1),_mm256_add_ps(a2,a3)),_mm256_add_ps(_mm256_add_ps(a4,a5),_mm256_add_ps(_mm256_add_ps(a6,a7),_mm256_add_ps(a8,a9)))); float o[8]; _mm256_storeu_ps(o,s); return o[0]; }
__attribute__((noinline)) static float run12_f32(long n){ __m256 m=_mm256_set1_ps(1.0000001f),c=_mm256_set1_ps(1e-7f),a0=_mm256_set1_ps(0),a1=_mm256_set1_ps(1),a2=_mm256_set1_ps(2),a3=_mm256_set1_ps(3),a4=_mm256_set1_ps(4),a5=_mm256_set1_ps(5),a6=_mm256_set1_ps(6),a7=_mm256_set1_ps(7),a8=_mm256_set1_ps(8),a9=_mm256_set1_ps(9),a10=_mm256_set1_ps(10),a11=_mm256_set1_ps(11);
  for(long i=0;i<n;i++){ F(a0)F(a1)F(a2)F(a3)F(a4)F(a5)F(a6)F(a7)F(a8)F(a9)F(a10)F(a11) }
  __m256 s=_mm256_add_ps(_mm256_add_ps(_mm256_add_ps(a0,a1),_mm256_add_ps(a2,a3)),_mm256_add_ps(_mm256_add_ps(_mm256_add_ps(a4,a5),_mm256_add_ps(a6,a7)),_mm256_add_ps(_mm256_add_ps(a8,a9),_mm256_add_ps(a10,a11)))); float o[8]; _mm256_storeu_ps(o,s); return o[0]; }
__attribute__((noinline)) static double run8_f64(long n){ __m256d m=_mm256_set1_pd(1.0000001),c=_mm256_set1_pd(1e-7),a0=_mm256_set1_pd(0),a1=_mm256_set1_pd(1),a2=_mm256_set1_pd(2),a3=_mm256_set1_pd(3),a4=_mm256_set1_pd(4),a5=_mm256_set1_pd(5),a6=_mm256_set1_pd(6),a7=_mm256_set1_pd(7);
  for(long i=0;i<n;i++){ D(a0)D(a1)D(a2)D(a3)D(a4)D(a5)D(a6)D(a7) }
  __m256d s=_mm256_add_pd(_mm256_add_pd(_mm256_add_pd(a0,a1),_mm256_add_pd(a2,a3)),_mm256_add_pd(_mm256_add_pd(a4,a5),_mm256_add_pd(a6,a7))); double o[4]; _mm256_storeu_pd(o,s); return o[0]; }
__attribute__((noinline)) static double run10_f64(long n){ __m256d m=_mm256_set1_pd(1.0000001),c=_mm256_set1_pd(1e-7),a0=_mm256_set1_pd(0),a1=_mm256_set1_pd(1),a2=_mm256_set1_pd(2),a3=_mm256_set1_pd(3),a4=_mm256_set1_pd(4),a5=_mm256_set1_pd(5),a6=_mm256_set1_pd(6),a7=_mm256_set1_pd(7),a8=_mm256_set1_pd(8),a9=_mm256_set1_pd(9);
  for(long i=0;i<n;i++){ D(a0)D(a1)D(a2)D(a3)D(a4)D(a5)D(a6)D(a7)D(a8)D(a9) }
  __m256d s=_mm256_add_pd(_mm256_add_pd(_mm256_add_pd(a0,a1),_mm256_add_pd(a2,a3)),_mm256_add_pd(_mm256_add_pd(a4,a5),_mm256_add_pd(_mm256_add_pd(a6,a7),_mm256_add_pd(a8,a9)))); double o[4]; _mm256_storeu_pd(o,s); return o[0]; }
__attribute__((noinline)) static double run12_f64(long n){ __m256d m=_mm256_set1_pd(1.0000001),c=_mm256_set1_pd(1e-7),a0=_mm256_set1_pd(0),a1=_mm256_set1_pd(1),a2=_mm256_set1_pd(2),a3=_mm256_set1_pd(3),a4=_mm256_set1_pd(4),a5=_mm256_set1_pd(5),a6=_mm256_set1_pd(6),a7=_mm256_set1_pd(7),a8=_mm256_set1_pd(8),a9=_mm256_set1_pd(9),a10=_mm256_set1_pd(10),a11=_mm256_set1_pd(11);
  for(long i=0;i<n;i++){ D(a0)D(a1)D(a2)D(a3)D(a4)D(a5)D(a6)D(a7)D(a8)D(a9)D(a10)D(a11) }
  __m256d s=_mm256_add_pd(_mm256_add_pd(_mm256_add_pd(a0,a1),_mm256_add_pd(a2,a3)),_mm256_add_pd(_mm256_add_pd(_mm256_add_pd(a4,a5),_mm256_add_pd(a6,a7)),_mm256_add_pd(_mm256_add_pd(a8,a9),_mm256_add_pd(a10,a11)))); double o[4]; _mm256_storeu_pd(o,s); return o[0]; }
int main(void){
  puts("dtype,gflops,seconds,chains"); long iters=300000000; volatile double sink=0;
  float (*f32[3])(long)={run8_f32,run10_f32,run12_f32}; double (*f64[3])(long)={run8_f64,run10_f64,run12_f64}; int K[3]={8,10,12};
  double best32=0,t32=0; int k32=0, best64k=0; double best64=0,t64=0;
  for(int j=0;j<3;j++){ for(int rep=0;rep<3;rep++){ double t0=now(); sink+=f32[j](iters); double t=now()-t0; double g=(double)iters*K[j]*8*2/t/1e9; if(g>best32){best32=g;t32=t;k32=K[j];} } }
  for(int j=0;j<3;j++){ for(int rep=0;rep<3;rep++){ double t0=now(); sink+=f64[j](iters); double t=now()-t0; double g=(double)iters*K[j]*4*2/t/1e9; if(g>best64){best64=g;t64=t;best64k=K[j];} } }
  printf("f32,%.2f,%.3f,%d\nf64,%.2f,%.3f,%d\n",best32,t32,k32,best64,t64,best64k); if(sink==1.2345)puts("x"); return 0; }
