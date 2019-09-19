import threading
import struct
import heapq
import time

from .packet_flow import SocketController, SocketMode, KeyManager
from .opcodes import AUDIO, REGISTER_UDP, SET_GATE, SET_COMP
from .config import TCP_PORT, SERVER
from .audio import AudioIO, AudioProcessor, Gate, Compressor
from . import loggers


class TransmitAudio(AudioProcessor):
    def __init__(self, sock):
        self.sock = sock

    def process(self, data, sequence, amp):
        data = struct.pack('!H', amp) + data
        self.sock.send_packet(AUDIO, data, sequence=sequence)

    def clone(self):
        return self.__class__(self.sock)


class JitterBuffer(AudioProcessor):
    ROLLOVER = 50
    BUFFER = 5

    def __init__(self):
        self.latest = 0
        self.heap = []

    def process(self, data, packet, *_):
        if packet.sequence > self.ROLLOVER and packet.sequence < self.latest:
            return None
        heapq.heappush(self.heap, (packet.sequence, data))

        while len(self.heap) >= self.BUFFER:
            popped = heapq.heappop(self.heap)
            if popped[0] <= self.latest and popped[0] > self.ROLLOVER:
                continue
            if self.latest == 0:
                self.latest = popped[0]
            else:
                self.latest += 1
            #if self.latest != popped[0]:
            #    heapq.heappush(self.heap, (packet.sequence, data))
            return popped[1]
        return None


class NullSink(AudioProcessor):
    def process(self, *args):
        return None


class Client:
    def __init__(self, no_input=False, no_output=False):
        self._alive = True
        self.log = loggers.getLogger(__name__ + '.' + self.__class__.__name__)

        self.km = KeyManager()

        self.sock = SocketController(km=self.km)
        self.sock.connect(SERVER, TCP_PORT)
        self.sock.start()
        self.sock.tcp_lost_hook = self.kill

        self.udp_send = SocketController(SocketMode.UDP, km=self.km)
        self.udp_send.connect(SERVER, TCP_PORT)

        self.udp_recv = SocketController(SocketMode.UDP, km=self.km)
        self.udp_recv.bind('', 0)
        self.udp_port = self.udp_recv.getsockname()[1]
        self.udp_recv.start()

        ms = lambda x: round(x * (44100 / 1000))
        self.gate = Gate(ms(3.5), ms(10), ms(10), 950)
        self.comp = Compressor(ms(1), ms(100), 10000)

        self.aio = AudioIO()
        self.aio.pipeline.insert(0, self.gate)
        self.aio.pipeline.insert(0, self.comp)
        self.aio.pipeline.append(TransmitAudio(self.udp_send))

        if no_output:
            self.aio.back_pipeline.insert(0, NullSink())
        if no_input:
            self.aio.pipeline.insert(0, NullSink())
        #self.aio.back_pipeline.insert(0, JitterBuffer())

    def kill(self, *args):
        self._alive = False

    def tcp_mainloop(self):
        while self._alive:
            pkt = self.sock.get_packet(True)

            if pkt[2].opcode == SET_GATE:
                attack, hold, release, threshold, _ = struct.unpack('!4lH', pkt[2].payload)
                if attack != -1:
                    self.gate.gate.attack = attack
                if hold != -1:
                    self.gate.gate.hold = hold
                if release != -1:
                    self.gate.gate.release = release
                if threshold != -1:
                    self.gate.gate.threshold = threshold
                self.log.debug(f'Set gate to: {attack}, {hold}, {release}, {threshold}')
            elif pkt[2].opcode == SET_COMP:
                attack, release, threshold, _ = struct.unpack('!3lH', pkt[2].payload)
                if attack != -1:
                    self.comp.comp.attack = attack
                if release != -1:
                    self.comp.comp.release = release
                if threshold != -1:
                    self.comp.comp.threshold = threshold
                self.log.debug(f'Set comp to: {attack}, {release}, {threshold}')

    def mainloop(self):
        self.client_id = self.sock.do_tcp_client_auth()
        self.udp_send.client_id = self.client_id
        self.udp_recv.client_id = self.client_id

        self.log.info(f'Received client ID: {self.client_id}')

        pld = struct.pack('!H', self.udp_port)
        self.sock.send_packet(REGISTER_UDP, pld)

        threading.Thread(target=self.tcp_mainloop, daemon=True).start()

        self.aio.begin()

        while self._alive:
            pkt = self.udp_recv.get_packet(True)

            if pkt[2].opcode == AUDIO:
                self.aio.feed(pkt[2].payload, pkt[2])

        self.log.warn('Terminating client due to dropped connection.')

if __name__ == '__main__':
    Client().mainloop()
