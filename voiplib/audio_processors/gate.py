from .base import AudioProcessor
from .._voiplib.audio import Gate as Gate_


class Gate(AudioProcessor):
    def __init__(self, attack, hold, release, threshold, exp=0.9):
        self.gate = Gate_(attack, hold, release, threshold, exp)

    def process(self, data, *args):
        return self.gate.feed(data)
