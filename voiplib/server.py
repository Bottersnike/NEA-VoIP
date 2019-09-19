import threading
import socket
import struct

from .util.packets import Packet, PacketError
from .packet_flow import SocketController, SocketMode, KeyManager
from .opcodes import AUDIO, REGISTER_UDP, SET_GATE, SET_ACK, SET_FAIL, SET_COMP
from .config import HOST, TCP_PORT, CONTROL_PORT
from . import loggers


class Server:
    def __init__(self):
        self.log = loggers.getLogger(__name__ + '.' + self.__class__.__name__)

        self.km = KeyManager()

        self.sock = SocketController(km=self.km)
        self.cont_sock = SocketController()
        self.udp_recv = SocketController(SocketMode.UDP, km=self.km)
        self.udp_send = SocketController(SocketMode.UDP, km=self.km)

        self.udp_recv.bind('', TCP_PORT)
        self.udp_recv.start()

        self.sock.bind(HOST, TCP_PORT)
        self.sock.listen(10)

        self.cont_sock.bind(HOST, CONTROL_PORT)
        self.cont_sock.listen(10)

        self.sock.start()
        self.cont_sock.start()

        self.udp_lock = threading.Lock()
        self.udp_listeners = {}
        self.sock.tcp_lost_hook = self.tcp_lost

    def tcp_lost(self, sock, addr):
        with self.udp_lock:
            client_id = self.km.id_from_sock(sock)
            if client_id in self.udp_listeners:
                del self.udp_listeners[client_id]
            self.km.forget(client_id)

    def udp_mainloop(self):
        while True:
            pkt = self.udp_recv.get_packet(True)
            self.log.debug(f'UDP packet from {pkt[1]}: {pkt[2].opcode}')
            if pkt[2].opcode == AUDIO:
                with self.udp_lock:
                    listeners = dict(self.udp_listeners)
                    for i in listeners:
                        if pkt[2].client_id != i:
                            self.udp_send.send_packet(AUDIO, pkt[2].payload, to=listeners[i], client_id=i, origin=pkt[2].client_id)

    def cont_mainloop(self):
        while True:
            pkt = self.cont_sock.get_packet(True)

            self.log.debug(f'CONT packet from {pkt[1]}: {pkt[2].opcode}')
            if pkt[2].opcode == SET_GATE:
                try:
                    client_id = pkt[2].payload[:16]
                    attack, hold, release, threshold, nonce = struct.unpack('!4lH', pkt[2].payload[16:])

                    sock = self.km.sock_from_id(client_id)
                    if sock is not None:
                        self.sock.send_packet(
                            SET_GATE,
                            pkt[2].payload[16:],
                            to=sock,
                            client_id=client_id
                        )
                    self.cont_sock.send_packet(SET_FAIL if sock is None else SET_ACK, struct.pack('!H', nonce), to=pkt[0])
                except struct.error:
                    self.log.warn('Failed to decode CONT packet')
            elif pkt[2].opcode == SET_COMP:
                try:
                    client_id = pkt[2].payload[:16]
                    attack, release, threshold, nonce = struct.unpack('!3lH', pkt[2].payload[16:])

                    sock = self.km.sock_from_id(client_id)
                    if sock is not None:
                        self.sock.send_packet(
                            SET_COMP,
                            pkt[2].payload[16:],
                            to=sock,
                            client_id=client_id
                        )
                    self.cont_sock.send_packet(SET_FAIL if sock is None else SET_ACK, struct.pack('!H', nonce), to=pkt[0])
                except struct.error:
                    self.log.warn('Failed to decode CONT packet')

    def mainloop(self):
        threading.Thread(target=self.udp_mainloop, daemon=True).start()
        threading.Thread(target=self.cont_mainloop, daemon=True).start()

        while True:
            pkt = self.sock.get_packet(True)

            self.log.debug(f'TCP packet from {pkt[1]}: {pkt[2].opcode}')
            if pkt[2].opcode == REGISTER_UDP:
                try:
                    udp_port = struct.unpack('!H', pkt[2].payload)[0]

                    self.udp_listeners[pkt[2].client_id] = (
                        pkt[1][0],  # Source IP
                        udp_port
                    )
                except struct.error:
                    self.log.warn('Invalid packet when registering UDP port')

if __name__ == '__main__':
    Server().mainloop()
