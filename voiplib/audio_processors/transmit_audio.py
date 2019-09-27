import struct

from .base import AudioProcessor
from ..opcodes import AUDIO


class TransmitAudio(AudioProcessor):
    def __init__(self, sock):
        self.sock = sock

    def process(self, data, sequence, amp):
        data = struct.pack('!H', amp) + data
        self.sock.send_packet(AUDIO, data, sequence=sequence)

    def clone(self):
        return self.__class__(self.sock)

