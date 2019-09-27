import struct
import threading

from . import loggers
from .config import HOST, TCP_PORT, CONTROL_PORT
from .opcodes import AUDIO, REGISTER_UDP, SET_GATE, SET_ACK, SET_FAIL, SET_COMP, CLIENT_LEAVE, CLIENT_JOIN, SET_NAME, \
    SET_ROOMS
from .packet_flow import SocketController, SocketMode, KeyManager


def ms(x):
    return round(x * (44100 / 1000))


class StateManager:
    # attack, hold, release, threshold
    DEFAULT_GATE = (ms(3.5), ms(10), ms(10), 950)
    # attack, release, threshold
    DEFAULT_COMP = (ms(1), ms(100), 10000)

    DEFAULT_NAME = 'Nameless?'

    def __init__(self, sock, cont_sock, km):
        self.gates = {}
        self.compressors = {}
        self.names = {}
        self.km = km

        self._sock = sock
        self._sock.state_manager = self

        self.rooms = []

        self._cont_sock = cont_sock
        self._cont_sock.cont_state_manager = self

    def new_cont_client(self, sock, addr, client_id):
        for ci in self.gates:
            r_data = bytearray([n for n in range(len(self.rooms)) if ci in self.rooms[n]])
            r_data.insert(0, len(r_data))
            name = bytearray([len(self.names[ci])])
            name += self.names[ci].encode('latin-1')

            gate, comp = self.gates.get(ci), self.compressors.get(ci)
            if gate and comp and len(gate) == 4 and len(comp) == 3:
                self._cont_sock.send_packet(
                    CLIENT_JOIN,
                    ci + struct.pack('!7H', *gate, *comp) + r_data + name,
                    to=client_id
                )

    def new_client(self, sock, addr, client_id):
        if client_id not in self.gates:
            self.gates[client_id] = self.DEFAULT_GATE
            self.compressors[client_id] = self.DEFAULT_COMP
            self.names[client_id] = self.DEFAULT_NAME

        if len(self.rooms) == 0:
            self.rooms.append([])
        for i in self.rooms:
            if client_id in i:
                break
        else:
            self.rooms[0].append(client_id)

        sock = self.km.sock_from_id(client_id)
        if sock is not None:
            self._sock.send_packet(
                SET_GATE,
                struct.pack('!4lH', *self.gates[client_id], 0),
                to=sock,
                client_id=client_id
            )
            self._sock.send_packet(
                SET_COMP,
                struct.pack('!3lH', *self.compressors[client_id], 0),
                to=sock,
                client_id=client_id
            )

        r_data = bytearray([n for n in range(len(self.rooms)) if client_id in self.rooms[n]])
        r_data.insert(0, len(r_data))
        name = bytearray([len(self.names[client_id])])
        name += self.names[client_id].encode('latin-1')

        self._cont_sock.send_packet(
            CLIENT_JOIN,
            client_id + struct.pack('!7H', *self.gates[client_id], *self.compressors[client_id]) + r_data + name
        )

    def set_rooms(self, client_id, rooms):
        for i in rooms:
            while i >= len(self.rooms):
                self.rooms.append([])

        for n, i in enumerate(self.rooms):
            if client_id in i and n not in rooms:
                i.remove(client_id)
            elif client_id not in i and n in rooms:
                i.append(client_id)

    def lost(self, sock, addr):
        client_id = self.km.id_from_sock(sock)
        if client_id is None:
            return
        if client_id in self.gates:
            del self.gates[client_id]
        if client_id in self.compressors:
            del self.compressors[client_id]
        if client_id in self.names:
            del self.names[client_id]
        for i in self.rooms:
            if client_id in i:
                i.remove(client_id)


class Server:
    def __init__(self):
        self.log = loggers.getLogger(__name__ + '.' + self.__class__.__name__)

        self.km = KeyManager()

        self.sock = SocketController(km=self.km)
        self.cont_sock = SocketController()
        self.udp_recv = SocketController(SocketMode.UDP, km=self.km)
        self.udp_send = SocketController(SocketMode.UDP, km=self.km)

        self.sm = StateManager(self.sock, self.cont_sock, self.km)

        self.udp_recv.bind('', TCP_PORT)
        self.udp_recv.start()

        self.sock.bind(HOST, TCP_PORT)
        self.sock.listen(10)

        self.cont_sock.bind(HOST, CONTROL_PORT)
        self.cont_sock.listen(10)
        self.cont_udp_port = None

        self.sock.start()
        self.cont_sock.start()

        self.udp_lock = threading.Lock()
        self.udp_listeners = {}
        self.sock.tcp_lost_hook = self.tcp_lost

    def tcp_lost(self, sock, addr):
        with self.udp_lock:
            client_id = self.km.id_from_sock(sock)
            if not client_id:
                return

            if client_id in self.udp_listeners:
                del self.udp_listeners[client_id]
            self.km.forget(client_id)

            self.cont_sock.send_packet(CLIENT_LEAVE, client_id)

    def udp_mainloop(self):
        while True:
            pkt = self.udp_recv.get_packet(True)
            self.log.debug(f'UDP packet from {pkt[1]}: {pkt[2].opcode}')
            if pkt[2].opcode == AUDIO:
                with self.udp_lock:
                    listeners = dict(self.udp_listeners)
                    can_listen = set(sum([i for i in self.sm.rooms if pkt[2].client_id in i], []))
                    if self.cont_udp_port is not None:
                        can_listen.add(self.cont_udp_port)

                    for i in can_listen:
                        if pkt[2].client_id != i and i in listeners:
                            self.udp_send.send_packet(AUDIO, pkt[2].payload, to=listeners[i], client_id=i,
                                                      origin=pkt[2].client_id)

    def cont_mainloop(self):
        while True:
            pkt = self.cont_sock.get_packet(True)

            self.log.debug(f'CONT packet from {pkt[1]}: {pkt[2].opcode}')
            if pkt[2].opcode == SET_GATE:
                try:
                    client_id = pkt[2].payload[:16]
                    attack, hold, release, threshold, nonce = struct.unpack('!4lH', pkt[2].payload[16:])
                    attack = max(0, min(65535, attack))
                    hold = max(0, min(65535, hold))
                    release = max(0, min(65535, release))
                    threshold = max(0, min(65535, threshold))

                    sock = self.km.sock_from_id(client_id)
                    if sock is not None:
                        self.sock.send_packet(
                            SET_GATE,
                            pkt[2].payload[16:],
                            to=sock,
                            client_id=client_id
                        )
                        self.sm.gates[client_id] = (attack, hold, release, threshold)
                    self.cont_sock.send_packet(SET_FAIL if sock is None else SET_ACK, struct.pack('!H', nonce),
                                               to=pkt[0])
                except struct.error:
                    self.log.warning('Failed to decode CONT packet')
            elif pkt[2].opcode == SET_COMP:
                try:
                    client_id = pkt[2].payload[:16]
                    attack, release, threshold, nonce = struct.unpack('!3lH', pkt[2].payload[16:])
                    attack = max(0, min(65535, attack))
                    release = max(0, min(65535, release))
                    threshold = max(0, min(65535, threshold))

                    sock = self.km.sock_from_id(client_id)
                    if sock is not None:
                        self.sock.send_packet(
                            SET_COMP,
                            pkt[2].payload[16:],
                            to=sock,
                            client_id=client_id
                        )
                        self.sm.compressors[client_id] = (attack, release, threshold)
                    self.cont_sock.send_packet(SET_FAIL if sock is None else SET_ACK, struct.pack('!H', nonce),
                                               to=pkt[0])
                except struct.error:
                    self.log.warning('Failed to decode CONT packet')
            elif pkt[2].opcode == SET_NAME:
                client_id = pkt[2].payload[:16]
                self.sm.names[client_id] = pkt[2].payload[16:271].decode('latin-1')
            elif pkt[2].opcode == SET_ROOMS:
                client_id = pkt[2].payload[:16]
                room_n = pkt[2].payload[16]
                rooms = pkt[2].payload[17: 17 + room_n]
                self.sm.set_rooms(client_id, rooms)
            elif pkt[2].opcode == REGISTER_UDP:
                try:
                    self.cont_udp_port = struct.unpack('!H', pkt[2].payload)[0]
                except struct.error:
                    self.log.warning('Invalid packet when registering UDP port')

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
                    self.log.warning('Invalid packet when registering UDP port')


if __name__ == '__main__':
    Server().mainloop()
