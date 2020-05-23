#!/opt/anaconda/bin/python -u
import sys
#sys.path.append('/opt/w2auto')
from w2auto import runWien2k

runParallel = False
runCommandPrefix = 'run-cluster-and-wait -l no -m 3000 -n 6 ' # Use "mpirun ..." or "srun ..." to run in parallel mode

common_params={
    'dosInfo' : {
        'energyInterval':[-7,2],
        'atomOrbitals':{'Fe':['d'], 'O_ATOM_3':['p'], 'O_ATOM_4':['p'], 'O_ATOM_5':['p'], 'O_ATOM_6':['p'], 'O_ATOM_8':['p'],
                        'O_ATOM_9':['p'], 'O_ATOM_10':['p'], 'O_ATOM_11':['p'], 'O_ATOM_13':['p'], 'O_ATOM_14':['p'], 'O_ATOM_15':['p'],
                        'O_ATOM_16':['p'], 'O_ATOM_18':['p'], 'O_ATOM_19':['p'], 'O_ATOM_20':['p'], 'O_ATOM_21':['p']}},
    'kpoints': 1, # 0 means auto      
    'debugMode': True
    }
                 

SCFparams ={
    'run': False,
    'struct_file': 'FeSiO4.struct',
    'runParallel': runParallel,
    'runCommandPrefix': runCommandPrefix,
    'lapwParams': {'iterNum':100, 'ec':0.0001},
    'lstart_energy': -10.5, # 0 means that will be used default value: -9.0 Ry
    'RKmax': 6, #0  means default value
    'efmod': 'GAUSS', # default value should be 'TETRA'
    'ef_eval': 0.003 # default value should be None
    }

DOSparams ={
    'run':False,
    'runParallel': runParallel,
    'runCommandPrefix': runCommandPrefix,
    'xmin' : -7 #Left border of energy for DOS plots. Default value is None
    }

BANDparams={
    'run': True,
    'runParallel': runParallel,
    'runCommandPrefix': runCommandPrefix,
    'klist_band': 'FeSiO4.klist_band'
    }

Wannierparams={
    'run': True,
    'runParallel': runParallel,
    'runCommandPrefix': runCommandPrefix,
    'wannierRunCommandPrefix': 'run-cluster-and-wait -m 3000 -n 6 ',
    'wannierName': 'wannier'
    }
                 
XTLSparams={
    'run': False,
    'hopMatBorder' : 3,
    'XTLSinput': 'Fe_2plus_XAS',
    'Xtls_path': '/opt/Xtls'
    }

params={
    'WIENROOT': '/opt/WIEN_19.1',  # set to '' if you want to use default WIEN installation (i.e. WIENROOT from environment)
    'SCF': SCFparams,
    'DOS': DOSparams,
    'BAND': BANDparams,
    'Wannier': Wannierparams,
    'XTLS': XTLSparams,
    'common': common_params
    }
runWien2k(params)
