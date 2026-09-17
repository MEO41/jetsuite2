import sys, numpy as np
fn=sys.argv[1]; w=float(sys.argv[2])
d=np.loadtxt(fn,delimiter=",",skiprows=1); d=d[np.argsort(d[:,0].astype(int))]
X=d[:,1:4]; rho=d[:,4]; mom=d[:,5:8]; E=d[:,8]; V=mom/rho[:,None]; V2=(V**2).sum(1); p=0.4*(E-0.5*rho*V2); T=p/(287.058*rho); Tt=T+V2/2009.0
r=np.hypot(X[:,1],X[:,2]); ct=(V[:,2]*X[:,1]-V[:,1]*X[:,2])/np.maximum(r,1e-9)
NI,NJ,NK=41,13,13; ids=np.arange(NI*NJ*NK).reshape(NI,NJ,NK)
def st(i):
    F=0; s_rc=0; s_Tt=0; s_pt=0
    for j in range(NJ-1):
        for k in range(NK-1):
            q=[ids[i,j,k],ids[i,j+1,k],ids[i,j+1,k+1],ids[i,j,k+1]]; pts=X[q]; n=0.5*np.cross(pts[2]-pts[0],pts[3]-pts[1]); f=abs(np.dot(mom[q].mean(0),n))
            F+=f; s_rc+=(r[q]*ct[q]).mean()*f; s_Tt+=Tt[q].mean()*f; s_pt+=(p[q]*(Tt[q]/T[q])**3.5).mean()*f
    return F, s_rc/F, s_Tt/F, s_pt/F
Fi,rci,Tti,pti=st(0); Fo,rco,Tto,pto=st(NI-1)
print(f"W {Fi:.4f}/{Fo:.4f}; Euler dTt {abs(w*(rco-rci))/1004.5:.2f} K; measured dTt {Tto-Tti:.2f} K; PR_tt {pto/pti:.4f} -> isentropic dTt {Tti*((pto/pti)**(1/3.5)-1):.2f} K; interior T {T[ids[10:31,2:11,2:11]].min():.0f}..{T[ids[10:31,2:11,2:11]].max():.0f} K, walls {min(T[ids[:,0,:]].min(),T[ids[:,:,0]].min()):.0f}..{max(T[ids[:,-1,:]].max(),T[ids[:,:,-1]].max()):.0f} K")
