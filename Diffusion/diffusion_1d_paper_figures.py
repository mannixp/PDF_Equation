# -*- coding: utf-8 -*-
"""Diffusion_1D_Stochastic_BCS.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/github/mannixp/PDF_Equation/blob/main/Diffusion/Diffusion_1D_Stochastic_BCS.ipynb

This notebook applies the forward Kolmogorov equation derived in *Craske J. et al. 2024* to the case of 1D scalar diffusion with boundary conditions prescribed by an Ornstein-Ulhenbeck process. The diffusion equation is solved using the open source pseudo-spectral code [Dedalus](https://dedalus-project.org/) (*Burns K.J. et. al. 2020*), while the relevant terms in the forward Kolmogorov equation are estimated using histograms.

**Setup**

This cell checks if Dedalus is installed and performs some other basic setup.
"""

import numpy as np
import scipy.stats as ss
import dedalus.public as d3
import logging
import h5py
logger = logging.getLogger(__name__)

root = logging.root
for h in root.handlers:
    h.setLevel("WARNING");

import matplotlib.pyplot as plt
plt.rcParams.update({
    "text.usetex": True,
    "font.family": "sans-serif",
    "font.sans-serif": "Helvetica",
    'text.latex.preamble': r'\usepackage{amsfonts}'
})


def OU(Y_t,W_t,dt, μ_z,a,σ):
    """
    Ornstein-Ulhenbeck process
    """

    dW_t = np.sqrt(dt) * W_t

    # Euler Maruyama
    return  Y_t + a*(μ_z - Y_t)*dt + σ * dW_t

def Solve(N=1000,T=10,Nz=24,a=10,σ=.25,W=None):

    zcoord = d3.Coordinate('z')
    dist   = d3.Distributor(zcoord, dtype=np.float64)
    zbasis = d3.ChebyshevT(zcoord, size=Nz, bounds=(0,1),dealias=3/2)

    # Fields
    Y      = dist.Field(name='Y', bases=zbasis)
    tau_Y1 = dist.Field(name='tau_Y1')
    tau_Y2 = dist.Field(name='tau_Y2')
    g0     = dist.Field(name='g0')
    g1     = dist.Field(name='g1')

    # Substitutions
    dz = lambda A: d3.Differentiate(A, zcoord)
    lift_basis = zbasis.derivative_basis(1)
    lift = lambda A: d3.Lift(A, lift_basis, -1)
    Yz = dz(Y)  + lift(tau_Y1)
    Yzz= dz(Yz) + lift(tau_Y2)

    # Problem
    problem = d3.IVP([Y, tau_Y1, tau_Y2], namespace=locals())
    problem.add_equation("dt(Y) - Yzz = 0")
    problem.add_equation("Y(z=0) = g0")
    problem.add_equation("Y(z=1) = g1")

    # Solver
    solver = problem.build_solver(d3.CNAB1)
    solver.stop_sim_time = T

    # Initial condition
    z      = dist.local_grid(zbasis)
    Y['g'] = z;

    np.random.seed(42)
    T_vec,dt = np.linspace(0,T,N,retstep=True)
    if W is None:
        W = ss.norm.rvs(loc=0, scale=1, size=(N,2))

    Y_snapshots = solver.evaluator.add_file_handler('Y_snapshots', iter=1)
    Y_snapshots.add_task(Y , layout='g',name='Y' ,scales=3/2)

    # Main loop
    logger.info('Starting main loop')
    while solver.proceed:

        n    = solver.iteration

        # Specify the bcs according to OU process
        Yt_z0    = Y(z=0).evaluate()['g'][0];
        g0['g'] = OU(Y_t = Yt_z0, W_t=W[n,0],dt=dt,μ_z=0,a=a,σ=σ)

        Yt_z1    = Y(z=1).evaluate()['g'][0]
        g1['g'] = OU(Y_t = Yt_z1, W_t=W[n,1],dt=dt,μ_z=1,a=a,σ=σ)

        solver.step(dt)

        # Capture the last 5 snapshots
        if  n == int(T/dt) - 5:
            snapshots = solver.evaluator.add_file_handler('snapshots', iter=1)
            snapshots.add_task(Y , layout='g',name='Y' ,scales=3/2)
            snapshots.add_task(Yz, layout='g',name='Yz',scales=3/2)

    return None



def density(Y_data,Range,N_bins):

  # PDF f_C
  f,y = np.histogram(Y_data[...].flatten(),range=Range,bins=N_bins,density=True); # n + 1 (-2)
  y   = 0.5*(y[1:] + y[:-1]);

  return f,y

def diffusion(dY2_data,Y_data,Range,N_bins):

  # Expectation
  # Let Φ = |∇Y|^2 and φ its dummy variable

  Y   = Y_data[...].flatten()
  dY2 = dY2_data[...].flatten()

  f_YΦ,y,φ = np.histogram2d(Y,dY2,range = (Range,(min(dY2),max(dY2))),bins=N_bins,density=True)
  φ = .5*(φ[1:]+φ[:-1]); dφ = φ[1] - φ[0];
  y = .5*(y[1:]+y[:-1]); dy = y[1] - y[0];
  f_Y =  np.sum(  f_YΦ,axis=1)*dφ;      # f_Y(y)
  E   = (np.sum(φ*f_YΦ,axis=1)*dφ)/f_Y; # E{Φ|Y} = int_φ f_Φ|Y(φ|y)*φ dφ

  return -E

def Expectation(Y,dY,y,N_bins):

    f_YΦ,_,φ = np.histogram2d(Y,dY,range = ((min(y),max(y)),(min(dY),max(dY))),bins=N_bins,density=True) # n (-3)
    φ   = .5*(φ[1:]+φ[:-1]);
    dφ  = φ[1] - φ[0];
    E   = np.sum(φ*f_YΦ,axis=1)*dφ # E{Φ|Y=y}*f(y) = int_φ f_ΦY(φ,y)*φ dφ where φ = ∇Y_t

    return E

def drift(f,y, Y0,Y1,Yz0,Yz1,N_bins):

  Ez1 = Expectation(Y1[...].flatten(),Yz1[...].flatten(),y,N_bins)
  Ez0 = Expectation(Y0[...].flatten(),Yz0[...].flatten(),y,N_bins)

  return ( Ez1 - Ez0 )/f

def Data():

  # Data loading
  file   = h5py.File('snapshots/snapshots_s1.h5', mode='r')

  # Interpolate the data (t,z) from a Chebyshev grid onto a uniform grid
  Y_cheb  = file['tasks/Y' ][:,:]
  Yz_cheb = file['tasks/Yz'][:,:]
  z_cheb  = file['tasks/Y'].dims[1][0][:]
  times   = file['tasks/Y'].dims[0][0][:]

  dz_cheb = z_cheb[1]-z_cheb[0];
  z_data  = np.arange(0,1,dz_cheb);
  s       = (len(times),len(z_data));
  Y_data  = np.zeros(s)
  Yz_data = np.zeros(s)
  for i,t in enumerate(times):
    Y_data[i,:] = np.interp(z_data, z_cheb, Y_cheb[i,:] )
    Yz_data[i,:]= np.interp(z_data, z_cheb, Yz_cheb[i,:])
  dY2_data = Yz_data**2;

  return times, z_data,Y_data,Yz_data,dY2_data;

def Generate_Ensemble(N=100,T=1,Paths=500):
   
  Solve(N,T)
  times, z_data,Y_data,Yz_data,dY2_data = Data()

  stp = (len(times),Paths)
  Y0_Data = np.zeros(stp)
  Y1_Data = np.zeros(stp)
  Y0zData = np.zeros(stp)
  Y1zData = np.zeros(stp)

  stzp = (len(times),len(z_data),Paths)
  Y_data   = np.zeros(stzp)
  #Yz_data  = np.zeros(stzp)
  dY2_data = np.zeros(stzp)

  W  = ss.norm.rvs(loc=0, scale=1, size=(N,2,Paths))

  for n in range(Paths):

    Solve(N,T,W=W[:,:,n])

    _,_,Y_n,Yz_n,dY2_n = Data()

    # z-integrated
    Y_data[:,:,n]  =   Y_n[:,:] # time,z_data
    #Yz_data[:,:,n] =  Yz_n[:,:]
    dY2_data[:,:,n]= dY2_n[:,:]

    # Boundaries
    Y0_Data[:,n] = Y_n[:, 0] # time,z=0
    Y1_Data[:,n] = Y_n[:,-1]
    Y0zData[:,n] = Yz_n[:, 0]
    Y1zData[:,n] = Yz_n[:,-1]

    if n%(Paths//5) == 0:
        print('Path = %d'%n,'\n')
  
  return Y_data,dY2_data, Y0_Data,Y1_Data,Y0zData,Y1zData



def Plot_space_time():
   
  Solve()

  # Data loading
  file  = h5py.File('Y_snapshots/Y_snapshots_s1.h5', mode='r')

  # Data (t,z)
  Y_vec  = file['tasks/Y' ][:,:]
  z_vec  = file['tasks/Y'].dims[1][0][:]
  t_vec  = file['tasks/Y'].dims[0][0][:]

  fig = plt.figure(figsize=(12,4))
  plt.contourf(t_vec,z_vec,Y_vec.T,levels=50,cmap='RdBu')
  plt.colorbar()
  plt.xlabel(r'$t$',fontsize=24)
  plt.ylabel(r'$z$',fontsize=24)
  
  
  plt.tick_params(axis='x', labelsize=20)
  plt.tick_params(axis='y', labelsize=20)

  plt.tight_layout()
  plt.savefig('Diffusion_1D_Space_Time.png',dpi=200)
  plt.show()

  return None;

def Plot_joint_density(Y0_Data,Y1_Data,Y0zData,Y1zData):

  fig, (ax1, ax2) = plt.subplots(ncols=2,sharey=True)

  ax1.hist2d(x=Y0_Data[...].flatten(), y=Y0zData[...].flatten(),bins = 20)
  ax1.set_title(r'$z=0$',fontsize=24)
  ax1.set_xlabel(r'$y$',fontsize=24)
  ax1.set_ylabel(r'$\nabla y$',fontsize=24)

  ax2.hist2d(x=Y1_Data[...].flatten(), y=Y1zData[...].flatten(),bins = 20)
  ax2.set_title(r'$z=1$',fontsize=24)
  ax2.set_xlabel(r'$y$',fontsize=24)

  for ax in [ax1,ax2]:
      ax.tick_params(axis='x', labelsize=20)
      ax.tick_params(axis='y', labelsize=20)

  plt.tight_layout()
  plt.savefig('Diffusion_1D_Joint_Density.png',dpi=200)
  plt.show()

def Plot_Terms(Y_data,dY2_data, Y0_Data,Y1_Data,Y0zData,Y1zData,N_bins=64):
  

  Range = (   min(Y_data[...].flatten()),max(Y_data[...].flatten())  );
  
  # Estimate the terms
  f,y = density(Y_data,Range,N_bins)
  D2  = diffusion(dY2_data,Y_data,Range,N_bins)
  D1  = drift(f,y, Y0_Data,Y1_Data,Y0zData,Y1zData, N_bins)

  # Derivative
  N = len(y)
  D = np.zeros((N,N))
  for i in range(N):
    if i < N - 1:
      D[i,i+1] = 1
    if i > 0:
      D[i,i-1] =-1
  D*=.5/(y[1]-y[0])

  fig, axs = plt.subplots(2, 2, layout='constrained',figsize=(12,6),sharex=True)

  axs[0,0].plot(y,D1,'k', linewidth=2,label=r'$\mathbb{D}^{(1)}(y)$')
  axs[0,1].plot(y,D2,'k', linewidth=2,label=r'$\mathbb{D}^{(2)}(y)$')

  axs[1,0].plot(y,D1*f,'k:', linewidth=2,label=r'$\mathbb{D}^{(1)} f$')
  axs[1,0].plot(y,D@(D2*f),'k--', linewidth=2,label=r'$d/dy \left( \mathbb{D}^{(2)} f \right)$')
  axs[1,0].set_xlabel(r'$y$',fontsize=24)

  axs[1,1].plot(y,f,'r', linewidth=2,label=r'$f(y)$')
  axs[1,1].fill_between(x=y,y1=f,color= "r",alpha= 0.2)
  axs[1,1].set_ylim([0,1.1*max(f)])
  axs[1,1].set_xlabel(r'$y$',fontsize=24)


  for ax in [axs[0,0],axs[1,0],axs[0,1],axs[1,1]]:
    ax.set_xlim([min(y),max(y)])
    ax.legend(loc=8,fontsize=20)
    ax.tick_params(axis='x', labelsize=20)
    ax.tick_params(axis='y', labelsize=20)

  plt.savefig('Diffusion_1D_Coefficients.png',dpi=200)
  plt.show()

  return None;


if __name__ == "__main__":

  # %%
  # %matplotlib inline

  # %%
  # plot the space time diffusion process
  Plot_space_time()

  # %%
  # # Generate Ensemble of data
  Y_data,dY2_data, Y0_Data,Y1_Data,Y0zData,Y1zData = Generate_Ensemble()

  # %%
  # # plot the joint densities
  Plot_joint_density(Y0_Data,Y1_Data,Y0zData,Y1zData)

  # # plot the terms and coefficients
  Plot_Terms(Y_data,dY2_data, Y0_Data,Y1_Data,Y0zData,Y1zData)

# %%
