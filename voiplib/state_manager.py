import struct

from .opcodes import *


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

    def new_cont_client(self, _, __, client_id):
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

    def new_client(self, _, __, client_id):
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

    def set_name(self, client_id, name):
        self.names[client_id] = name

    def set_gate(self, client_id, gate):
        self.gates[client_id] = gate

    def set_compressor(self, client_id, compressor):
        self.compressors[client_id] = compressor

    def lost(self, sock, _):
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
