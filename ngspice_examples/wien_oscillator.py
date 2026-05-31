"""Full characterization of the original symmetric 2-NPN clamp Wien:
  1. Supply step (Vcc +-5/+-10%) -> amplitude PSRR
  2. Temperature sweep (-20..70C) -> V_BE-driven amplitude tempco
  3. Component tolerance (Rfb, Rg, R_TOT +-1/+-5%) -> amplitude spread
alpha=0.5 nominal.
"""
import sys, subprocess, re
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
HERE=str(Path(__file__).resolve().parent)
UOPAMP=f'{HERE}/uopamp.lib'
WORK=Path('/tmp/wien_char_work'); WORK.mkdir(exist_ok=True)
OP='uopamp_lvl3 Avol=1meg GBW=10meg Rin=100g Rout=10 Iq=2m Ilimit=20m Vos=0'
Q3904='''.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF=416.4 NE=1.259
+ ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0 IKR=0 RC=1
+ CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p MJE=.2593 VJE=.75
+ TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)'''
R_TOT=240e3; T_STEP=2.0

def netlist(tag, temp=25, vstep=0.0, k_rfb=1.0, k_rg=1.0, k_rtot=1.0, alpha=0.5, T_end=4.0):
    rtop=(1-alpha)*R_TOT*k_rtot; rbot=alpha*R_TOT*k_rtot
    vcc=f'9*(time>{T_STEP} ? {1+vstep:.5f} : 1)'
    dat=(WORK/f'{tag}.data').as_posix()
    return f"""* Wien char {tag}
.include {UOPAMP}
{Q3904}
.options temp={temp}
B_vcc vcc 0 V = {vcc}
B_vee vee 0 V = -1*({vcc})
R1 v_osc ns 10k
C1 ns np 15.915n IC=0
R2 np 0 10k
C2 np 0 15.915n IC=10m
Rg nn 0 {10e3*k_rg:.6g}
Rfa nn fb 10k
Rfb fb v_osc {12e3*k_rfb:.6g}
Q1 fb b1 v_osc Q2N3904
Q2 v_osc b2 fb Q2N3904
Rtop1 fb b1 {rtop:.6g}
Rbot1 b1 v_osc {rbot:.6g}
Rtop2 v_osc b2 {rtop:.6g}
Rbot2 b2 fb {rbot:.6g}
XU_osc np nn vcc vee v_osc {OP}
.tran 20u {T_end} 0 uic
.options reltol=1e-4 abstol=1n vntol=1u
.save v(v_osc)
.control
run
wrdata {dat} v(v_osc)
.endc
.end
"""

def envelope(t,x,win=2e-3):
    tg=np.arange(t[0],t[-1],win);amp=np.empty(len(tg))
    for i,tt in enumerate(tg):
        m=(t>=tt)&(t<tt+win);amp[i]=np.max(np.abs(x[m])) if m.any() else np.nan
    return tg,amp

def measure(path):
    d=np.loadtxt(path); t=d[:,0]; v=d[:,1]
    tg,amp=envelope(t,v)
    A_pre=np.nanmean(amp[(tg>=1.5)&(tg<2.0)])
    A_post=np.nanmean(amp[(tg>=3.5)&(tg<4.0)])
    # THD post
    m=(t>=3.0)&(t<4.0); ts=t[m]-t[m][0]; vs=v[m]
    dt=20e-6; tu=np.arange(0,ts[-1],dt); vu=np.interp(tu,ts,vs); vu=vu-np.mean(vu)
    F=np.abs(np.fft.rfft(vu*np.hanning(len(vu)))); fr=np.fft.rfftfreq(len(vu),dt)
    band=(fr>800)&(fr<1100); fc=fr[band][np.argmax(F[band])]
    def a(f):
        sb=np.sin(2*np.pi*f*tu);cb=np.cos(2*np.pi*f*tu);return np.hypot(2*np.mean(vu*sb),2*np.mean(vu*cb))
    lo,hi=fc-5,fc+5;phi=(np.sqrt(5)-1)/2
    for _ in range(35):
        x1=hi-phi*(hi-lo);x2=lo+phi*(hi-lo)
        if a(x1)>a(x2):hi=x2
        else:lo=x1
    f0=(lo+hi)/2;H={k:a(k*f0) for k in range(1,11)}
    thd=np.sqrt(sum(H[k]**2 for k in range(2,11)))/H[1]
    return float(A_pre),float(A_post),float(f0),float(thd*100)

def run_one(args):
    tag,kw=args
    (WORK/f'{tag}.cir').write_text(netlist(tag,**kw))
    r=subprocess.run(['ngspice','-b',f'{tag}.cir'],cwd=WORK,capture_output=True,text=True,timeout=300)
    if r.returncode!=0: return tag,kw,None
    try: return tag,kw,measure(WORK/f'{tag}.data')
    except Exception as e: return tag,kw,('ERR',str(e))

CASES=[]
# supply steps
for v in (0.05,-0.05,0.10,-0.10): CASES.append((f'sup{int(v*100):+d}',dict(vstep=v)))
# temperature
for T in (-20,0,25,50,70): CASES.append((f'temp{T}',dict(temp=T)))
# component tolerance (individually +-5%, +-1%)
for k in (0.95,0.99,1.01,1.05):
    CASES.append((f'rfb{int(k*100)}',dict(k_rfb=k)))
    CASES.append((f'rg{int(k*100)}',dict(k_rg=k)))
    CASES.append((f'rtot{int(k*100)}',dict(k_rtot=k)))

print(f'Running {len(CASES)} characterization cases, p=16',flush=True)
res={}
with ProcessPoolExecutor(max_workers=16) as ex:
    futs={ex.submit(run_one,c):c for c in CASES}
    for f in as_completed(futs):
        tag,kw,m=f.result(); res[tag]=(kw,m)

def amp(tag):
    kw,m=res[tag]
    if m is None or m[0]=='ERR': return None
    return m

print()
print('=== 1. SUPPLY STEP (Vcc step at t=2s) ===')
print(f'{"step":>6} {"A_pre":>7} {"A_post":>7} {"dA%":>7} {"f0":>7} {"THD%":>6}')
for v in (0.05,-0.05,0.10,-0.10):
    m=amp(f'sup{int(v*100):+d}')
    if m: print(f'{v*100:>+5.0f}% {m[0]:>7.4f} {m[1]:>7.4f} {(m[1]-m[0])/m[0]*100:>+7.4f} {m[2]:>7.1f} {m[3]:>6.3f}')

print()
print('=== 2. TEMPERATURE (amplitude tempco) ===')
print(f'{"T(C)":>6} {"A_post":>7} {"f0":>7} {"THD%":>6}')
A25=None
for T in (-20,0,25,50,70):
    m=amp(f'temp{T}')
    if m:
        if T==25: A25=m[1]
        print(f'{T:>6} {m[1]:>7.4f} {m[2]:>7.1f} {m[3]:>6.3f}')
if A25:
    m20=amp('temp-20'); m70=amp('temp70')
    if m20 and m70:
        tc=(m70[1]-m20[1])/A25/(70-(-20))*100
        print(f'  amplitude tempco ~ {tc:+.4f} %/C  ({(m70[1]-m20[1])/A25*100:+.2f}% over -20..70C)')

print()
print('=== 3. COMPONENT TOLERANCE (amplitude spread) ===')
print(f'{"param":>6} {"-5%":>8} {"-1%":>8} {"+1%":>8} {"+5%":>8}  (A_post V)')
for p in ('rfb','rg','rtot'):
    row=[]
    for k in (95,99,101,105):
        m=amp(f'{p}{k}')
        row.append(f'{m[1]:>8.4f}' if m else '    FAIL')
    print(f'{p:>6} {row[0]} {row[1]} {row[2]} {row[3]}')
# nominal ref
mn=amp('temp25')
if mn: print(f'  (nominal A = {mn[1]:.4f} V)')
