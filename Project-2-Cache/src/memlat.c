// Pointer-chasing latency benchmark. One process = one config, `reps` repetitions. CSV on stdout.
// memlat WS_BYTES [--gran B] [--pattern rand|seq] [--chains K] [--huge 0|1] [--reps R]   |  memlat --freq  |  memlat --header
//  rand: one random single-cycle permutation of nodes spaced `gran` bytes apart (defeats prefetchers)
//  seq : node i -> node i+1 (stride = gran bytes; prefetcher-friendly => pitfall demo)
//  chains K: K independent chains walked in lockstep = K outstanding misses (memory-level parallelism)
//  gran 4096 => one node per 4 KiB page: isolates TLB reach (footprint in cache is only WS/4096 lines)
//  huge 1/0: madvise(MADV_HUGEPAGE / MADV_NOHUGEPAGE) (needs THP enabled=madvise|always)
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <sys/mman.h>
static double now(void){ struct timespec t; clock_gettime(CLOCK_MONOTONIC_RAW,&t); return t.tv_sec+1e-9*t.tv_nsec; }
static uint64_t rs=0x9E3779B97F4A7C15ULL; static inline uint64_t rnd(void){ rs^=rs<<13; rs^=rs>>7; rs^=rs<<17; return rs; }

// Core-clock estimate from two dependent chains whose latency is architecturally known: reg+reg ADD (1 cycle) and IMUL (3 cycles).
// (v1 used `add $imm`: recent cores fold immediate-add chains in the renamer, which gave an impossible 13 GHz in testing.)
static double est_ghz_add(void){ uint64_t n=300000000ULL, x=1, y=1; double t0=now();
  __asm__ volatile("1: add %2,%0\n add %2,%0\n add %2,%0\n add %2,%0\n add %2,%0\n add %2,%0\n add %2,%0\n add %2,%0\n sub $1,%1\n jnz 1b":"+r"(x),"+r"(n):"r"(y):"cc");
  return 8.0*300000000ULL/(now()-t0)/1e9; }
static double est_ghz_imul(void){ uint64_t n=100000000ULL, x=3, y=3; double t0=now();
  __asm__ volatile("1: imul %2,%0\n imul %2,%0\n imul %2,%0\n imul %2,%0\n imul %2,%0\n imul %2,%0\n imul %2,%0\n imul %2,%0\n sub $1,%1\n jnz 1b":"+r"(x),"+r"(n):"r"(y):"cc");
  return 3.0*8*100000000ULL/(now()-t0)/1e9; }
static long thp_kb(void){ FILE*f=fopen("/proc/self/smaps_rollup","r"); if(!f) return -1; char l[256]; long kb=-1; while(fgets(l,256,f)) if(!strncmp(l,"AnonHugePages:",14)) sscanf(l+14,"%ld",&kb); fclose(f); return kb; }
static char *alloc(size_t bytes,int huge){ size_t al=2u<<20, sz=(bytes+al-1)/al*al; char*p=mmap(0,sz+al,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
  if(p==MAP_FAILED){ perror("mmap"); exit(1); } char*a=(char*)(((uintptr_t)p+al-1)&~(uintptr_t)(al-1)); madvise(a,sz,huge?MADV_HUGEPAGE:MADV_NOHUGEPAGE); return a; }

#define CH(K) static __attribute__((noinline)) void* chase##K(void**st,size_t it){ void*p[K]; for(int j=0;j<K;j++)p[j]=st[j]; \
  for(size_t i=0;i<it;i++){ for(int j=0;j<K;j++) p[j]=*(void**)p[j]; } uintptr_t r=0; for(int j=0;j<K;j++) r^=(uintptr_t)p[j]; return (void*)r; }
CH(1) CH(2) CH(3) CH(4) CH(6) CH(8) CH(12) CH(16)
static void* run(int K,void**st,size_t it){ switch(K){case 1:return chase1(st,it);case 2:return chase2(st,it);case 3:return chase3(st,it);case 4:return chase4(st,it);
  case 6:return chase6(st,it);case 8:return chase8(st,it);case 12:return chase12(st,it);case 16:return chase16(st,it);} fprintf(stderr,"chains must be 1,2,3,4,6,8,12,16\n"); exit(2); }

int main(int argc,char**argv){
  if(argc>1&&!strcmp(argv[1],"--header")){ puts("ws_bytes,gran,pattern,chains,huge,thp_kb,rep,lat_ns,thr_Mloads_s,iters"); return 0; }
  if(argc>1&&!strcmp(argv[1],"--freq")){ double g=0,h=0; for(int i=0;i<3;i++){ double x=est_ghz_add(), y=est_ghz_imul(); if(x>g)g=x; if(y>h)h=y; } printf("%.3f %.3f\n",g,h); return 0; }   // add-chain GHz, imul-chain GHz (should agree within a few %)
  if(argc<2){ fprintf(stderr,"usage\n"); return 2; }
  size_t ws=strtoull(argv[1],0,10), gran=64; int K=1,huge=0,reps=5; int seq=0;
  for(int i=2;i+1<argc;i+=2){ if(!strcmp(argv[i],"--gran")) gran=strtoull(argv[i+1],0,10); else if(!strcmp(argv[i],"--pattern")) seq=!strcmp(argv[i+1],"seq");
    else if(!strcmp(argv[i],"--chains")) K=atoi(argv[i+1]); else if(!strcmp(argv[i],"--huge")) huge=atoi(argv[i+1]); else if(!strcmp(argv[i],"--reps")) reps=atoi(argv[i+1]); }
  size_t nn=ws/gran; if(nn<(size_t)(K*4)){ fprintf(stderr,"ws too small\n"); return 2; }
  char*buf=alloc(ws,huge); memset(buf,1,ws);                       // touch every page now (THP decision happens here)
  uint32_t*ord=malloc(nn*4),*nxt=malloc(nn*4);
  for(size_t i=0;i<nn;i++) ord[i]=i;
  if(!seq){ for(size_t i=nn-1;i>0;i--){ size_t j=rnd()%i; uint32_t t=ord[i]; ord[i]=ord[j]; ord[j]=t; } }  // Sattolo shuffle => single cycle when linked in order
  for(size_t i=0;i<nn;i++) nxt[ord[i]]=ord[(i+1)%nn];
  #define NODE(i) ((void**)(buf+(size_t)(i)*gran+(gran>=4096?((size_t)(i)*64)%gran:0)))   // stagger offsets only for page-sized granules (TLB test) to avoid cache-set aliasing; for 256/1024 B granules the stride must stay exact
  for(size_t i=0;i<nn;i++) *NODE(i)=NODE(nxt[i]);
  void*st[16]; uint32_t cur=0; size_t step=nn/K; for(int j=0;j<K;j++){ st[j]=NODE(cur); for(size_t s=0;s<step;s++) cur=nxt[cur]; }
  free(ord); free(nxt);
  long thp=thp_kb(); void*sink=run(K,st,nn<50000000?nn:50000000);  // warm: one full traversal (capped)
  size_t it=100000; double t=0; for(;;){ double a=now(); sink=run(K,st,it); t=now()-a; if(t>0.1||it>(1ull<<33)) break; it*=4; }
  it=(size_t)(it*0.2/t); if(it<1000) it=1000;
  for(int r=0;r<reps;r++){ double a=now(); sink=run(K,st,it); double e=now()-a;
    printf("%zu,%zu,%s,%d,%d,%ld,%d,%.3f,%.2f,%zu\n",ws,gran,seq?"seq":"rand",K,huge,thp,r,e/it*1e9,(double)K*it/e/1e6,it); }
  if(sink==(void*)1) puts("x"); return 0; }
