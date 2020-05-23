#!/opt/anaconda/bin/python -u
import sys
#sys.path.append('/opt/w2auto')
from w2auto import runWien2k

runParallel = False
runCommandPrefix = 'run-cluster-and-wait -l no -m 3000 -n 6 ' # Use "mpirun ..." or "srun ..." to run in parallel mode

common_params={
    'dosInfo' : {
        'energyInterval':[-7,2],
        'atomOrbitals':{'FeM':['d'], 'FeT':['d'], 'O':['p']}},
    'kpoints': 0, # 0 means auto      
    'debugMode': True
    }
                 

SCFparams ={
    'run': False,
    'struct_file': 'Fe3O4.struct',
    'runParallel': runParallel,
    'runCommandPrefix': runCommandPrefix,
    'lapwParams': {'iterNum':100, 'ec':0.0001},
    'lstart_energy': -9.0, # 0 means that will be used default value: -9.0 Ry
    'RKmax': 7, #0  means default value
    'efmod': 'TETRA', # default value should be 'TETRA'
    'ef_eval': None # default value should be None
    }

DOSparams ={
    'run': False,
    'runParallel': runParallel,
    'runCommandPrefix': runCommandPrefix,
    'xmin' : -10 #Left border of energy for DOS plots. Default value is None
    }

BANDparams={
    'run': True,
    'runParallel': runParallel,
    'runCommandPrefix': runCommandPrefix,
    'klist_band': 'Fe3O4.klist_band'
    }

Wannierparams={
    'run': True,
    'runParallel': runParallel,
    'runCommandPrefix': runCommandPrefix,
    'wannierRunCommandPrefix': 'run-cluster-and-wait -m 3000 -n 6 ',
    'wannierName': 'wannier'
    }
                 
XTLSparams={
    'run': True,
    'hopMatBorder' : 3,
    'XTLSinput': 'Fe_2plus_XAS',
    'Xtls_path': '/opt/Xtls',
    'structInfo': {'atomNamesList': ['FeT', 'FeM', 'O'],
                   'kpoints':1,
                   'atomCounts': {'FeM': 4, 'FeT': 2, 'O': 8}}
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
