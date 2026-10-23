// Multi-threaded bandwidth + loaded-latency generator. Each load thread streams over its OWN private buffer of WS bytes.
// membw --ws B --threads T --pattern seq|rand --stride B --read PCT --delay D --secs S --cpus a,b,c [--lat_ws B]
//  stride: bytes between consecutive 64-B line touches (64 = dense stream; 256/1024 = sparse)
//  read PCT: % of line operations that are reads (rest are full-line writes), e.g. 100/70/50/0
//  delay D: spin iterations between line ops (injection-rate control => throughput/latency sweep)
//  lat_ws: if >0, one extra thread (first CPU in list) runs a 1-chain random pointer chase over lat_ws bytes while load runs
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <pthread.h>
#include <sched.h>
#include <sys/mman.h>
#ifdef __AVX2__
#include <immintrin.h>
#endif
static double now(void){ struct timespec t; clock_gettime(CLOCK_MONOTONIC_RAW,&t); return t.tv_sec+1e-9*t.tv_nsec; }
static volatile int stop_flag=0; static pthread_barrier_t bar;
typedef struct { int cpu,rnd,readpct; size_t ws,stride; long delay; uint64_t seed,lines,sink; char*buf; void*start; double lat_ns; uint64_t loads; int is_lat; } W;
static void pin(int cpu){ cpu_set_t s; CPU_ZERO(&s); CPU_SET(cpu,&s); pthread_setaffinity_np(pthread_self(),sizeof s,&s); }
static void* worker(void*a){ W*w=a; pin(w->cpu); size_t nl=w->ws/64, sl=w->stride/64, pos=0, phase=0; uint64_t rs=w->seed,s=0,cnt=0; char*b=w->buf; int rp=w->readpct, ph=0; long dl=w->delay;
#ifdef __AVX2__
  __m256i acc=_mm256_setzero_si256(); const __m256i v=_mm256_set1_epi64x(0x0123456789abcdefLL);   // explicit 2 x 32 B per 64 B line (v1: scalar 8 x 8 B, which capped cache-resident bandwidth)
#endif
  pthread_barrier_wait(&bar);
  while(!stop_flag){ for(int k=0;k<1024;k++){ size_t line;
      if(w->rnd){ rs^=rs<<13; rs^=rs>>7; rs^=rs<<17; line=(size_t)(((rs>>32)*(uint64_t)nl)>>32); }   // multiply-high range reduction (v1 used rs%nl = a 64-bit DIV per access, 20+ cycles)
      else { line=pos; pos+=sl; if(pos>=nl){ phase=(phase+1)%sl; pos=phase; } }
      char*p=b+line*64;
      if(ph<rp){
#ifdef __AVX2__
        acc=_mm256_add_epi64(acc,_mm256_load_si256((const __m256i*)p)); acc=_mm256_add_epi64(acc,_mm256_load_si256((const __m256i*)(p+32)));
#else
        const uint64_t*q=(const uint64_t*)p; s+=q[0]+q[1]+q[2]+q[3]+q[4]+q[5]+q[6]+q[7];
#endif
      } else {
#ifdef __AVX2__
        _mm256_store_si256((__m256i*)p,v); _mm256_store_si256((__m256i*)(p+32),v);
#else
        uint64_t*q=(uint64_t*)p; q[0]=cnt;q[1]=cnt;q[2]=cnt;q[3]=cnt;q[4]=cnt;q[5]=cnt;q[6]=cnt;q[7]=cnt;
#endif
      }
      if(++ph==100) ph=0; cnt++; for(long d=0;d<dl;d++) __asm__ volatile("add $0,%0":"+r"(s)); } }
#ifdef __AVX2__
  { uint64_t t[4]; _mm256_storeu_si256((__m256i*)t,acc); s+=t[0]+t[1]+t[2]+t[3]; }
#endif
  w->lines=cnt; w->sink=s; return 0; }
static void* latworker(void*a){ W*w=a; pin(w->cpu); void**p=w->start; size_t n=0; pthread_barrier_wait(&bar); double t0=now();
  while(!stop_flag){ for(int k=0;k<10000;k++) p=*(void***)p; n+=10000; } double e=now()-t0; w->lat_ns=e/n*1e9; w->loads=n; w->sink=(uint64_t)p; return 0; }
static char* big(size_t n){ char*p=mmap(0,n,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0); if(p==MAP_FAILED){perror("mmap");exit(1);} madvise(p,n,MADV_HUGEPAGE); memset(p,1,n); return p; }
int main(int argc,char**argv){
  if(argc>1&&!strcmp(argv[1],"--header")){ puts("ws_bytes,threads,pattern,stride,readpct,delay,secs,bw_GBps,Mlines_s,lat_ns,lat_loads"); return 0; }
  size_t ws=1<<28,stride=64,lat_ws=0; int T=1,rnd=0,rp=100,cpus[256],nc=0; long delay=0; double secs=3;
  for(int i=1;i+1<argc;i+=2){ char*k=argv[i],*v=argv[i+1];
    if(!strcmp(k,"--ws"))ws=strtoull(v,0,10); else if(!strcmp(k,"--threads"))T=atoi(v); else if(!strcmp(k,"--pattern"))rnd=!strcmp(v,"rand"); else if(!strcmp(k,"--stride"))stride=strtoull(v,0,10);
    else if(!strcmp(k,"--read"))rp=atoi(v); else if(!strcmp(k,"--delay"))delay=atol(v); else if(!strcmp(k,"--secs"))secs=atof(v); else if(!strcmp(k,"--lat_ws"))lat_ws=strtoull(v,0,10);
    else if(!strcmp(k,"--cpus")){ char*s=strdup(v),*t=strtok(s,","); while(t&&nc<256){ cpus[nc++]=atoi(t); t=strtok(0,","); } } }
  int extra=lat_ws?1:0; if(nc==0){ for(int i=0;i<T+extra;i++) cpus[nc++]=i; } if(nc<T+extra){ fprintf(stderr,"need %d cpus\n",T+extra); return 2; }
  if(stride<64) stride=64;
  pthread_t th[256]; W w[256]; pthread_barrier_init(&bar,0,T+extra+1);
  if(extra){ size_t nn=lat_ws/64; char*b=big(lat_ws); uint32_t*o=malloc(nn*4); uint64_t r=88172645463325252ULL; for(size_t i=0;i<nn;i++)o[i]=i;
    for(size_t i=nn-1;i>0;i--){ r^=r<<13;r^=r>>7;r^=r<<17; size_t j=r%i; uint32_t t=o[i];o[i]=o[j];o[j]=t; }
    for(size_t i=0;i<nn;i++) *(void**)(b+(size_t)o[i]*64)=b+(size_t)o[(i+1)%nn]*64; w[255]=(W){0}; w[255].cpu=cpus[0]; w[255].start=b+(size_t)o[0]*64; free(o); pthread_create(&th[255],0,latworker,&w[255]); }
  for(int i=0;i<T;i++){ w[i]=(W){0}; w[i].cpu=cpus[i+extra]; w[i].ws=ws; w[i].stride=stride; w[i].rnd=rnd; w[i].readpct=rp; w[i].delay=delay; w[i].seed=0x9E3779B97F4A7C15ULL*(i+1); w[i].buf=big(ws); pthread_create(&th[i],0,worker,&w[i]); }
  pthread_barrier_wait(&bar); double t0=now(); struct timespec ts={(time_t)secs,(long)((secs-(time_t)secs)*1e9)}; nanosleep(&ts,0); stop_flag=1; double el=now()-t0;
  uint64_t tot=0; for(int i=0;i<T;i++){ pthread_join(th[i],0); tot+=w[i].lines; } if(extra) pthread_join(th[255],0);
  printf("%zu,%d,%s,%zu,%d,%ld,%.1f,%.3f,%.2f,%.2f,%lu\n",ws,T,rnd?"rand":"seq",stride,rp,delay,secs,tot*64.0/el/1e9,tot/el/1e6,extra?w[255].lat_ns:-1.0,extra?w[255].loads:0UL); return 0; }
