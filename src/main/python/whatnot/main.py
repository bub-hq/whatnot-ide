'''
Created on Jan 25, 2017

@author: bcopy
'''
import os
import cherrypy
import sys
import subprocess
import random
import time
import threading
import Queue
import tempfile
import logging

class ScriptMonitor(object):
    '''
    Monitors the script execution and updates result statuses
    '''
    
    def __init__(self):
        self.m_processInitialized = False
    
    def monitor(self, process):
        assert isinstance(process, subprocess.Popen)
        self.m_processInitialized = True
        self.m_process = process
        if(self.m_process.pid != None and self.m_process.poll() == None):
            print "Starting script process output polling..."
            self.m_stdoutQueue = Queue.Queue()
            self.m_stdoutReader = AsynchronousFileReader(self.m_process.stdout, self.m_stdoutQueue)
            self.m_stdoutReader.start()
        else:
            print "script process startup failed."
            
    def abort(self):
        try:
            if(self.m_processInitialized and self.m_process.poll() == None):
                self.m_process.terminate()
                self.m_stdoutQueue.put("* Script execution aborted *")
            self.m_processInitialized = False
            return True
        except:
            print "script could not be terminated : ", sys.exc_info()[0]
            return False
 
    def isRunning(self):
        return (self.m_processInitialized and self.m_process.poll() == None)
        
    def getStdoutQueue(self):
        return self.m_stdoutQueue

class AsynchronousFileReader(threading.Thread):
    '''
    Helper class to implement asynchronous reading of a file
    in a separate thread. Pushes read lines on a queue to
    be consumed in another thread.
    '''
 
    def __init__(self, fd, queue):
        assert isinstance(queue, Queue.Queue)
        assert callable(fd.readline)
        threading.Thread.__init__(self)
        self._fd = fd
        self._queue = queue
 
    def run(self):
        '''The body of the thread: read lines and put them on the queue.'''
        for line in iter(self._fd.readline, ''):
            self._queue.put(line)
 
    def eof(self):
        '''Check whether there is no more content to expect.'''
        return not self.is_alive() and self._queue.empty()

class WhatnotService(object):
    def __init__(self):
        self.m_scriptMonitor = None
    
    @cherrypy.expose
    @cherrypy.tools.json_out()
    def ping(self):
        return {"msg": "pong"}
        
    @cherrypy.expose
    @cherrypy.tools.json_out()
    def status(self):
        if(self.m_scriptMonitor != None):
            running = self.m_scriptMonitor.isRunning()
            retCode = self.m_scriptMonitor.m_process.poll()
            if(retCode == None):
                retCode = -1
            return {"running":running,"exitCode":retCode}
        else:
            return {"running":False,"exitCode":-1}
    
    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def execute(self):
        scriptData = cherrypy.request.json
        if(self.m_scriptMonitor == None):
            self.m_scriptMonitor = ScriptMonitor()
        
        if(scriptData["scriptText"] == None):
            return {"success":False, "message":"Script contents undefined"}
        elif(self.m_scriptMonitor.isRunning()):
            return {"success":False, "message":"Script already running !"}
        else:
            # Write the script to a temporary file
            #scriptFile = tempfile.NamedTemporaryFile(prefix='whatnot-script-')
            scriptFile = open("/tmp/script.py", "w")
            scriptFile.write(scriptData["scriptText"]+"\n")
            scriptFile.close()
            print "Executing script "+scriptFile.name+" ..."
            
            # Starting a new python process (with -u for unbuffered output)
            scriptProcess = subprocess.Popen(["python", "-u", scriptFile.name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=256)
            
            if(scriptProcess.pid != None):
                self.m_scriptMonitor.monitor(scriptProcess)
                return {"success":True, "message": "Running script (pid "+str(self.m_scriptMonitor.m_process.pid)+")"}
            else:
                return {"success":False, "message": "Could not start up script"}
        
    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def abort(self):
        result = False;
        if (self.m_scriptMonitor != None):
            print "Aborting script execution"
            result = self.m_scriptMonitor.abort()
        return {"result":result}

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def tailStdOut(self):
        result = []
        if (self.m_scriptMonitor != None):
            queue = self.m_scriptMonitor.getStdoutQueue()
            for x in xrange(min(100, queue.qsize())):
                try:
                    val = queue.get_nowait()
                    result.append(val)
                except Empty:
                    pass
        return  {"tail": result}

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def shutdown(self):
        result = -1
        try:
            print "Shutting down Whatnot IDE service..."
            if (self.m_scriptMonitor != None and self.m_scriptMonitor.isRunning()):
                self.m_scriptMonitor.abort()
            print "Whatnot IDE service shutdown complete."
            result = 0
        except:
            print "Failed to shutdown Whatnot IDE service : ", sys.exc_info()[0]
        return  {"result": result}
        
        
if __name__ == '__main__':
    whatNotService = WhatnotService()
    try:
        WEBAPP_ROOT = os.getenv('WEBAPP_ROOT',os.getcwd()+"/webapp")
        WEBJARS_ROOT = os.getenv('WEBJARS_ROOT',os.getcwd()+"/webjars")
        
        cherrypy.server.socket_host = '0.0.0.0'
        accessLogger = logging.getLogger('cherrypy.access')
        accessLogger.setLevel(logging.WARNING)
        
        # Registering a cherrypy stop handler to force the service to
        # stop any script execution or threads
        cherrypy.engine.subscribe('stop', whatNotService.shutdown)
        
        cherrypy.quickstart(whatNotService, "/", 
            {
                  '/':
                  {
                   'tools.staticdir.on': True,
                   'tools.staticdir.dir': os.path.abspath(WEBAPP_ROOT),
                   'tools.staticdir.index': 'index.html'
                  },
                  '/webjars':
                  {
                   'tools.staticdir.on': True,
                   'tools.staticdir.dir': os.path.abspath(WEBJARS_ROOT)
                  }                   
            })
    except KeyboardInterrupt:
        whatNotService.shutdown()
        cherrypy.engine.exit()
