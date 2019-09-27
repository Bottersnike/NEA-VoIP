import struct
import threading

import numpy as np
import pyaudio

from . import loggers

from .audio_processors import OpusEncProcessor, OpusDecProcessor


class Muxer:
    BUFFER = 1

    def __init__(self):
        self._frames = {}
        self._has_frame = threading.Event()

    def write(self, frame, client):
        if client not in self._frames:
            self._frames[client] = []

        frame = np.ndarray((len(frame) // 2,), '<h', frame)

        self._frames[client].append(frame)
        while len(self._frames[client]) > self.BUFFER:
            self._frames[client].pop(0)
        self._has_frame.set()

    def read(self):
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


class AudioIO:
    CHUNK = 256

    def __init__(self):
        self.log = loggers.getLogger(__name__ + '.' + self.__class__.__name__)
        self.pa = pyaudio.PyAudio()

        self.inputs = []
        self.outputs = []
        for i in range(self.pa.get_device_count()):
            info = self.pa.get_device_info_by_index(i)
            idata = (
                i, info['name'], info['hostApi'], info['defaultSampleRate']
            )
            if info['maxInputChannels']:
                self.inputs.append(idata)
            if info['maxOutputChannels']:
                self.outputs.append(idata)

        if not self.inputs or not self.outputs:
            # TODO: This
            ...

        self.in_stream = self.pa.open(
            channels=1,
            format=8,
            rate=int(self.inputs[0][3]),
            input=True,
            frames_per_buffer=self.CHUNK,
            input_device_index=self.inputs[0][0]
        )
        self.out_stream = self.pa.open(
            channels=1,
            format=8,
            rate=int(self.outputs[0][3]),
            output=True,
            frames_per_buffer=self.CHUNK,
            input_device_index=self.outputs[0][0]
        )

        self.log.info(f'Opened "{self.inputs[0][1]}" as input')
        self.log.info(f'   and "{self.outputs[0][1]}" as output')

        self.pipeline = [OpusEncProcessor()]
        self.back_pipeline = [OpusDecProcessor()]
        self._back_pipeline = {}

        self.muxer = Muxer()

    def begin(self):
        threading.Thread(target=self._audio_player, daemon=True).start()
        t = threading.Thread(target=self._in_watcher, daemon=True)
        t.start()

    def _audio_player(self):
        while True:
            frame = self.muxer.read()
            if frame is None:
                continue
            self.out_stream.write(frame)

    def _new_pipeline(self, client_id):
        self._back_pipeline[client_id] = [i.clone() for i in self.back_pipeline]

    def feed(self, data, packet):
        amp = struct.unpack('!H', data[:2])[0]

        if packet.client_id not in self._back_pipeline:
            self._new_pipeline(packet.client_id)

        data = data[2:]
        for i in self._back_pipeline[packet.client_id]:
            data = i(data, packet, amp)
            # Someone wants us to stop
            if data is None:
                return

        self.muxer.write(data, packet.client_id)

    def _in_watcher(self):
        sequence = 0
        while True:
            data = self.in_stream.read(self.CHUNK, exception_on_overflow=False)
            threading.Thread(target=self._handle_in_data, args=(data, sequence)).start()

    def _handle_in_data(self, data, sequence):
        samps = np.ndarray((len(data) // 2), '<h', data).astype(np.int32)
        amp = np.sqrt(np.mean(samps ** 2))
        amp = int(amp)

        if False:
            print(('*' * int((amp / 32768) * 500)).center(300))

        for i in self.pipeline:
            data = i(data, sequence, amp)
            # Someone wants us to stop
            if data is None:
                break
