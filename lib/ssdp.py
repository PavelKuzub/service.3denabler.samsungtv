#   Copyright 2014 Dan Krause, 2020 Pavel Kuzub
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import socket
import http.client
import io
import json

class SSDPResponse(object):
    class _FakeSocket(io.BytesIO):
        def makefile(self, *args, **kw):
            return self
    def __init__(self, response):
        r = http.client.HTTPResponse(self._FakeSocket(response))
        try:
            r.begin()
            self.location = r.getheader("location")
            self.usn = r.getheader("usn")
            self.st = r.getheader("st")
            self.cache = r.getheader("cache-control").split("=")[1]
        except Exception as e:
            print(str(e))

    def toJson(self):
        return json.dumps(self, default=lambda o: o.__dict__)
    def __repr__(self):
        return "<SSDPResponse({location}, {st}, {usn})>".format(**self.__dict__)

def discover(service, timeout=5, retries=1, mx=3):
    group = ("239.255.255.250", 1900)
    message = "\r\n".join([
        'M-SEARCH * HTTP/1.1',
        'ST: {st}',
        'MAN: "ssdp:discover"',
        'HOST: {0}:{1}',
        'MX: {mx}',
        'Content-Length: 0',
        '',''])
    socket.setdefaulttimeout(timeout)
    responses = {}
    for _ in range(retries):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        message_bytes = message.format(*group, st=service, mx=mx).encode('utf-8')
        sock.bind((getNetworkIp(), 0))  # Bind on any free port on local interface
        sock.sendto(message_bytes, group)
        while True:
            try:
                received = sock.recv(1024)
                print(received)
                response = SSDPResponse(received)
                responses[response.location] = json.loads(response.toJson())
            except socket.timeout:
                break

    return list(responses.values())

def getNetworkIp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.connect(('<broadcast>', 0))
    return s.getsockname()[0]

# Example:
# import ssdp
# ssdp.discover("ssdp:all")