from .base import AudioProcessor


class NullSink(AudioProcessor):
    def process(self, *args):
        return None
