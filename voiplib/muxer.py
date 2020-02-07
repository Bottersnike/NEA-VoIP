import threading

import numpy as np


class Muxer:
    """
    Mix multiple streams of audio info a single output stream.
    """
    BUFFER = 1

    def __init__(self) -> None:
        """
        Create a new muxer instance.
        """
        self._frames = {}
        self._has_frame = threading.Event()

    def write(self, frame: bytes, client: bytes) -> None:
        """
        Write a single frame into a muxer buffer.

        :param bytes frame: The frame audio data
        :param btyes client: The client id repsonsible for the audio
        """
        # Ensure we have a buffer for this client
        if client not in self._frames:
            self._frames[client] = []

        # Very quickly decode the audio in the frame
        frame = np.ndarray((len(frame) // 2,), '<h', frame)

        # Buffer and flush the frame
        self._frames[client].append(frame)
        while len(self._frames[client]) > self.BUFFER:
            self._frames[client].pop(0)
        # Alert other threads that there is new data in the buffer
        self._has_frame.set()

    def read(self) -> bytes:
        """
        Read a single frame of audio from the mix.
        """
        for i in self._frames:
            if len(self._frames[i]) > 0:
                break
        else:
            self._has_frame.clear()
            self._has_frame.wait()

        frame = np.zeros((960,), dtype='<i')

        for i in list(self._frames.keys()):
            if not self._frames[i]:
                continue
            layer = self._frames[i].pop(0)
            if layer.shape != frame.shape:
                print('Shape error!')
                continue
            frame += layer
            frame.clip(-1 << 15, (1 << 15) - 1)

        return frame.astype('<h').tobytes('C')
