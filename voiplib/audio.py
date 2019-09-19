import threading
import pyaudio
import struct
import numpy as np
import time
import math

# pylint: disable=E0611
from ._voiplib.audio import Compressor as Compressor_
from ._voiplib.audio import Gate as Gate_
from .util.opus import OpusEncoder, OpusDecoder
from . import loggers


class AudioProcessor:
    def process(self, data, *args):
        return data

    def __call__(self, data, *args):
        return self.process(data, *args)

    def clone(self):
        return self.__class__()


class Gate(AudioProcessor):
    def __init__(self, attack, hold, release, threshold, exp=0.9):
        self.gate = Gate_(attack, hold, release, threshold, exp)

    def process(self, data, *args):
        return self.gate.feed(data)


class Compressor(AudioProcessor):
    def __init__(self, attack, release, threshold, exp=0.9):
        self.comp = Compressor_(attack, release, threshold, exp)

    def process(self, data, *args):
        return self.comp.feed(data)


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
        try:
            return self.decoder.decode(data)
        except:
            return None


class PrintData(AudioProcessor):
    def process(self, data, *args):
        print(data)
        return data


class Muxer:
    BUFFER = 1

    def __init__(self):
        self._frames = {}
        self._has_frame = threading.Event()

    def write(self, frame, client):
        if client not in self._frames:
            self._frames[client] = []

        frame = np.ndarray((len(frame) // 2, ), '<h', frame)# struct.unpack(f'<{len(frame) // 2}h', frame)

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

        frame = np.zeros((960, ), dtype='<i')

        for i in list(self._frames.keys()):
            if not self._frames[i]:
                continue
            frame += self._frames[i].pop(0)
            frame.clip(-1<<15, (1<<15)-1)

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

    def begin(self, debug=False):
        threading.Thread(target=self._audio_player, daemon=True).start()
        t = threading.Thread(target=self._in_watcher, daemon=True)
        t.start()
        if debug:
            self.pipeline.append(PrintData())
            t.join()

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
            # start = time.time()
            data = i(data, packet, amp)
            # dur = time.time() - start
            #if dur > self.CHUNK / 44100:
            #    print(id(i), i.__class__.__name__, dur)
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
        #amp = max(map(abs, samps))# / len(samps)
        amp = np.sqrt(np.mean(samps ** 2))
        amp = int(amp)

        print(('*' * int((amp / 32768) * 500)).center(300))
        #print(amp)

        for i in self.pipeline:
            #start = time.time()
            data = i(data, sequence, amp)
            #dur = time.time() - start
            #if dur > self.CHUNK / 44100:
            #    print(id(i), i.__class__.__name__, dur)
            # Someone wants us to stop
            if data is None:
                break


if __name__ == '__main__':
    AudioIO().begin(True)
