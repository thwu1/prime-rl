#'XBeach Diagnostic Test Model Generator'
# Performing different checks

#%%GENERAL#####################################################################

import logging
import numpy as np
from xb_read_mpi_dims import mpidims

logger = logging.getLogger(__name__)
logger.info('checks.py is called for')

#%%CHECKS OVER WHOLE GRID######################################################

###CHECK: Bed level change###
def bedlevelchange(zb0, zbEnd):
    logger.info('Bed level check is called for')

    #processing
    zbDelta=np.mean(abs(zbEnd - zb0))

    #checking
    if zbDelta > 0:
        check = 0                                                               #check=0 means result is satisfactory
        logger.debug('check= %s', check)
    else:
        check = 1                                                               #check=1 means test has run but result is unsatisfactory
        logger.debug('check= %s --> mean of delta zb = 0', check)
    return check

###CHECK: Mass balance###
def massbalance(z0, zEnd, dx, dy, massbalancecon):                              #applicable to zs and zb
    logger.info('Mass balance is called for')

    #processing
    mass0 = z0.sum() * dx * dy
    massEnd = zEnd.sum() * dx * dy
    massbalance = massEnd - mass0
    logger.debug('massbalance= %s m3', massbalance)

    #checking
    if massbalance > massbalancecon:
        check = 1
        logger.debug('check= %s --> too much mass entering the model', check)
    elif massbalance < -massbalancecon:
        check = 1
        logger.debug('check= %s --> too much mass leaving the model', check)
    else:
        check = 0
    return check, massbalance

###CHECK: Mass balance in time###
def massbalance_intime(z, dx, dy, massbalancecon_intime):                       #applicable to zs and zb
    logger.info('Mass balance in time is called for')
    z0 = z[0,:,:]
    massbalance_intime = np.zeros(len(z[:,0,0]))

    for i in range(len(massbalance_intime)):
        #processing
        mass0 = z0.sum() * dx * dy
        massuse = z[i,:,:].sum() * dx * dy
        massbalance_intime [i] = massuse - mass0

        #checking
        if massbalance_intime[i] > massbalancecon_intime:
            check = 1
            logger.debug('check= %s --> too much mass entering the model', check)
            break
        elif massbalance_intime[i] < -massbalancecon_intime:
            check = 1
            logger.debug('check= %s --> too much mass leaving the model', check)
            break
        else:
            check = 0
    logger.debug('massbalance at final timestep= %s m3', massbalance_intime[-1])
    return check, massbalance_intime

###Making transects###
def midtrans(zb0, zbEnd, ny): #(Middle transect)
    logger.info('Middle transect (midtrans) is called for')

    if ny==0:                                                                   #For 1D cases you do not have to take a transect, also no transect in n-direction
        zb0trans_m = zb0.reshape(-1,1)
        zbEndtrans_m = zbEnd.reshape(-1,1)
        zb0trans_n = 0
        zbEndtrans_n = 0
    else:                                                                       #2D cases
        trans_m = int(round(np.shape(zbEnd)[0]/2))
        trans_n = int(round(np.shape(zbEnd)[1]/2))
        zb0trans_m = zb0[trans_m, :]
        zb0trans_n = zb0[:,trans_n]
        zbEndtrans_m = zbEnd[trans_m, :]
        zbEndtrans_n = zbEnd[:, trans_n]
    return  zb0trans_m, zbEndtrans_m, zb0trans_n, zbEndtrans_n

###Calculating slopes along transect###
def slope(zbtrans, dd, nd):                                                     #dd = dx or dy, nd = nx or ny
    slp = np.zeros(nd)
    for i in range(nd):
        slp[i] = ((zbtrans[i+1]-zbtrans[i])/dd)
    return slp

###CHECK: Slope m-direction###
def m_slope(zb0, zbEnd, nx, ny, dx, slploc, slptheo, slpcon):
    logger.info('Slope check m-direction is called for')

    #processing
    zb0trans_m, zbEndtrans_m, zb0trans_n, zbEndtrans_n = midtrans(zb0, zbEnd, ny)
    slope_m = slope(zbEndtrans_m, dx, nx)

    #checking
    for b in range(len(slploc)):
        if slope_m[slploc[b]] > slptheo[b]*(1+slpcon):
            check = 1
            logger.debug('check= %s --> slope %s > theoretical slope %s', check, slope_m[slploc[b]], slptheo[b] * (1+slpcon))
            break
        elif slope_m[slploc[b]] < slptheo[b]*(1-slpcon):
            check = 1
            logger.debug('check= %s --> slope %s < theoretical slope %s', check, slope_m[slploc[b]], slptheo[b] * (1-slpcon))
            break
        else:
            check = 0
            logger.debug('check= %s because slope= %s', check, slope_m[slploc[b]])
    return check

###CHECK: Benchmark comparison using the RMSE###
def rmse_comp(zbEndbench, zbEnd, ny, rmsecon):
    logger.info('rsme comparison is called for')
    #processing
    if len(zbEndbench) == 0:
        logger.warning('zbEndbench is empty!')
        check = 2
    else:
        diff = np.zeros(len(zbEndbench))
        for i in range(len(zbEnd)):
            diff[i] = zbEnd[i] - zbEndbench[i]

        rmse = (np.sqrt(np.mean((diff)**2)))
        logger.debug('rmse= %s', rmse)
        #checking
        if rmse > rmsecon:
            check = 1
            logger.debug('check= %s --> rmse %s > rmseconstraint %s', check, rmse, rmsecon)
        else:
            check = 0
            logger.debug('check= %s', check)

    return check

logger.info('Close checks.py')
