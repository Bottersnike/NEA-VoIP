import struct

from .._voiplib.crc import CRC
from . import util


class PacketError(Exception):
    pass


class Packet:
    EPOCH = 1563520000

    CRC_LENGTH = 2
    CRC16 = CRC(CRC_LENGTH * 8, 0x1337)

    def __init__(self, opcode, payload, timestamp, sequence, client_id=None):
        self.opcode = opcode
        self.payload = payload
        self.timestamp = timestamp
        self.sequence = sequence
        if client_id is None:
            client_id = b'\0' * 16
        self.client_id = client_id

        self.source_addr = None
        self.source_sock = None

    @classmethod
    def make_bytes(cls, opcode, payload, timestamp, sequence, client_id=None):
        if len(payload) > 0xff_ff:
            raise PacketError('Payload too long')
        if not (0 <= timestamp - cls.EPOCH <= 0xff_ff_ff_ff):
            raise PacketError('Invalid timestamp')

        if client_id is None:
            client_id = b'\0' * 16

        packet = struct.pack('!BIHH', opcode, timestamp - cls.EPOCH, len(payload), sequence)
        packet += client_id
        packet += payload
        packet += cls.CRC16(packet)

        return packet

    def digest(self):
        return self.make_bytes(self.opcode, self.payload, self.timestamp, self.sequence, self.client_id)

    @classmethod
    def from_bytes(cls, packet):
        opcode, timestamp, _, sequence = struct.unpack('!BIHH', packet[:9])
        timestamp += cls.EPOCH
        payload = packet[9:-cls.CRC_LENGTH]
        client_id = payload[:16]
        payload = payload[16:]

        if cls.CRC16(packet[:-cls.CRC_LENGTH]) != packet[-cls.CRC_LENGTH:]:
            raise PacketError('Invalid CRC on packet')

        return cls(opcode, payload, timestamp, sequence, client_id)

    @classmethod
    def from_pipe(cls, pipe):
        head = util.read(pipe, 9)
        opcode, timestamp, length, sequence = struct.unpack('!BIHH', head)
        timestamp += cls.EPOCH
        client_id = util.read(pipe, 16)
        payload = util.read(pipe, length)
        crc = util.read(pipe, cls.CRC_LENGTH)

        if cls.CRC16(head + client_id + payload) != crc:
            raise PacketError('Invalid CRC on packet')

        return cls(opcode, payload, timestamp, sequence, client_id)
