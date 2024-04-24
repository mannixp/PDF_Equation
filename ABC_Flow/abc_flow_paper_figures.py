# -*- coding: utf-8 -*-
"""ABC_Flow.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/github/mannixp/PDF_Equation/blob/main/ABC_Flow.ipynb

This notebook applies the forward Kolmogorov equation derived in *Craske J. et al. 2024* to the case of a scalar concentration evolving subject to an advection diffusion equation in a triply peridioc domain. The advection diffusion equation is solved using the open source pseudo-spectral code [Dedalus](https://dedalus-project.org/) (*Burns K.J. et. al. 2020*), while the relevant terms in the forward Kolmogorov equation are estimated using histograms.
"""

import numpy as np
import dedalus.public as d3
import logging
import h5py
logger = logging.getLogger(__name__)

def solve(stop_sim_time,Nx=32):
    
    # Parameters
    κ     = 0.1;  # Equivalent to Peclet number
    A,B,C = 1,1,1;
    timestep = 1e-03

    # Domain
    coords = d3.CartesianCoordinates('x','y','z')
    dist   = d3.Distributor(coords, dtype=np.float64)
    xbasis = d3.RealFourier(coords['x'], size=Nx, bounds=(-np.pi, np.pi), dealias=3/2)
    ybasis = d3.RealFourier(coords['y'], size=Nx, bounds=(-np.pi, np.pi), dealias=3/2)
    zbasis = d3.RealFourier(coords['z'], size=Nx, bounds=(-np.pi, np.pi), dealias=3/2)

    # Fields
    S = dist.Field(name='S', bases=(xbasis,ybasis,zbasis))
    U = dist.VectorField(coords, name='U', bases=(xbasis,ybasis,zbasis))
    x,y,z = dist.local_grids(xbasis,ybasis,zbasis)

    # ABC flow
    U['g'][0] = A*np.sin(z) + C*np.cos(y);
    U['g'][1] = B*np.sin(x) + A*np.cos(z);
    U['g'][2] = C*np.sin(y) + B*np.cos(x);

    # Initial condition
    S['g']    = np.tanh(10*(x + y + z))

    # Problem
    grad_S  = d3.grad(S)
    problem = d3.IVP([S], namespace=locals())
    problem.add_equation("dt(S) - κ*div(grad_S) = -U@grad(S)") #

    # Solver
    solver = problem.build_solver(d3.RK222)
    solver.stop_sim_time = stop_sim_time

    # Flow properties
    flow = d3.GlobalFlowProperty(solver, cadence=100)
    flow.add_property(d3.Integrate(S**2)         , name='<S^2>' )
    flow.add_property(d3.Integrate(grad_S@grad_S), name='<dS^2>')

    # Main loop
    #try:
    logger.info('Starting main loop')
    while solver.proceed:
        solver.step(timestep)
        if (solver.iteration-1) % 100 == 0:

            S2_avg = flow.grid_average('<S^2>')
            dS_avg = flow.grid_average('<dS^2>' )

            logger.info('Iteration=%i, Time=%e, dt=%e'%(solver.iteration, solver.sim_time, timestep))
            logger.info('<S^2>=%f, <dS^2>    =%f'%(S2_avg,dS_avg))

        # Capture the last 5 snapshots
        if  solver.iteration == int(stop_sim_time/timestep) - 5:
            snapshots = solver.evaluator.add_file_handler('snapshots', iter=1)
            snapshots.add_task(S,      layout='g',name='Scalar',scales=3/2)
            snapshots.add_task(grad_S, layout='g',name='grad_S',scales=3/2)
    # except:
    #     logger.error('Exception raised, triggering end of main loop.')
    #     raise
    # finally:
    #     solver.log_stats()

    return None;

def Data(N_bins=256):
    
    # Data loading
    file   = h5py.File('./snapshots/snapshots_s1.h5', mode='r')
    times  = file['tasks/Scalar'].dims[0][0][:]
    x_data = file['tasks/Scalar'].dims[1][0][:]
    y_data = file['tasks/Scalar'].dims[2][0][:]
    z_data = file['tasks/Scalar'].dims[3][0][:]

    S_data   = file['tasks/Scalar'][:,...]
    dSx_data = file['tasks/grad_S'][:,0,...]
    dSy_data = file['tasks/grad_S'][:,1,...]
    dSz_data = file['tasks/grad_S'][:,2,...]
    dS2_data = dSx_data**2 + dSy_data**2 + dSz_data**2;

    # PDF f_s
    f_np2,s = np.histogram(S_data[-1,...].flatten(),bins=N_bins,density=True); # n + 2 (-1)
    f_np1,s = np.histogram(S_data[-2,...].flatten(),bins=N_bins,density=True); # n + 1 (-2)

    f_nm1,s = np.histogram(S_data[-4,...].flatten(),bins=N_bins,density=True); # n - 1 (-4)
    f_nm2,s = np.histogram(S_data[-5,...].flatten(),bins=N_bins,density=True); # n - 2 (-5)

    s       = 0.5*(s[1:] + s[:-1]); ds = s[1] - s[0];

    # Time derivate df_s/dt
    dt   = times[-1] - times[-2];
    dfdt = (-1./12.)*f_np2 + (2./3.)*f_np1 - (2./3.)*f_nm1 + (1./12.)*f_nm2;
    dfdt /=dt;

    # Expectation
    f_SΦ,s,φ = np.histogram2d(S_data[-3,...].flatten(), dS2_data[-3,...].flatten(),bins=N_bins,density=True) # n (-3)
    φ = .5*(φ[1:]+φ[:-1]); dφ = φ[1] - φ[0];
    s = .5*(s[1:]+s[:-1]); ds = s[1] - s[0];
    f_S =  np.sum(  f_SΦ,axis=1)*dφ     # f_S(s)
    E   = (np.sum(φ*f_SΦ,axis=1)*dφ)/f_S; # E{Φ|S} = int_φ f_Φ|S(φ|s)*φ dφ

    # # Derivative
    # N = len(s)
    # L = np.zeros((N,N))
    # for i in range(N):
    # L[i,i] = -2.
    # if i < N-1:
    #     L[i,i+1] = 1
    # if i > 1:
    #     L[i,i-1] = 1
    # L   *= 1./(ds**2);

    return x_data,y_data,S_data,s,f_S,E

def Plot(x_data,y_data,Y_data,y,f,E,stop_sim_time):

    # Commented out IPython magic to ensure Python compatibility.
    import matplotlib as mpl
    mpl.rcParams['xtick.major.size'] = 16
    mpl.rcParams['ytick.major.size'] = 16

    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "text.usetex": True,
        "font.family": "sans-serif",
        "font.sans-serif": "Helvetica",
        'text.latex.preamble': r'\usepackage{amsfonts}'
    })

    fig, axs = plt.subplots(1,2,figsize=(8,4))

    axs[0].pcolormesh(x_data,y_data,Y_data[-1,:,:,0],cmap='RdBu',norm='linear')
    axs[0].annotate(r'$t=%2.2f$'%stop_sim_time, xy=(-0.3,-0.3), xycoords='axes fraction',fontsize=24)

    axs[1].plot(y,f,'r', linewidth=2)
    axs[1].fill_between(x=y,y1=f,color= "r",alpha= 0.2)
    axs[1].plot(y,E,'b', linewidth=2)
    
    axs[1].set_xlim([-1,1])
    lims = [np.max(E),np.max(f)]
    axs[1].set_ylim([0.,1.1*np.max(lims)])

    #if stop_sim_time >= 2.0:
    axs[0].set_ylabel(r'$x_2$',fontsize=24)
    axs[0].set_xlabel(r'$x_1$',fontsize=24)
    axs[1].set_xlabel(r'$y$'  ,fontsize=24)
        
    for n,ax in enumerate(fig.axes):
        ax.tick_params(axis='x', labelsize=20)
        ax.tick_params(axis='y', labelsize=20)
        ax.set_box_aspect(aspect=1)

    plt.tight_layout()
    plt.savefig('ABC_Flow_t%2.2f.png'%stop_sim_time,dpi=200)

    return None;

if __name__ == "__main__":
    
    for t in [0.05,0.5,1.0,2.0]:
        solve(stop_sim_time=t,Nx=48)
        x_data,y_data,Y_data,y,f,E = Data(N_bins=128)
        Plot(x_data,y_data,Y_data,y,f,E,stop_sim_time=t)