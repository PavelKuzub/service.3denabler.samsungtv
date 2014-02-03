'''
    3D Enabler [for] Samsung TV - addon for XBMC to enable 3D mode
    Copyright (C) 2014  Pavel Kuzub

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import os
import sys
import xbmc
import xbmcgui
import xbmcaddon
import simplejson
import socket
import re
import urllib2
from xml.dom.minidom import parseString
import base64
import uuid
import select

__addon__   = xbmcaddon.Addon()
libs = os.path.join(__addon__.getAddonInfo('path'), 'lib')
sys.path.append(libs)

import ssdp

keyMap = {
          '3D'      :'KEY_PANNEL_CHDOWN',
          'RIGHT'   :'KEY_RIGHT',
          'LEFT'    :'KEY_LEFT',
          'UP'      :'KEY_UP',
          'DOWN'    :'KEY_DOWN',
          'EXIT'    :'KEY_EXIT',
          'ENTER'   :'KEY_ENTER'
    }

class responsePayloadMapping(object):
    def __init__(self):
        self.waiting        = '\x0A\x00\x01\x00\x00\x00'
        self.requested      = '\x0A\x00\x02\x00\x00\x00'
        self.disconnected   = '\x0A\x00\x15\x00\x00\x00'
        self.denied         = '\x64\x00\x00\x00'
        self.granted        = '\x64\x00\x01\x00'
        self.timeout        = '\x65\x00'

class Settings(object):
    def __init__(self):
        self.enabled        = True
        self.discover       = True
        self.ipaddress      = ''
        self.tvname         = ''
        self.pause          = True
        self.black          = True
        self.notifications  = True
        self.notifymessage  = ''
        self.sock           = False
        self.authCount      = 0
        self.pollCount      = 0
        self.curTVmode      = 0
        self.newTVmode      = 0
        self.detectmode     = 0
        self.pollsec        = 5
        self.idlesec        = 5
        self.inProgress     = False
        self.inScreensaver  = False
        self.skipInScreensaver  = True
        self.addonname      = __addon__.getAddonInfo('name')
        self.icon           = __addon__.getAddonInfo('icon')
        self.sequenceBegin  = 'BLACKON,PAUSE'
        self.sequenceEnd    = 'BLACKOFF,PLAY'
        self.sequence3DTAB  = '3D,P4000,RIGHT,P1200,RIGHT,P1200,EXIT'
        self.sequence3DSBS  = '3D,P4000,RIGHT,P1200,EXIT'
        self.sequence3Dnone = '3D,P1200'
        self.remotename     = '3D Enabler'
        self.appstring      = 'iphone.3DEnabler.iapp.samsung'
        self.load()
        
    def getSetting(self, name, dataType = str):
        value = __addon__.getSetting(name)
        if dataType == bool:
            if value.lower() == 'true':
                value = True
            else:
                value = False
        elif dataType == int:
            value = int(value)
        else:
            value = str(value)
        xbmc.log('getSetting:' + str(name) + '=' + str(value), xbmc.LOGDEBUG)
        return value
    
    def setSetting(self, name, value):
        if type(value) == bool:
            if value:
                value = 'true'
            else:
                value = 'false'
        else:
            value = str(value)
        xbmc.log('setSetting:' + str(name) + '=' + str(value), xbmc.LOGDEBUG)
        __addon__.setSetting(name, value)
    
    def getLocalizedString(self, stringid):
        return __addon__.getLocalizedString(stringid)
    
    def load(self):
        xbmc.log('loading Settings', xbmc.LOGINFO)
        self.enabled            = self.getSetting('enabled', bool)
        self.discover           = self.getSetting('discover', bool)
        self.ipaddress          = self.getSetting('ipaddress', str)
        self.tvname             = self.getSetting('tvname', str)
        self.pause              = self.getSetting('pause', bool)
        self.black              = self.getSetting('black', bool)
        self.notifications      = self.getSetting('notifications', bool)
        self.curTVmode          = self.getSetting('curTVmode', int)
        self.detectmode         = self.getSetting('detectmode', int)
        self.pollsec            = self.getSetting('pollsec', int)
        self.idlesec            = self.getSetting('idlesec', int)
        self.skipInScreensaver  = self.getSetting('skipInScreensaver', bool)
        self.sequence3DTAB      = self.getSetting('sequence3DTAB', str)
        self.sequence3DSBS      = self.getSetting('sequence3DSBS', str)
        self.sequence3Dnone     = self.getSetting('sequence3Dnone', str)
    
def toNotify(message):
    if len(settings.notifymessage) == 0:
        settings.notifymessage = message
    else:
        settings.notifymessage += '. ' + message

def notify(timeout = 5000):
    if len(settings.notifymessage) == 0:
        return
    if settings.notifications:
        xbmc.executebuiltin('Notification(%s, %s, %d, %s)'%(settings.addonname, settings.notifymessage, timeout, settings.icon))
    xbmc.log('NOTIFY: ' + settings.notifymessage, xbmc.LOGINFO)
    settings.notifymessage = ''

def getStereoscopicMode():
    query = '{"jsonrpc": "2.0", "method": "GUI.GetProperties", "params": {"properties": ["stereoscopicmode"]}, "id": 1}'
    result = xbmc.executeJSONRPC(query)
    json = simplejson.loads(result)
    xbmc.log('Received JSON response: ' + str(json), xbmc.LOGDEBUG)
    ret = 'unknown'
    if json.has_key('result'):
        if json['result'].has_key('stereoscopicmode'):
            if json['result']['stereoscopicmode'].has_key('mode'):
                ret = json['result']['stereoscopicmode']['mode'].encode('utf-8')
    # "off", "split_vertical", "split_horizontal", "row_interleaved"
    # "hardware_based", "anaglyph_cyan_red", "anaglyph_green_magenta", "monoscopic"
    return ret

def getTranslatedStereoscopicMode():
    mode = getStereoscopicMode()
    if mode == 'split_horizontal': return 1
    elif mode == 'split_vertical': return 2
    else: return 0

def stereoModeHasChanged():
    if settings.curTVmode != settings.newTVmode:
        return True
    else:
        return False

def getIPfromString(string):
    try:
        return re.search("(\d{1,3}\.){3}\d{1,3}", string).group()
    except:
        return ''

# Discover Samsung TV. If more than one detected - choose one from the list 
# To match all devices use ssdp.discover('ssdp:all')
def discoverTVip():
    tvdevices = []
    tvdevicesIPs = []
    tvdevicesNames = []
    discoverCount = 0
    while True:
        discoverCount += 1
        dicovered = ssdp.discover('urn:samsung.com:service:MultiScreenService:1')
        if xbmc.abortRequested: break
        if len(dicovered) > 0: break
        if discoverCount > 2: break
        
    for tvdevice in dicovered:
        tvXMLloc = tvdevice.location
        xbmc.log('tvXMLloc: ' + str(tvXMLloc), xbmc.LOGDEBUG)
        tvip = getIPfromString(tvXMLloc)
        if tvip:
            xbmc.log('tvip: ' + str(tvip), xbmc.LOGDEBUG)
            tvFriendlyName = settings.getLocalizedString(30503) #Unknown
            try:
                tvXML = urllib2.urlopen(tvXMLloc).read()
                xbmc.log('tvXML: ' + str(tvXML), xbmc.LOGDEBUG)
                tvXMLdom = parseString(tvXML)
                tvFriendlyName = tvXMLdom.getElementsByTagName('friendlyName')[0].childNodes[0].toxml()
            except urllib2.HTTPError as e:
                if e.code == 401:
                    # If Remote Access has been denied - we cannot even read the description
                    tvFriendlyName = settings.getLocalizedString(30501) #Access Denied. Check Permissions
                else:
                    toNotify(settings.getLocalizedString(30502) + ' ' + str(e))
                    xbmc.log('HTTP Error ' + str(e), xbmc.LOGERROR)
            except:
                xbmc.log('Exception getting friendly name', xbmc.LOGERROR)
            if tvip not in tvdevicesIPs:
                tvdevicesIPs.append(tvip)
                tvdevicesNames.append(tvFriendlyName + ' @ ' + tvip)
                tvdevices.append([tvip, tvFriendlyName])
    
    xbmc.log('Discovered devices count: ' + str(len(tvdevices)), xbmc.LOGINFO)
        
    if len(tvdevices) > 1:
        myselect = dialog.select(settings.getLocalizedString(30514), tvdevicesNames) #Select your TV device
        toNotify(settings.getLocalizedString(30504) + ': ' + str(tvdevices[myselect][1])) #Discovered TV
        return tvdevices[myselect]
    elif len(tvdevices) == 1:
        toNotify(settings.getLocalizedString(30504) + ': ' + str(tvdevices[0][1])) #Discovered TV
        return tvdevices[0]
    else:
        toNotify(settings.getLocalizedString(30505)) #Samsung TV is not detected
        return []

def getPayloads(response = ''):
    xbmc.log('Parsing response (' + str(len(response)) + '):' + response.encode('hex'), xbmc.LOGDEBUG)
    payloads = []
    while True:
        if len(response) < 5: break
        strLen = int(''.join(reversed(response[1:3])).encode('hex'), 16)
        paylLen = int(''.join(reversed(response[3+strLen:5+strLen])).encode('hex'), 16)
        payl = response[5+strLen:5+strLen+paylLen]
        response = response[5+strLen+paylLen:]
        payloads.append(payl)
        xbmc.log('Payload: ' + payl.encode('hex'), xbmc.LOGDEBUG)
        if xbmc.abortRequested: break
    return payloads

# Function to send generic message to TV
def sendMessage(payload):
    thisMessage = '\x00' \
    + chr(len(settings.appstring) & 0xFF) + chr((len(settings.appstring) >> 8) & 0xFF) + settings.appstring \
    + chr(len(payload) & 0xFF) + chr((len(payload) >> 8) & 0xFF) + payload
    try:
        settings.sock.setblocking(1)
        settings.sock.send(thisMessage)
    except socket.error, (value,message):
        xbmc.log('Failed to send: ' + thisMessage.encode('hex') + ' due to socket error: ' + str(value) + ': ' + str(message), xbmc.LOGERROR)
        return ''
    ready = select.select([settings.sock], [], [], 10)[0]
    if ready:
        return settings.sock.recv(4096)
    else:
        return ''

# Function to send keys
def sendKey(key):
    key64 = base64.b64encode(key)
    keyMessage = '\x00\x00\x00' + chr(len(key64) & 0xFF) + chr((len(key64) >> 8) & 0xFF) + key64
    return sendMessage(keyMessage)

def authenticate():
    if not settings.sock: return False
    # Need client IP and MAC for auth purposes
    ip64 = base64.b64encode(settings.sock.getsockname()[0])
    mac64 = base64.b64encode('-'.join('%02X' %((uuid.getnode() >> 8*i) & 0xff) for i in reversed(xrange(6))))
    remote64 = base64.b64encode(settings.remotename)
    authMessage = '\x64\x00' \
    + chr(len(ip64) & 0xFF) + chr((len(ip64) >> 8) & 0xFF) + ip64 \
    + chr(len(mac64) & 0xFF) + chr((len(mac64) >> 8) & 0xFF) + mac64 \
    + chr(len(remote64) & 0xFF) + chr((len(remote64) >> 8) & 0xFF) + remote64
    
    gotResponseTriggers = [responseMap.granted, responseMap.denied, responseMap.timeout]
    progressTriggers = [responseMap.waiting, responseMap.requested]
    progressDialogOpen = False
    settings.authCount = 0
    response = sendMessage(authMessage)
    responsePayloads = getPayloads(response)
    if any(x in responsePayloads for x in progressTriggers):
        while True:
            if any(x in responsePayloads for x in gotResponseTriggers): break
            if settings.authCount >= 100: break
            settings.authCount += 1
            if not progressDialogOpen:
                progressDialogOpen = True
                dialogprogress.create(settings.addonname + ': ' + settings.getLocalizedString(30511), settings.getLocalizedString(30512), settings.getLocalizedString(30513)) #Authentication    #Your TV is asking for permission    #Please Allow access
            dialogprogress.update(settings.authCount)
            ready = select.select([settings.sock], [], [], 0.61)[0]  # TV authentication timeout is ~60 seconds
            if ready:
                response = settings.sock.recv(4096)
                responsePayloads = getPayloads(response)
            if dialogprogress.iscanceled(): break
            if xbmc.abortRequested: break
    
    if progressDialogOpen:
        dialogprogress.close()
        progressDialogOpen = False
    
    if responseMap.disconnected in responsePayloads:
        if connectTV():
            return authenticate()
        return False
    elif responseMap.granted in responsePayloads:
        xbmc.log('authenticate() returned: True', xbmc.LOGDEBUG)
        return True
    else:
        xbmc.log('authenticate() returned: False', xbmc.LOGDEBUG)
        toNotify(settings.getLocalizedString(30509)) #Authentication Failed
        return False

def newSock():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    return sock

def connectTV():
    port = 55000
    settings.ipaddress = getIPfromString(settings.ipaddress)
    if bool(settings.ipaddress):
        settings.sock = newSock()
        try:
            xbmc.log('Connecting to:' + str(settings.ipaddress) + ':' + str(port), xbmc.LOGDEBUG)
            settings.sock.connect((settings.ipaddress, port))
            return True
        except:
            xbmc.log('TV is Off or IP is outdated', xbmc.LOGINFO)
    if settings.discover:
        tv = discoverTVip()
        if tv:
            settings.sock = newSock()
            try:
                xbmc.log('Connecting to:' + str(tv[0]) + ':' + str(port), xbmc.LOGDEBUG)
                settings.sock.connect((tv[0], port))
                settings.ipaddress = tv[0]
                settings.tvname = tv[1]
                settings.setSetting('ipaddress', settings.ipaddress)
                settings.setSetting('tvname', settings.tvname)
                return True
            except:
                xbmc.log('TV is Off or IP is outdated', xbmc.LOGINFO)
                toNotify(settings.getLocalizedString(30508)) #Connection Failed
        else:
            xbmc.log('TV has not been discovered', xbmc.LOGINFO)
            toNotify(settings.getLocalizedString(30506)) #TV has not been discovered
    else:
        xbmc.log('Cannot connect. Discovery is turned off', xbmc.LOGINFO)
        toNotify(settings.getLocalizedString(30507)) #Discovery is turned off
    return False

def processSequence(commandSequence):
    putOnPause = False
    # Parse commands and execute them
    for x in commandSequence.split(','):
        thisKey = x.strip().upper()
        if thisKey in keyMap:
            xbmc.log('Sending ' + thisKey + ' as Key: ' + keyMap[thisKey], xbmc.LOGDEBUG)
            sendKey(keyMap[thisKey])
        elif thisKey[:3] == 'KEY':
            xbmc.log('Sending Key: ' + thisKey, xbmc.LOGDEBUG)
            sendKey(thisKey)
        elif thisKey == 'PAUSE':
            if settings.pause:
                if xbmc.Player().isPlayingVideo():
                    if not xbmc.getCondVisibility('Player.Paused'):
                        xbmc.log('Pause XBMC', xbmc.LOGDEBUG)
                        xbmc.Player().pause()
                        putOnPause = True
        elif thisKey == 'PLAY':
            if settings.pause:
                if xbmc.Player().isPlayingVideo():
                    if xbmc.getCondVisibility('Player.Paused'):
                        xbmc.log('Resume XBMC', xbmc.LOGDEBUG)
                        if putOnPause: xbmc.Player().pause()
        elif thisKey[:1] == 'P':
            xbmc.log('Waiting for ' + thisKey[1:] + ' milliseconds', xbmc.LOGDEBUG)
            xbmc.sleep(int(thisKey[1:]))
        elif thisKey == 'BLACKON':
            if settings.black:
                xbmc.log('Screen to Black', xbmc.LOGDEBUG)
                blackScreen.show()
        elif thisKey == 'BLACKOFF':
            if settings.black:
                xbmc.log('Screen from Black', xbmc.LOGDEBUG)
                blackScreen.close()
        else:
            xbmc.log('Unknown command: ' + thisKey, xbmc.LOGWARNING)
    xbmc.log('Done with sequence')

def mainStereoChange():
    if stereoModeHasChanged():
        if not connectTV():
            toNotify(settings.getLocalizedString(30508)) #Connection Failed
            # Authenticate and action
        elif authenticate():
            # Checking again as mode could have changed during long authentication process
            if settings.authCount > 1:
                settings.newTVmode = getTranslatedStereoscopicMode()
            if stereoModeHasChanged():
                xbmc.log('Stereoscopic Mode changed: curTVmode:newTVmode = ' + str(settings.curTVmode) + ':' + str(settings.newTVmode), xbmc.LOGDEBUG)
                # Action Assignment
                if settings.newTVmode == 1: commandSequence = settings.sequence3DTAB
                elif settings.newTVmode == 2: commandSequence = settings.sequence3DSBS
                else: commandSequence = settings.sequence3Dnone
                
                if (settings.curTVmode != 0) and (settings.newTVmode != 0):
                    # We need to transition from one 3D mode to another
                    commandSequence = settings.sequenceBegin + ',' + settings.sequence3Dnone + ',' + commandSequence + ',' + settings.sequenceEnd
                else:
                    # We need to switch from none to 3D mode
                    commandSequence = settings.sequenceBegin + ',' + commandSequence + ',' + settings.sequenceEnd
                processSequence(commandSequence)
                # Saving current 3D mode
                settings.curTVmode = settings.newTVmode
                settings.setSetting('curTVmode', settings.newTVmode)
            else:
                xbmc.log('Stereoscopic Mode is the same', xbmc.LOGINFO)
        
        else:
            toNotify(settings.getLocalizedString(30509)) #Authentication Failed
        
        # Close the socket
        if settings.sock:
            settings.sock.close()
    else:
        xbmc.log('Stereoscopic mode has not changed', xbmc.LOGDEBUG)
    # Notify of all messages
    notify()

def mainTrigger():
    if not settings.inProgress:
        settings.inProgress - True
        settings.newTVmode = getTranslatedStereoscopicMode()
        if stereoModeHasChanged():
            mainStereoChange()
        settings.inProgress - False

def onAbort():
    # On exit switch TV back to None 3D
    settings.newTVmode = 0
    if stereoModeHasChanged():
        xbmc.log('Exit procedure: changing back to None 3D', xbmc.LOGINFO)
        mainStereoChange()

def checkAndDiscover():
    if not settings.ipaddress:
        if settings.discover:
            if dialog.yesno(settings.addonname, settings.getLocalizedString(30515), settings.getLocalizedString(30518), settings.getLocalizedString(30519)):    #Your Samsung TV is not defined yet    #If it is connected to your network - it can be discovered    #Do you want to discover TV now?
                if connectTV():
                    authenticate()
        else:
            if dialog.yesno(settings.addonname, settings.getLocalizedString(30515), settings.getLocalizedString(30516), settings.getLocalizedString(30517)):    #Your Samsung TV is not defined yet    #Auto Discovery is currently Disabled    #Do you want to enter your TV IP address now?
                __addon__.openSettings()
    notify()

class MyMonitor(xbmc.Monitor):
    def __init__(self, *args, **kwargs):
        xbmc.Monitor.__init__(self)
    
    def onSettingsChanged( self ):
        xbmc.log('Settings changed', xbmc.LOGDEBUG)
        settings.load()
        checkAndDiscover()
    
    def onScreensaverDeactivated(self):
        # If detect mode is poll only - do not react on events
        if settings.detectmode == 2: return
        xbmc.log('Screensaver Deactivated', xbmc.LOGDEBUG)
        settings.inScreensaver = False
    
    def onScreensaverActivated(self):
        # If detect mode is poll only - do not react on events
        if settings.detectmode == 2: return
        xbmc.log('Screensaver Activated', xbmc.LOGDEBUG)
        if settings.skipInScreensaver:
            settings.inScreensaver = True
    
    def onNotification(self, sender, method, data):
        # If detect mode is poll only - do not react on events
        if settings.detectmode == 2: return
        xbmc.log('Notification Received: ' + str(sender) + ': ' + str(method) + ': ' + str(data), xbmc.LOGDEBUG)
        if method == 'Player.OnPlay':
            if xbmc.Player().isPlayingVideo():
                xbmc.log('Trigger: onNotification: ' + str(method), xbmc.LOGDEBUG)
                #Small delay to ensure Stereoscopic Manager completed changing mode
                xbmc.sleep(500)
                mainTrigger()
        elif method == 'Player.OnStop':
            xbmc.log('Trigger: onNotification: ' + str(method), xbmc.LOGDEBUG)
            #Small delay to ensure Stereoscopic Manager completed changing mode
            xbmc.sleep(500)
            mainTrigger()

def main():
    global dialog, dialogprogress, blackScreen, responseMap, settings, monitor
    dialog = xbmcgui.Dialog()
    dialogprogress = xbmcgui.DialogProgress()
    blackScreen = xbmcgui.Window(-1)
    responseMap = responsePayloadMapping()
    settings = Settings()
    checkAndDiscover()
    monitor = MyMonitor()
    while not xbmc.abortRequested:
        if settings.detectmode != 1:
            if not settings.inScreensaver:
                settings.pollCount += 1
                if xbmc.getGlobalIdleTime() <= settings.idlesec:
                    if settings.pollCount > settings.pollsec:
                        mainTrigger()
                        settings.pollCount = 0
                        continue
        xbmc.sleep(1000)
    onAbort()

if __name__ == '__main__':
    main()
