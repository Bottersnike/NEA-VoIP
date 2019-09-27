from .base import AudioProcessor
from .. import loggers
from ..util.opus import OpusEncoder, OpusDecoder


class OpusEncProcessor(AudioProcessor):
    def __init__(self):
        self.log = loggers.getLogger(__name__ + '.' + self.__class__.__name__)

        self.encoder = OpusEncoder()
        self.buffer = b''

    def process(self, data, *args):
        self.buffer += data
        if len(self.buffer) < self.encoder.FRAME_SIZE:
            return
        frame = self.buffer[:self.encoder.FRAME_SIZE]
        self.buffer = self.buffer[self.encoder.FRAME_SIZE:]
        if len(self.buffer) > self.encoder.FRAME_SIZE:
            self.log.warn('Audio underrun detected! Flushing buffer!')
            self.buffer = self.buffer[:self.encoder.FRAME_SIZE]

        return self.encoder.encode(frame)


class OpusDecProcessor(AudioProcessor):
    def __init__(self):
        self.decoder = OpusDecoder()

    def process(self, data, *args):
        # noinspection PyBroadException
        try:
            return self.decoder.decode(data)
        except:
            return None
