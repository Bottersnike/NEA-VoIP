from .base import AudioProcessor
from .._voiplib.audio import Compressor as Compressor_


class Compressor(AudioProcessor):
    def __init__(self, attack, release, threshold, exp=0.9):
        self.comp = Compressor_(attack, release, threshold, exp)

    def process(self, data, *args):
        return self.comp.feed(data)
