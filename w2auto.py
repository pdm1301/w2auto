#!/opt/anaconda/bin/python -u
import sys, os, subprocess, shutil, tempfile, socket, copy, re, urllib, glob, random, string, json
import numpy as np
import pandas as pd
import scipy, scipy.optimize
from io import StringIO

tryFastGlobal = True
join = os.path.join
comandLogSeparator = ('='*80+'\n')*3 + ('='*79+'-\n')

def escape_argument(arg):
    if not arg or re.search(r'(["\s])', arg):
        arg = '"' + arg.replace('"', r'\"') + '"'

    return escape_for_cmd_exe(arg)

def escape_for_cmd_exe(arg):
    meta_chars = '()%!^"<>&|'
    meta_re = re.compile('(' + '|'.join(re.escape(char) for char in list(meta_chars)) + ')')
    meta_map = { char: "^%s" % char for char in meta_chars }

    def escape_meta_chars(m):
        char = m.group(1)
        return meta_map[char]

    return meta_re.sub(escape_meta_chars, arg)
  
def notEmpty(filename):
    if os.path.exists(filename): return os.path.getsize(filename)>0
    else: return False

class Cache:
    def __init__(self, workDir):
        self.workDir = workDir
        self.cacheFile = self.workDir + '/.cache'
        self.load()
        
    def load(self):
        if os.path.exists(self.cacheFile):
            self.cache = self.from_JSON()
        else:
            self.cache = []
            self.save()
        
    def save(self):
        with open(self.workDir + '/.cache', 'w') as f: json.dump(self.to_JSON(), f)

    def findSameState(self, cmd):
        sameStateCacheLine = None # 
        for cacheLine in self.cache:
            if cacheLine.cmd == cmd:
                output, code = runCommand('git diff --quiet --exit-code ' + str(cacheLine.inState), self.workDir, tryFast = False, returnCode=True)
                if code == 0:
                    sameStateCacheLine = cacheLine
                    break
        if sameStateCacheLine is not None:
            print('Command {0} was found in cache'.format(sameStateCacheLine.cmd))
        else: print('Command {0} was not found in cache'.format(cmd))
        return sameStateCacheLine
      
    def add(self, cacheLine):
        self.cache.append(cacheLine)
        self.save()
        
    def to_JSON(self):
        json_pack = []
        for cache_line in self.cache:
            json_pack.append({'cmd' : cache_line.cmd,
                              'inState' : cache_line.inState,
                              'outState' : cache_line.outState,
                              'output' : cache_line.output})
        return json_pack
    
    def from_JSON(self):
        with open(self.cacheFile, 'r') as f:
                json_cache = json.load(f)
        temp_cache = []
        for cache_line in json_cache:
            temp_cache.append(CacheLine(cache_line['cmd'], cache_line['inState'], cache_line['outState'], cache_line['output']))
        return temp_cache

class CacheLine:
    def __init__(self, cmd, inState, outState, output):
        self.cmd = cmd
        self.inState = inState
        self.outState = outState
        self.output = output


def saveState(workDir, cmd, stage):
    runCommand('git add -A .', workDir, tryFast = False)
    runCommand('git commit --allow-empty-message --no-edit', workDir, tryFast = False, returnCode=True)
    state = runCommand('git log --pretty=format:"%H"', workDir, tryFast = False).split("\n")[0]
    print('save {0} state for command: {1}'.format(stage, cmd))
    return state


def restoreState(workDir, state):
    print('restore state for command: {0}'.format(state.cmd))
    runCommand('git checkout ' + state.outState + ' .', workDir, tryFast = False)


def runCommand(cmd, workDir, prefix = '', canRedirectOutputToFile=True, env=None, tryFast=tryFastGlobal, returnCode=False, w2webTrueDir=None):
    
    cmdWorkDir = workDir
    if w2webTrueDir is not None:  workDir = w2webTrueDir
    
    if 'run-cluster' in prefix:
        canRedirectOutputToFile = False
      
    if canRedirectOutputToFile:
        f = tempfile.NamedTemporaryFile(delete=False)
        f.close()
        postfix = ' > '+f.name+' 2>&1'
    else: postfix = ''
    
    if tryFast:
        cache = Cache(workDir)
        sameStateCacheLine = cache.findSameState(cmd)
        if sameStateCacheLine is not None:
            restoreState(workDir, sameStateCacheLine)
            output = sameStateCacheLine.output
        else:
            prevState = saveState(workDir, cmd, 'input')
    
    if (not tryFast) or (tryFast and (sameStateCacheLine is None)):
        prefix = prefix.strip()
        if prefix=='':
            fullCommand = cmd+' '+postfix
        else:
            fullCommand = prefix+' "'+cmd+'" '+postfix
        procInfo = subprocess.run(fullCommand, cwd=cmdWorkDir, shell=True, env=env)
        
        if postfix != '':
            with open(f.name, 'rb') as myfile:
                output = myfile.read()
                output = output.decode('utf8', 'ignore')
            os.remove(f.name)
        else: 
            output = ''
            if 'run-cluster' in prefix:
                files = glob.glob(workDir+'/slurm*.out'); files.sort()
                if len(files) == 0: raise Exception('Error: can\'t find slurm*.out file in folder '+workDir)
                with open(files[-1], 'r') as myfile: output = myfile.read()
                output = output[:output.find('================================= SLURM INFO')]
                
        if debugMode:
            debugLog.write(comandLogSeparator + cmd + '\n')            
            if 'git diff' in cmd: debugLog.write('output size = '+str(len(output))+'\n')
            else: debugLog.write(output+'\n')
        if returnCode: return output, procInfo.returncode
        if procInfo.returncode !=0:
            raise Exception('Error while executing command ' + prefix + ' "'+cmd+'":\n'+output)
      
    if tryFast and (sameStateCacheLine is None):
        nextState = saveState(workDir, cmd, 'output')
        cache.add(CacheLine(cmd, prevState, nextState, output))

    return output


def prepareW2WebEmulation(parentDir=None):
    if parentDir is None: d = tempfile.TemporaryDirectory()
    else: 
        d = join(os.path.realpath(parentDir), 'w2webEmulator')
        os.makedirs(d, exist_ok=True)
    d = os.path.abspath(d)
    hostname = runCommand('hostname -f','.', tryFast = False).strip()
    if hostname=='': hostname = socket.gethostname()
    w2webInstallFolder = join(d,'.w2web',hostname)
    os.makedirs(w2webInstallFolder, exist_ok=True)
    os.makedirs(join(w2webInstallFolder,'conf'), exist_ok=True)
    os.makedirs(join(w2webInstallFolder,'logs'), exist_ok=True)
    os.makedirs(join(w2webInstallFolder,'sessions'), exist_ok=True)
    os.makedirs(join(w2webInstallFolder,'tmp'), exist_ok=True)
    with open(join(w2webInstallFolder,'conf','w2web.conf'), "w") as text_file:
        text_file.write('''port=7965
host=''' + hostname + '''
master_url=
realm=w2web
passdelay=3
log=0
logtime=60
logfile=''' + join(w2webInstallFolder,'logs','w2web.log') + '''
pidfile=''' + join(w2webInstallFolder,'logs','w2web.pid') + '''
userfile=''' + join(w2webInstallFolder,'conf','w2web.users') + '''
keyfile=''' + join(w2webInstallFolder,'conf','w2web.pem') + '''
debug=0
''')
    with open(join(w2webInstallFolder,'conf','w2web.users'), "w") as text_file:
        text_file.write('user:Ib0fIWrVewRJo\n')
    caseBaseDir = join(d,'caseBaseDir')
    os.makedirs(caseBaseDir, exist_ok=True)
    wienroot = os.environ['WIENROOT']
    htdocs = join(wienroot, 'SRC_w2web/htdocs')
    env = {}
    for k, v in os.environ.items(): env[k] = v
    env['HOME'] = d
    env['W2WEB_CASE_BASEDIR'] = caseBaseDir
    env['W2WEB'] = w2webInstallFolder
    env['DOCUMENT_ROOT'] = htdocs
    env['WIENROOT'] = wienroot
    env['SERVER_NAME'] = hostname
    w2webContext = {'HOME':d, 'w2webInstallFolder':w2webInstallFolder, 'caseBaseDir':caseBaseDir, 'env':env}    
    return w2webContext

def runW2webCommand(htdocsFileName0, params, w2webContext, workDir, method='GET', tryFast = True):
    wienroot = os.environ['WIENROOT']
    htdocs = join(wienroot, 'SRC_w2web/htdocs')
    if htdocsFileName0[0]=='/': htdocsFileName = htdocsFileName0[1:]
    else: htdocsFileName = htdocsFileName0
    cmd0 = join(htdocs, htdocsFileName)
    env = copy.deepcopy(w2webContext['env'])
    if isinstance(params,str): webParams = params
    else:
        keys = list(params.keys()); keys.sort()
        sorted_params = [(key, params[key]) for key in keys]
        webParams = urllib.parse.urlencode(sorted_params)
    env['SCRIPT_NAME'] = htdocsFileName0
    env['HTTP_REFERER'] = ''
    if method=='GET':
        env['QUERY_STRING'] = webParams
        env['REQUEST_METHOD'] = 'GET'
        cmd = 'QUERY_STRING="'+ webParams + '" '+cmd0
        output = runCommand(cmd0, os.path.dirname(cmd0), '', True, env, tryFast=False, w2webTrueDir=workDir)
    else:
        env['REQUEST_METHOD'] = 'POST'
        env['CONTENT_LENGTH'] = str(len(webParams))
        f = tempfile.NamedTemporaryFile(delete=False)
        f.write(str.encode(webParams))
        f.close()
        cmd = 'echo -n "'+webParams+'" | '+cmd0
        #cmd = 'cat ' + f.name + ' | '+cmd0
        output = runCommand(cmd, os.path.dirname(cmd0), '', True, env, tryFast=False, w2webTrueDir=workDir)
        os.remove(f.name)
    if debugMode:
        debugLog.write(comandLogSeparator + htdocsFileName0+'\nparams = ' + str(params) + '\nMETHOD = '+method+'\n')
        debugLog.write(output+'\n')
    return output

def newSession(workDir, w2webContext):
    sessionName = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
    output = runW2webCommand('/session/new.cgi', {'NEWNAME':sessionName}, w2webContext, workDir, tryFast = False)
    foundRes = re.search('dir.pl\?.*SID=(\d+)\&', output)
    if foundRes is None:
        raise Exception('Error while executing command "/session/new.cgi":\n'+output)
    else: SID = foundRes.group(1)
    output = runW2webCommand('/session/save.cgi', {'SID':SID, 'dir':workDir}, w2webContext, workDir, tryFast = False)
    return SID, sessionName

def parseStructFile(structFile):
    #Serch names of atoms in struct file
    with open(structFile, 'r') as myfile: structFileContent = myfile.read()
    atomNamesList = re.findall(r'[\n\s]+(\D\s?\S*)\s+NPT', structFileContent, flags = re.IGNORECASE)
    atomNamesList = list(map(lambda a: a.strip(), atomNamesList))
    
    atomNumbers = re.findall(r'ATOM\s+\-?(\d+)\:', structFileContent, flags = re.IGNORECASE)
    assert len(atomNumbers) == len(atomNamesList)
    
    atomNamesList1 = []
    for i in range(len(atomNamesList)):
        if atomNamesList.count(atomNamesList[i]) > 1:
            atomNamesList1.append(atomNamesList[i]+'_ATOM_'+atomNumbers[i])
        else:
            atomNamesList1.append(atomNamesList[i])
    atomNamesList = atomNamesList1
    
    #count the number of each atom
    counts = re.findall(r'[.*\s][-\s]+(\d+)[:+]', structFileContent, flags = re.IGNORECASE)
    
    #make elements in counts list integers, not string for correct sort in np.unique
    for i in range(len(counts)):
        counts[i] = int(counts[i])
        
    unique, unique_counts = np.unique(counts, return_counts=True)
    assert len(unique_counts) == len(atomNamesList)
    atomCounts={}
    for i in range(len(atomNamesList)):
        if atomNamesList[i] in atomCounts:
            atomCounts[atomNamesList[i]]+=unique_counts[i]
        else:
            atomCounts[atomNamesList[i]]=unique_counts[i]
    atomNamesListUnique = []
    for a in atomNamesList:
        if a not in atomNamesListUnique: atomNamesListUnique.append(a)
    atomNamesList = atomNamesListUnique
    #Count number of kpoints
    foundRes = re.search(r'MODE OF CALC=RELA unit=bohr', structFileContent, flags = re.IGNORECASE)
    if foundRes is None:
        raise Exception('String "MODE OF CALC=RELA unit=bohr" is absent in struct file. May be you are using another units?":\n')
    cellSize=re.search(r'unit=.*[\s\n]*(\d+.\d+)\s+(\d+.\d+)\s+(\d+.\d+)', structFileContent, flags = re.IGNORECASE)
    
    divider=1
    bohrToAngstrom=1.88973
    for i in range(1,4):
        divider*=float(cellSize.group(i))/bohrToAngstrom/5
    kpoints=int((2000//divider)+1)
    result = {'atomNamesList':atomNamesList, 'kpoints':kpoints, 'atomCounts':atomCounts}
	
    parse_file_log = open('parse_log.txt', 'w')
    for information in result.keys():
        parse_file_log.write(information + '\n')
        parse_file_log.write(str(result[information]) +'\n')
	
    return result

def getSID(workDir, w2webContext):
    if os.path.exists(workDir + '/.session'):
        with open(workDir+'/.session', 'r') as SIDfile: sessionParams = SIDfile.read().splitlines()      
        SID = sessionParams[0]
        sessionName = sessionParams[1]
    else:
        SID, sessionName = newSession(workDir, w2webContext)
        with open(workDir+'/.session', 'w') as SIDfile: SIDfile.write(SID + '\n' + sessionName)
    return SID, sessionName

ignoreFiles = ['.git', '.gitignore', '.cache', '.session']
def prepareDirectory(workDir):
    rmAllExceptIgnore(workDir)
    os.makedirs(workDir, exist_ok=True)
    if not os.path.exists(workDir+'/.git'):
        with open(workDir+'/.gitignore', 'w') as f: f.write(":*\n.*\n")
        runCommand('git init', workDir, tryFast = False)
        runCommand('git add .', workDir, tryFast = False)
        runCommand('git add -f .gitignore', workDir, tryFast = False)
        #=====================================================
        runCommand('git commit -m "initial commit"', workDir, tryFast = False)
        #=====================================================

def mycopy(src, dst):
    if os.path.isdir(src): shutil.copytree(src, dst)
    else: shutil.copy(src, dst)

def copyAllFiles(srcDir, dstDir):
    for f in os.listdir(srcDir):
        if (f not in ignoreFiles) and (f[0] not in ['.',':']):
            mycopy(srcDir+'/'+f, dstDir)

def rmAllExceptIgnore(workDir):
    if os.path.exists(workDir):
        for f in os.listdir(workDir):      
            if f not in ignoreFiles:
                #remove file
                if os.path.isfile(workDir+'/'+f): os.unlink(workDir+'/'+f )
                #remove directory
                if os.path.isdir(workDir+'/'+f): shutil.rmtree(workDir+'/'+f)

def SCF(structureFile0, w2webContext, runParallel, runCommandPrefix, lapwParams, kpoints, rkmax = 0, lstart_energy = 0, efmod='TETRA', ef_eval=None, iqtlsave=False):
    print('SCF running...')
    parentDir = w2webContext['caseBaseDir']
    fileName, fileExtension = os.path.splitext(structureFile0)
    fileName = os.path.basename(fileName)
    structureFile = fileName+fileExtension
    workDir = parentDir + '/' + fileName
    
    prepareDirectory(workDir)
    SID, sessionName = getSID(workDir, w2webContext)

    assert os.path.exists(structureFile0), 'File '+structureFile0+' doesn\'t exist'
    shutil.copyfile(structureFile0, workDir+'/'+structureFile)
   

    def saveStructure(output):
        foundRes = re.findall(r'INPUT.*?NAME=\"(.*?)\".*?VALUE=\"(.*?)\"', output, flags = re.IGNORECASE)
        params = { r[0]:r[1] for r in foundRes }
        foundRes = re.findall(r'INPUT.*?NAME=\"(.*?)\".*?VALUE=\s*([^\s\"]+?)[\s\>]', output, flags = re.IGNORECASE)
        for r in foundRes: params[r[0]] = r[1]
        #foundRes = re.search(r'"s_lattice"[\s\S]*?value=(\d+\_.*?)[^\>]?selected', output, flags = re.IGNORECASE)
        foundRes = re.search(r'"s_lattice"[\s\S]*?value=([\d\w_/]+)[^\>]?selected', output, flags = re.IGNORECASE)
        if foundRes is None:
            raise Exception('Error while search s_lattice in output of command "/util/structgen.pl":\n'+output)
        params['s_lattice'] = foundRes.group(1)
        #Search 's_nsym'
        foundRes = re.search(r'\"s_nsym\">\n.*OPTION.*VALUE=\"(.*?)\"', output, flags = re.IGNORECASE)
        if foundRes is not None: params['s_nsym']=foundRes.group(1)
        
        #Lattice parameters:1)ang  2)bohr 
        foundRes=re.search(r'Lattice parameters[\s\S]*value="(.*)".*selected', output, flags = re.IGNORECASE)
        params['unit']=foundRes.group(1)
        params['complex'] = 'CHECKED'  
        
        output = runW2webCommand('/util/structsave.pl', params, w2webContext, workDir, method='POST')
        return output
    
    
    #======================== struct ======================================
    if fileExtension=='.cif':
        output = runW2webCommand('/util/structask.pl', {'SID':SID}, w2webContext, workDir, method='GET')
        output = runW2webCommand('/util/structask.pl', {'SID':SID, 'DIR':workDir, 'doit':'1', 'NAME':fileName, 'complex':'CHECKED', 'numatoms':'2', 'ciffil':structureFile, 'TIME':'Wed Oct  3 16:14:37 2018', 'ALERT':'', 'spinpol':'', 'afm':'', 'p':'', 'COMMENT':'', 'SESSION_EXPERT_RED':'', 'SESSION_EXPERT_VXC':'', 'SESSION_EXPERT_ECUT':'', 'SESSION_EXPERT_RKMAX':'', 'SESSION_EXPERT_FERMIT':'', 'SESSION_EXPERT_MIX':'', 'SESSION_EXPERT_NUMK':''}, w2webContext, workDir, method='POST')
        shutil.copyfile(structureFile0, workDir+'/'+structureFile)
    else: 
        assert fileExtension=='.struct', 'Use only .cif or .struct files'
        output = runW2webCommand('/util/structstart.pl', {'SID':SID}, w2webContext, workDir, method='GET')

    output = runW2webCommand('/util/structgen.pl', {'SID':SID}, w2webContext, workDir, method='GET')
    
    output = saveStructure(output)
    
    output = runW2webCommand('/util/structrmt.pl', 'doit=1&SID='+SID+'&reduc=0&orig=', w2webContext, workDir, method='POST')
    output = runW2webCommand('/util/structgen.pl', {'SID':SID}, w2webContext, workDir, method='GET')
    
    #  Save structure
    output = saveStructure(output)
    # save file and clean up (when you are done)
    output = runW2webCommand('/util/structend.pl', {'SID':SID}, w2webContext, workDir, method='GET')
    output = runW2webCommand('/util/structgen.pl', {'SID':SID}, w2webContext, workDir, method='GET')
            
    #x nn
    enters = "\n"*22
    cmd = "echo '2"+enters+"' | x nn"
    output = runCommand(cmd, workDir)
            
    if output.lower().find('error')>=0:
        raise Exception('Error while executing command "'+cmd+'":\n'+output)
    #Check that command "x nn" worked correctly
    foundRes=re.findall(r'SUMS\sTO\s([\d\.]*).*NN-DIST=\s([\d\.]*)\S*', output, flags = re.IGNORECASE)
    for r in foundRes:
        if float(r[0])>=float(r[1]):
            raise Exception('Error! SUMS TO >= NN-DIST\n')
    #x sgroup
    output = runCommand('x sgroup', workDir)
    #x symmetry
    output = runCommand("echo '' | x symmetry", workDir)
    #copy struct_st
    shutil.copyfile(workDir+'/'+fileName+'.struct_st', workDir+'/'+fileName+'.struct')
    
    structInfo = parseStructFile(workDir+'/'+fileName+'.struct')
    w2webContext['structInfo'] = structInfo
    if kpoints>0:
         w2webContext['structInfo']['kpoints'] = kpoints
    
    #instgen_lapw
    output = runCommand("echo '\n\n"+" u\n"*len(structInfo['atomNamesList'])+enters+"' | instgen_lapw", workDir)
    #x lstart
    exchangeCorrelationPotential={'PBE-GGA (Perdew-Burke-Ernzerhof 96)':'13',
                                  'LSDA':'5',
                                  'WC-GGA (Wu-Cohen 06)':'11',
                                  'PBEsol-GGA (Perdew etal 08)':'19'}
    
    energy = -9.0 if lstart_energy == 0 else lstart_energy
    
    cmd="echo '"+str(exchangeCorrelationPotential['PBE-GGA (Perdew-Burke-Ernzerhof 96)'])+"\n"+str(energy)+enters+"' | x lstart"
    try:
        output = runCommand(cmd, workDir)
    except Exception:
        print('ERROR in command "x lstart".\nPlease, correct energy level for "x lstart" command!\nCurrent energy level is ', energy)
        exit(0)
    
    output = runW2webCommand('/exec/initlapw.pl', {'SID':SID,'phase':'10'}, w2webContext, workDir, method='GET')
    
    #Set RKMAX parameter
    if rkmax!=0:
        current_file = fileName + '.in1_st'
        if os.path.exists(workDir + '/' + current_file):
            print('correcting:',workDir + '/' + current_file)
            with open(workDir + '/' + current_file, 'r') as file_in:
                fileContent = file_in.read()
            result = re.sub(pattern = r'(.*\(WFFIL, WFPRI, ENFIL, SUPWF\)\s+)(\d+[.\d]*)', repl = '\g<1>' + str(rkmax), string = fileContent)
            with open(workDir + '/' + current_file, 'w') as file_out:
                file_out.write(result)
        else:
            print('ERROR: file ' + fileName + '.in1_st does not exist!')
            exit(0)
    
    #Change EF-method
    if efmod != 'TETRA':
        current_file = fileName + '.in2_st'
        if os.path.exists(workDir + '/' + current_file):
            with open(workDir + '/' + current_file, 'r') as file_in:
                fileContent = file_in.read()
            result = re.sub(pattern = r'^(TETRA)', repl = efmod, string = fileContent, flags=re.MULTILINE)
            #Change eval value of EF_model
            if ef_eval is not None:
                result = re.sub(pattern = r'(^\S{5}\s+)([\d.]+)', repl = '\g<1>{0}'.format(ef_eval), string = result, flags=re.MULTILINE)
            with open(workDir + '/' + current_file, 'w') as file_out:
                file_out.write(result)
        else:
            print('ERROR:file ' + fileName + '.in2 does not exist!')
            exit(0)
            
    if iqtlsave:
        current_file = fileName + '.in2_st'
        if os.path.exists(workDir + '/' + current_file):
            with open(workDir + '/' + current_file, 'r') as file_in:
                fileContent = file_in.read()
            result = re.sub(pattern = r'([\s\S]*[-\d.+ ]{4} )(1)([\s]+EMIN[\s\S]+)', repl = '\g<1>0\g<3>', string = fileContent, flags=re.MULTILINE)
            with open(workDir + '/' + current_file, 'w') as file_out:
                file_out.write(result)
        else:
            print('ERROR:file ' + fileName + '.in2 does not exist!')
            exit(0)
        
        
    # x kgen
    output = runCommand("echo ' \n"+str(structInfo['kpoints'])+"\n\n\n\n\n1"+enters+"' | x kgen", workDir)
            
    output = runW2webCommand('/exec/initlapw.pl', {'SID':SID,'phase':'15', 'doit':'1'}, w2webContext, workDir, method='GET')

    #x dstart
    output = runCommand("x dstart", workDir)
            
    if output.lower().find('error')>=0:
        if os.path.exists(workDir+'/dstart.error'):
            with open(workDir+'/dstart.error', 'r') as myfile: output += "\n" + myfile.read()
        raise Exception('Error while executing command x dstart:\n'+output)
    
    #copy .in0_std -> .in0
    shutil.copyfile(workDir+'/'+fileName+'.in0_std', workDir+'/'+fileName+'.in0')
    
    #change NR2V to R2V for generating *.vtotal file for hybridization
    current_file = fileName + '.in0'
    if os.path.exists(workDir + '/' + current_file):
        with open(workDir + '/' + current_file, 'r') as file_in:
            fileContent = file_in.read()
        result = re.sub(pattern=r'(NR2V)([\s\S]*)', repl='R2V' + '\g<2>', string=fileContent)
        with open(workDir + '/' + current_file, 'w') as file_out:
            file_out.write(result)
    else:
        raise Exception('File ' + current_file + ' was not found!')
    
    
    output = runW2webCommand('/exec/initlapw.pl', {'SID':SID,'phase':'20'}, w2webContext, workDir, method='GET')
            
    #For BaCoP2O7 change *.in1 file to correct
    if fileName=='BaCoP2O7':
        shutil.copyfile('BaCoP2O7.in1', workDir+'/BaCoP2O7.in1')
    parallel = ' -p' if runParallel else ''
    cmd = 'run_lapw -i '+str(lapwParams['iterNum'])+' -ec '+str(lapwParams['ec']) + parallel
    output = runCommand(cmd, workDir=workDir, prefix=runCommandPrefix)
    if output.find('energy in SCF NOT CONVERGED')>=0:
        raise Exception('Energy in SCF NOT CONVERGED')
    if output.lower().find('error')>=0:
        raise Exception('Error while executing command '+cmd+':\n'+output)
    return workDir

def DOS(workDirSCF, w2webContext, runParallel, runCommandPrefix, xmin=None):
    print('DOS running...')
    parentFolder = os.path.dirname(workDirSCF)
    taskName = os.path.basename(workDirSCF)
    workDir = parentFolder + '/' + taskName + '_DOS'
    workDir += '/' + taskName
    prepareDirectory(workDir)
    copyAllFiles(workDirSCF, workDir)
    SID, sessionName = getSID(workDir, w2webContext)
    
    #x lapw1
    parallel = ' -p' if runParallel else ''
    output = runCommand("echo ''|x lapw1"+parallel, workDir=workDir, prefix=runCommandPrefix)
    if (output.lower().find('error')>=0) or notEmpty(workDir+'/lapw1.error'):
        with open(workDir+'/lapw1.error', 'r') as myfile: error = myfile.read()
        print(error)
        raise Exception('Error while executing command x lapw1'+parallel+':\n'+output)
    
    # x lapw2 -qtl
    output = runCommand("echo ''|x lapw2 -qtl"+parallel, workDir)
    if (output.lower().find('error')>=0) or notEmpty(workDir+'/lapw2.error'):
        with open(workDir+'/lapw2.error', 'r') as myfile: error = myfile.read()
        print(error)
        raise Exception('Error while executing command x lapw2 -qtl'+parallel+':\n'+output)

    # Configure input-file, command: "configure taskName.inp"
    structInfo = w2webContext['structInfo']
    atomNumb=len(structInfo['atomNamesList'])
    enters = "\n"*22

    picDir = workDir+'/pics'
    if os.path.exists(picDir): shutil.rmtree(picDir)
    os.makedirs(picDir, exist_ok=True)
            
    #Draw DOS plot
    def drawDOSPlot(atomIndex):
        config = str(atomIndex+1) + " tot,s,p,d"
        output = runCommand("echo '"+enters+"'|configure_int_lapw -b total "+config+" end", workDir)
        
        #Extend boundary of DOS plots
        current_file = taskName + '.int'
        if os.path.exists(workDir + '/' + current_file):
            with open(workDir + '/' + current_file, 'r') as file_in:
                fileContent = file_in.read()
            result = re.sub(pattern = r'^\W+(-[.\d]+)(\W+[\d.]+\W+[\d.]+.*#Emin)', repl = ' -1.50\g<2>', string = fileContent, flags=re.MULTILINE)
            result = re.sub(pattern = r'(^\W+-[.\d]+\W+[\d.]+\W+)([\d.]+)(.*#Emin)', repl = '\g<1>1.500\g<3>', string = result, flags=re.MULTILINE)
            with open(workDir + '/' + current_file, 'w') as file_out:
                file_out.write(result)
            
        # x tetra
        output = runCommand("echo ''|x tetra", workDir)
        
        xmin_str = str(xmin) if xmin is not None else '-10'
        params={'xmin':xmin_str, 'xmax':'10', 'ymin':'', 'ymax':'', 'doit':'1', 'plot':'1', 'dos_col1':'1', 'NAME':sessionName, 'SID':SID,'HOSTNODE':'', 'DIR':workDir, 'ALERT':'', 'TIME':'Wed Oct  3 16:14:37 2018', 'spinpol':'', 'afm':'', 'complex':'', 'p':'', 'COMMENT':'', 'SESSION_EXPERT_RED':'', 'SESSION_EXPERT_VXC':'', 'SESSION_EXPERT_ECUT':'', 'SESSION_EXPERT_RKMAX':'', 'SESSION_EXPERT_FERMIT':'', 'SESSION_EXPERT_MIX':'', 'SESSION_EXPERT_NUMK':'', 'units':'1', 'color':'1', 'dos_lsize':'24'}
        for i in range(4):
            params['dos_col'+str(i+1)] = str(2+i)
            
        params['dos_label1']=''
        params['dos_linetyp1']='1'
        params['dos_linewidth1']='1'
        
        output = runW2webCommand('/exec/dos.pl', params, w2webContext, workDir, method='POST')
        
        foundRes=re.search(r'\<IMG\s+SRC=(/tmp/.*?.png)', output, flags = re.IGNORECASE)
        img = foundRes.group(1)
        img = w2webContext['w2webInstallFolder']+img
        ps = os.path.splitext(img)[0]+'.ps'
        #fileName = 'total' if atomIndex<0 else atoms[atomIndex]
        fileName = 'total' if atomIndex<0 else structInfo['atomNamesList'][atomIndex]+'_'+str(atomIndex)
        if os.path.exists(img): shutil.copy(img, picDir+'/'+fileName+'.png')
        else: print('Warning: file '+img+' doesn\'t exist')
        if os.path.exists(ps): shutil.copy(ps, picDir+'/'+fileName+'.ps')
        else: print('Warning: file '+ps+' doesn\'t exist')
        
    for atomIndex in range(0,atomNumb): drawDOSPlot(atomIndex)

def Bandstructure(workDirSCF, klist_band_file, w2webContext, runParallel, runCommandPrefix, efmod='TETRA'):
    print('Bandstructure running...')
    parentFolder = os.path.dirname(workDirSCF)
    taskName = os.path.basename(workDirSCF)
    workDir = parentFolder + '/' + taskName + '_Bandstructure'
    workDir += '/' + taskName
    prepareDirectory(workDir)
    copyAllFiles(workDirSCF, workDir)
    SID, sessionName = getSID(workDir, w2webContext)

    shutil.copy(klist_band_file, workDir+'/'+taskName+'.klist_band')
    
    # x lapw1 -band
    parallel = ' -p' if runParallel else ''
    output = runCommand("echo ''|x lapw1 -band"+parallel, workDir=workDir, prefix=runCommandPrefix)
        
    if (output.lower().find('error')>=0) or notEmpty(workDir+'/lapw1.error'):
        with open(workDir+'/lapw1.error', 'r') as myfile: error = myfile.read()
        print(error)
        raise Exception('Error while executing command x lapw1 -band'+parallel+':\n'+output)


    # x irrep
    #output = runCommand("echo ''|x irrep"+parallel, workDir)

    # x lapw2 -band -qtl
    output = runCommand("echo ''|x lapw2 -band -qtl"+parallel, workDir)
    if (output.lower().find('error')>=0) or notEmpty(workDir+'/lapw2.error'):
        with open(workDir+'/lapw2.error', 'r') as myfile: error = myfile.read()
        print(error)
        raise Exception('Error while executing command x lapw2 -band -qtl'+parallel+':\n'+output)
        
    output = runW2webCommand('/exec/band.pl', {'SID':SID, 'next':'continue', 'interactive':'on'}, w2webContext, workDir, method='POST')

    # Insert correct EF( "BUTTON" edit taskName.insp file)
  
    scfFile=workDir+'/'+taskName+'.scf'
    with open(scfFile, 'r') as myfile: scfFileContent = myfile.read()
    foundRes = re.findall(r'F E R M I - ENERGY\(.+\)=\s*([\d\.\+\-]*)', scfFileContent, flags = re.IGNORECASE)
    energy=str(foundRes[-1]).strip()
    if energy == '':
        raise Exception('Error: can\'t parse sENERGY({0}) in file '.format(efmod)+scfFile)
        
    inspFile=workDir+'/'+taskName+'.insp'
    with open(inspFile, 'r') as file_in:
        inspFileContent = file_in.read()

    inspFileContent = inspFileContent.replace("0.xxxx", energy)

    with open(inspFile, 'w') as file_out:
        file_out.write(inspFileContent)
    
    # x spaghetti
    output = runCommand("echo ''|x spaghetti"+parallel, workDir)
        
    output = runW2webCommand('/exec/band.pl', {'doit':'1', 'plot':'1', 'NAME':sessionName, 'SID':SID,'HOSTNODE':'', 'DIR':workDir, 'ALERT':'', 'TIME':'Wed Oct  3 16:14:37 2018', 'spinpol':'', 'afm':'', 'complex':'', 'p':'', 'COMMENT':'', 'SESSION_EXPERT_RED':'', 'SESSION_EXPERT_VXC':'', 'SESSION_EXPERT_ECUT':'', 'SESSION_EXPERT_RKMAX':'', 'SESSION_EXPERT_FERMIT':'', 'SESSION_EXPERT_MIX':'', 'SESSION_EXPERT_NUMK':''}, w2webContext, workDir, method='POST')
        
    foundRes=re.search(r'\<IMG\s+SRC=(/tmp/.*?.jpg)', output, flags = re.IGNORECASE)
    img = foundRes.group(1)
    img = w2webContext['w2webInstallFolder']+img
    ps = os.path.splitext(img)[0]+'.ps'
    if not os.path.exists(img) and not os.path.exists(ps): raise Exception('Spaghetti picture file was not generated!')
    if os.path.exists(img): shutil.copy(img, workDir)
    if os.path.exists(ps): shutil.copy(ps, workDir)
    
    return workDir
    
def analyseDOS(workDirDOS):
    dosInfo = {'energyInterval':[-11,2], 'atomOrbitals':{'FeT':['d'], 'FeM':['d'], 'O':['p']}}
    return dosInfo

def Wannier(taskName, workDirBandstructure, energyInterval, atomOrbitals, w2webContext, runParallel, runCommandPrefix, wannierRunCommandPrefix):
    print('Wannier running...')
    workDir = workDirBandstructure+'/'+taskName
    enters = "\n"*22
    prepareDirectory(workDir)
    
    output = runCommand("echo '"+enters+"' | prepare_w2wdir "+taskName, workDirBandstructure, tryFast=False)
    structInfo = w2webContext['structInfo']
    output = runCommand("echo '"+str(structInfo['kpoints']*2)+"\n0\n"+enters+"' | x kgen -fbz", workDir)
    
    
    correctBandCount = 0
    counts = {'s':1, 'p':3, 'd':5}
    proj = ''
    atomList = [] 
    for an in structInfo['atomNamesList']: atomList += [an]*structInfo['atomCounts'][an]
    # order of atoms and orbitals must be the same as in function XTLS !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    for a in structInfo['atomNamesList']:
        if a not in atomOrbitals: continue
        for orb in atomOrbitals[a]:
            correctBandCount += counts[orb]*structInfo['atomCounts'][a]
            ind = np.where(np.array(atomList) == a)[0]
            for i in ind: proj += str(i+1) + ':' + orb + "\n"
    
    e1 = str(energyInterval[0]); e2 = str(energyInterval[1])
    output = runCommand("x findbands -all "+e1+" "+e2, workDir)
        
    findbandsFile = workDir + '/' + taskName+'.outputfind'
    with open(findbandsFile, 'r') as myfile: findbandsFileContent = myfile.read()
    i = findbandsFileContent.find("\n \n")
    bands = pd.read_csv(StringIO(findbandsFileContent[:i]), sep='\s+', names=['k-point', 'first', 'last', 'bands'], skiprows=2, header=None)
    ind = bands['bands'].values == correctBandCount
    if True not in ind:
        print('Wrong count of K-points\' bands!\n')
        print('Expected band: '+str(correctBandCount))
        print('Actual bands: {0}'.format(np.unique(bands['bands'].values)))
        print('You should {0} energy interval.'.format('extend' if correctBandCount>max(bands['bands'].values) else 'narrow')+ 'Current energy interval is ['+e1+';'+e2+']')
        exit(0)      
    first = bands['first'].values[ind]
    last = bands['last'].values[ind]
    bandCounts = bands['bands'].values[ind]
    unique, unique_indices, unique_counts = np.unique(first, return_index=True, return_counts=True)
    i = np.argmax(unique_counts)
    bestFirst = first[unique_indices[i]]
    bestLast = last[unique_indices[i]]
    assert bestLast-bestFirst+1 == correctBandCount, 'first = ' + str(bestFirst) + ' last = '+str(bestLast)+' correctBandCount = '+str(correctBandCount)
    output = runCommand("echo '"+str(bestFirst)+' '+str(bestLast)+"\n"+proj+"' | write_inwf", workDir)
    
    correctInitializing = str(correctBandCount) +" bands, " + str(correctBandCount)+" initial projections"
    if correctInitializing in output:
        print('write_inwf command worked correctly\nCorrect bandCount=' + str(correctBandCount))
    else:
        print('ERROR:\n Number of correctBandCount: ' + str(correctBandCount) + '  does not match to founded bands:' + str(bestLast-bestFirst+1))
        exit(0)
    #write_win
    output = runCommand("write_win", workDir)
        
    winFile=workDir+'/'+taskName+'.win'
    with open(winFile, 'r') as file_in:
        winFileContent = file_in.read()

    winFileContent = winFileContent.replace("hr_plot                = .true.", "write_hr               = .true.")

    with open(winFile, 'w') as file_out:
        file_out.write(winFileContent)
        
    #x wannier90 -pp
    wannier_prefix = wannierRunCommandPrefix if runParallel else ''
    output = runCommand("x wannier90 -pp ", workDir=workDir, prefix=wannier_prefix)
        
    #x lapw1
    parallel = ' -p' if runParallel else ''
    output = runCommand("x lapw1" + parallel, workDir=workDir, prefix=runCommandPrefix)

    threads = os.cpu_count()
    #x w2w
    if runParallel:
        w2w_threads = min([threads, 12])
        output = runCommand("OMP_NUM_THREADS="+str(w2w_threads)+" x w2w -p", workDir=workDir, prefix='')
    else:
        output = runCommand("x w2w ", workDir=workDir, prefix='')
    
    #x wannier90
    if runParallel:
        output = runCommand("wannier90.x " + taskName + '.win', workDir=workDir, prefix=wannierRunCommandPrefix)    
    else:
        output = runCommand("OMP_NUM_THREADS=1 x wannier90", workDir=workDir, prefix='')
        
    output = runCommand("echo \"set term png\nset output '1.png'\nset yrange ["+str(energyInterval[0]-2)+":"+str(energyInterval[1]+2)+"]\nplot '"+taskName+r".spaghetti_ene' using (\$4/0.529189):5, '"+taskName+"_band.dat' with lines\nexit\n\" | gnuplot", workDir)
    
    return workDir

# =====================================================================================================================================
def TriDiag(folder):
    def constructV(x,n):
        V = np.eye(n)
        c = np.cos(x)
        s = np.sin(x)
        inds = [[0,1], [0,2], [0,3], [0,4], [1,2], [1,3], [1,4], [2,3], [2,4], [3,4]]
        K = len(inds)
        for k in range(K):
            Q = np.eye(n)
            i = inds[k][0]+5
            j = inds[k][1]+5
            Q[i][i]=c[k]
            Q[i][j]=-s[k]
            Q[j][i]=s[k]
            Q[j][j]=c[k]
            V = np.dot(V,Q)
        k = K
        for i in range(5,10):
            for j in range(10,n):
                Q = np.eye(n)
                Q[i][i]=c[k]
                Q[i][j]=-s[k]
                Q[j][i]=s[k]
                Q[j][j]=c[k]
                V = np.dot(V,Q)
                k = k+1
        return V

    def targetF(x,A):
        n,m = A.shape
        inds = [[0,1], [0,2], [0,3], [0,4], [1,2], [1,3], [1,4], [2,3], [2,4], [3,4]]
        K = len(inds)
        V = constructV(x,n)
        Vt = np.transpose(V)
        D = np.dot(Vt,A)
        D = np.dot(D,V)
        y = np.zeros(2*K+5)
        for k in range(K):
            i = inds[k][0]
            j = inds[k][1]
            y[k] = D[i][j+5] - D[j][i+5]
            y[k+K] = D[i][j+5]
        dd = [3, 3, 3, 3, 3]
        for i in range(5):
            y[2*K+i] = D[i][i+5]-dd[i]
        return np.linalg.norm(y)**2

    A0 = np.loadtxt(folder+'/HopMat.dat')
    n,sz = A0.shape
    if n<10:
        with open(folder + '/info.txt', 'a') as f: f.write('Error:\nSize of HopMat < 10\n')
        return 1
    m = 5
    Apart = A0[:m,:m]
    eigs, Vpart = np.linalg.eig(Apart) #% D = V'*A*V
    ind = np.argsort(eigs)
    Vpart = Vpart[:,ind]
    V0 = np.eye(n,n)
    V0[:m,:m] = Vpart
    V0t = np.transpose(V0)
    A = np.dot(V0t,A0)
    A = np.dot(A,V0)
    sol = scipy.optimize.minimize(targetF, np.zeros((10+(n-10)*5,1)), args=(A), method='BFGS', tol=1e-04, options={'maxiter':100000})
    #print(sol)
    x = sol.x
    V = constructV(x,n)
    Vt = np.transpose(V)
    D = np.dot(Vt,A)
    D = np.dot(D,V)
    V = np.dot(V,V0)
    Vt = np.transpose(V)
    np.savetxt(folder+'/matr_diag.txt',D,delimiter=' ', fmt='%6.3f');
    np.savetxt(folder+'/matr_perehod.txt',V,delimiter=' ', fmt='%6.3f');
    Dcheck = np.dot(Vt,A0)
    Dcheck = np.dot(Dcheck,V)
    q=1.0/np.sqrt(2)
    TSph2CubD = np.array([[q, 0, 0, 0, -q], [0, q, 0, -q, 0], [0, q, 0, q, 0], [q, 0, 0, 0, q], [0, 0, 1, 0, 0]])
    Tdd = np.dot(np.transpose(V[:5,:5]),TSph2CubD)
    np.savetxt(folder+"/Tdd.input.mat", Tdd, delimiter=" ", fmt='%6.3f')

    # remove diagonalization of the d-block
    D1 = np.dot(V0,D)
    V0t = np.transpose(V0)
    D1 = np.dot(D1,V0t)
    # transfer to the spherical harmonics
    TSph2CubD1 = np.eye(n,n)
    TSph2CubD1[:5,:5] = TSph2CubD
    Tsph2CubD1_transposed = np.transpose(TSph2CubD1)
    D1spher = np.dot(Tsph2CubD1_transposed,D1)
    D1spher = np.dot(D1spher,TSph2CubD1)

    np.savetxt(folder+"/matr_diag_spher.txt", D1spher, delimiter=" ", fmt='%6.3f')
    np.savetxt(folder+"/HsphereDD.dat", D1spher[:5,:5], delimiter=" ", fmt='%6.3f')
    np.savetxt(folder+"/HsphereLD.dat", D1spher[5:10,:5], delimiter=" ", fmt='%6.3f')
    np.savetxt(folder+"/HsphereDL.dat", D1spher[:5,5:10], delimiter=" ", fmt='%6.3f')
    np.savetxt(folder+"/HsphereLL.dat", D1spher[5:10,5:10], delimiter=" ", fmt='%6.3f')
    return 0

def XTLS(workDirWannier, XTLSFolder, atomOrbitals, hopMatBorder, XTLSinput, w2webContext):
    print('XTLS running...')
    parentDir = w2webContext['caseBaseDir']
    workDir = workDirWannier + '/XTLS1'
    prepareDirectory(workDir)
    wannierName = os.path.basename(workDirWannier)
    shutil.copyfile(workDirWannier + '/' + wannierName + '_hr.dat', workDir + '/' + wannierName + '_hr.dat')
        
    # order of atoms and orbitals must be the same as in function Wannier !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    structInfo = w2webContext['structInfo']

    counts = {'s':1, 'p':3, 'd':5}
    params = str(len(atomOrbitals))
    atomList = []
    hopMatAtomOrbitals = []
    for an in structInfo['atomNamesList']: atomList += [an]*structInfo['atomCounts'][an]
    for a in structInfo['atomNamesList']:
        if a not in atomOrbitals: continue
        for orb in atomOrbitals[a]:
            params += ' ' + str(structInfo['atomCounts'][a]) + ' ' + str(counts[orb])
            ind = np.where(np.array(atomList) == a)[0]
            for i in ind: hopMatAtomOrbitals.append(a + ':' + orb)
    hopMatAtomOrbitals = np.array(hopMatAtomOrbitals)

    cmd = "local_Hamilton "+wannierName+"_hr.dat  "+params+" 1 1"    
    output = runCommand(cmd, workDir)
    with open(workDir+'/output.txt', 'w') as file_out:
        file_out.write(output)
    
    foundRes=re.search(r'Block Norms Max \n([\s\S]+)[\s\n]+Block Norms 2nd max', output, flags = re.IGNORECASE)
    matrix=foundRes.group(1)
    matrix=matrix.split('\n') #split matrix in rows
    hopMatr=[]
    minElemOfMatrix=sys.float_info.max
    for line in matrix:
        if line!='':
            listOfNumbers=line.split(' ')  #split each row in list of elements
            listOfNumbers.remove('')
            matrixRow=[float(item) for item in listOfNumbers]
            minInRow=min(matrixRow)
            minElemOfMatrix=minInRow if minInRow<minElemOfMatrix else minElemOfMatrix
            hopMatr.append(matrixRow)
    
    matr = np.copy(hopMatr)
    matrSize=len(hopMatAtomOrbitals)
    for i in range(matrSize):
        matr[i][i]=minElemOfMatrix
    
    uniqElements, elCounts = np.unique(matr.reshape(-1), return_counts=True)
    uniqElements = np.flipud(uniqElements)
    elCounts = np.flipud(elCounts)
    
    print('HopMat elements and their counts: ' + " ".join(map(lambda p: "({0:2g},{1})".format(p[0],p[1]), zip(uniqElements,elCounts))) )
    s = elCounts[uniqElements>hopMatBorder].sum()
    print('Take', s, 'elements greater than', hopMatBorder)
    
    def XTLSComputation(folder):
        
        def replaceToAbsolutePath(XTLSinputFolder, Hsphere):
            with open(XTLSinputFolder + '/' + XTLSinput, 'r') as file_in:
                text = file_in.read()
            
            abs_path = os.path.abspath(XTLSinputFolder) + '/Hsphere'
            '''replace_string is a string which will replace the first open(11,..) command
            in Xtls script. This string will contain declairings of all needed variables
            for describing absolute path.
            total_parts is a counter of parts of absolute path with length 'limit'
            '''
            replace_string=''
            total_parts = 1
            limit = 50
            #declaring variables of parts
            for part in range(limit, len(abs_path), limit):
                replace_string +='char @ path' + str(total_parts) + '=\"' + abs_path[part-limit:part] + '\";\n    '
                total_parts+=1
                
            replace_string += 'char @ path' + str(total_parts) + '=\"' + abs_path[part:len(abs_path)] + '\";\n    '
            #declaring path string as sum of path variables
            input_file_path = ''
            for i in range(1, total_parts+1):
                input_file_path +='path' + str(i) + '+'
            #declaring InputFileName variables for all types of Hsphere        
            for sphere in Hsphere:
                if sphere!='LD':
                    replace_string +='char @ InputFileName{0}={1}\"{0}.dat\";\n    '.format(sphere, input_file_path)

            replace_string += '\n    open(11,InputFileNameDD);'
            #replacing relative paths to absolute in Xtls script
            for sphere in Hsphere:
                if sphere == 'DD':
                    text = re.sub(r'open.*DD.*', replace_string, text)
                else:
                    text = re.sub(r'\s*".*Hsphere' + sphere + '.dat"', 'InputFileName' + sphere, text)
            
            with open(XTLSinputFolder + '/' + XTLSinput, 'w') as file_out:
                    file_out.write(text)
                    
        output = TriDiag(folder)
        if output==1: 
            return
        os.makedirs(folder+'/xcards', exist_ok=True)
        os.makedirs(folder+'/xcodes', exist_ok=True)
        os.makedirs(folder+'/xobjs', exist_ok=True)
        os.makedirs(folder+'/xwrk', exist_ok=True)
        Hsphere=['DD', 'DL', 'LD', 'LL']
        for sphere in Hsphere:
            shutil.copy(folder+'/Hsphere'+sphere+'.dat', folder+'/xcards/')
        shutil.copy(XTLSinput, folder+'/xcards/')
                
        #change paths to Hsphere files to absolute in XTLSinput file
        #replaceToAbsolutePath(folder+'/xcards', Hsphere)
                
        XTLSinputBaseName = os.path.split(XTLSinput)[1]
        output = runCommand("HOST=localhost "+XTLSFolder+"/bin/x925 --wait "+XTLSinputBaseName, folder+'/xcards')
        os.rename(folder+'/xobjs/'+XTLSinputBaseName+'.obj', folder+'/xobjs/result.obj')
        output = runCommand(XTLSFolder+"/bin/xc < "+XTLSFolder+"/xc/spc/spcana.x > spectrum.txt", folder+'/xcodes')
        #Copy spectrum picture to main folder
        shutil.copy(folder+'/xcodes/spectrum.ps', 'spectrum_'+folder.split('/')[-1] + '.ps')
        
    for j in range(matrSize):
        
        #indBool = hopMatr[j+1:, j] > hopMatBorder
        temp=[hopMatr[j+i][j] for i in range(1,matrSize-j)]
        indBool = np.array(temp) > hopMatBorder
        
        if not np.any(indBool): continue
        folder = workDir+'/'+str(j+1)
        os.makedirs(folder, exist_ok=True)
        ind = 1 + j+1 + np.where(indBool)[0]
        with open(folder + '/info.txt', 'w') as f: 
            f.write(str(hopMatAtomOrbitals[j]) + ' is overlapped with: '+ " ".join(hopMatAtomOrbitals[ind-1]) + '\n') 
            f.write("local_Hamilton ../"+wannierName+"_hr.dat  "+params+" "+str(len(ind)+1)+" "+str(j+1)+" "+" ".join(str(x) for x in ind) + '\n')
        
        output = runCommand("local_Hamilton ../"+wannierName+"_hr.dat  "+params+" "+str(len(ind)+1)+" "+str(j+1)+" "+" ".join(str(x) for x in ind), folder)
            
        XTLSComputation(folder)
# ===================================================================================================================

def runWien2k(params):
    global debugMode, debugLog
    common_params = params['common']
    SCFparams = params['SCF']
    DOSparams = params['DOS']
    BANDparams = params['BAND']
    Wannierparams = params['Wannier']
    XTLSparams = params['XTLS']
    
    debugMode = common_params['debugMode']
    if debugMode:
        debugLog=open('log.txt','w')
        
    if ('WIENROOT' in params) and (params['WIENROOT'] != ''):
        if not os.path.isfile(params['WIENROOT']+os.sep+'lapw1'):
            print('WIENROOT is not correct!')
            exit(1)
        os.environ['WIENROOT'] = params['WIENROOT']
        os.environ['PATH'] = os.environ['WIENROOT']+':'+os.environ['PATH']

    wannierName = Wannierparams['wannierName']
    structureFile = SCFparams['struct_file']
    
    #Раньше не было ещё одного сплита по слэшу.Из-за этого программа падала в случае, если workingFolder!='.'
    name = os.path.splitext(structureFile)[-2].split('/')[-1]
    klist_band_file = BANDparams['klist_band']
    lapwParams = SCFparams['lapwParams']
    dosInfo = common_params['dosInfo']
    kpoints = common_params['kpoints']
    rkmax = SCFparams['RKmax']
    lstart_energy = SCFparams['lstart_energy']
    efmod = SCFparams['efmod']
    ef_eval = SCFparams['ef_eval']
    iqtlsave = SCFparams['iqtlsave'] if 'iqtlsave' in SCFparams else False
    hopMatBorder = XTLSparams['hopMatBorder']
    XTLSinput = XTLSparams['XTLSinput']
    
    workingFolder = '.' if 'workingFolder' not in params['common'] else params['common']['workingFolder']
    w2webContext = prepareW2WebEmulation(workingFolder)

    if SCFparams['run']:
        workDirSCF = SCF(structureFile, w2webContext, SCFparams['runParallel'], SCFparams['runCommandPrefix'], lapwParams, kpoints, rkmax, lstart_energy, efmod, ef_eval, iqtlsave)
    else:
        workDirSCF = workingFolder + '/w2webEmulator/caseBaseDir/'+name
        workDirSCF = os.path.abspath(workDirSCF)
        w2webContext['structInfo'] = parseStructFile(workDirSCF+'/'+name+'.struct')
        if kpoints>0 : 
             w2webContext['structInfo']['kpoints'] = kpoints
        
    if DOSparams['run']:
        workDirDOS = DOS(workDirSCF, w2webContext, DOSparams['runParallel'], DOSparams['runCommandPrefix'], DOSparams['xmin'])
    else:
        workDirDOS = workingFolder + '/w2webEmulator/caseBaseDir/'+name+'_DOS/'+name
        workDirDOS = os.path.abspath(workDirDOS)

    if BANDparams['run']:
        workDirBandstructure = Bandstructure(workDirSCF, klist_band_file, w2webContext, BANDparams['runParallel'], BANDparams['runCommandPrefix'], efmod)
    else:
        workDirBandstructure = workingFolder + '/w2webEmulator/caseBaseDir/'+name+'_Bandstructure/'+name
        workDirBandstructure = os.path.abspath(workDirBandstructure)

    if Wannierparams['run']:
        workDirWannier = Wannier(wannierName, workDirBandstructure, dosInfo['energyInterval'], dosInfo['atomOrbitals'], w2webContext, Wannierparams['runParallel'], Wannierparams['runCommandPrefix'], Wannierparams['wannierRunCommandPrefix'])
    else:
        workDirWannier=workingFolder+'/w2webEmulator/caseBaseDir/'+name+'_Bandstructure/'+name+'/'+wannierName;   
    
    if XTLSparams['run']:
        if 'structInfo' in XTLSparams:
            w2webContext['structInfo'] = XTLSparams['structInfo']
        XTLS(workDirWannier, XTLSparams['Xtls_path'], dosInfo['atomOrbitals'], hopMatBorder, XTLSinput, w2webContext=w2webContext)
