import struct
import threading

import numpy as np
import pyaudio

from .audio_processors import OpusEncProcessor, OpusDecProcessor
from .util.packets import Packet
from .muxer import Muxer
from . import loggers


class AudioIO:
    """
    The main class responsible for audio input, output, and pipelineing.
    """

    CHUNK = 256

    def __init__(self) -> None:
        self.log = loggers.getLogger(__name__ + '.' + self.__class__.__name__)
        self.pa = pyaudio.PyAudio()

        # Locate all input and output audio hardware devices
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

        # Bind to the most appropriate input and output devices
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

        # Create our two dummy pipelines
        self.pipeline = [OpusEncProcessor()]
        self.back_pipeline = [OpusDecProcessor()]
        self._back_pipeline = {}

        # Setup a muxer instance for the output pipeline
        self.muxer = Muxer()

    def begin(self) -> None:
        """
        Start the audio interface and begin feeding the pipelines
        """
        threading.Thread(target=self._audio_player, daemon=True).start()
        threading.Thread(target=self._in_watcher, daemon=True).start()

    def _audio_player(self) -> None:
        """
        Constantly flush data from the muxer and feed it to the output device
        """
        while True:
            frame = self.muxer.read()
            if frame is None:
                continue
            self.out_stream.write(frame)

    def _new_pipeline(self, client_id: bytes) -> None:
        """
        Setup a new client-specific pipleine for processing pre-mix
        """
        self._back_pipeline[client_id] = [
            i.clone() for i in self.back_pipeline
        ]

    def feed(self, data: bytes, packet: Packet) -> None:
        """
        Feed audio into the pipeline

        :param bytes data: The audio data
        :param Packet packet: The Packet, including metadata 
        """
        # The first two bytes of the data are an unsigned short containg the
        # rms aplitude
        amp = struct.unpack('!H', data[:2])[0]

        # If this client doesn't exist in our pipelines, create a new one for
        # them.
        if packet.client_id not in self._back_pipeline:
            self._new_pipeline(packet.client_id)

        data = data[2:]
        # Feed the data through the pipeline
        for i in self._back_pipeline[packet.client_id]:
            data = i(data, packet, amp)
            # Someone wants us to stop
            if data is None:
                return

        # Let the muxer know there's new data
        self.muxer.write(data, packet.client_id)

    def _in_watcher(self) -> None:
        """
        This thread monitors the incomming audio stream and spawns a new thread
        each time there is aditional data to process.

        As Python threads are very cheap to create, this is an acceptable use
        as the execution is significantly slowed if the data handler fails to
        complete before the next chunk of data is waiting in the buffer.
        """
        sequence = 0
        while True:
            data = self.in_stream.read(
                self.CHUNK, exception_on_overflow=False)
            threading.Thread(target=self._handle_in_data,
                             args=(data, sequence)).start()

    def _handle_in_data(self, data: bytes, sequence: int) -> None:
        """
        Processing incomming data.
        If this data is from a socket, we will want to know the order it came
        in. This is just transparently passed down to pipeline modules,
        however, so is of little concern here.

        :param bytes data: The raw PCM data
        :param int sequence: The audio sequence number
        """
        # Calculate the RMS of the audio
        samps = np.ndarray((len(data) // 2), '<h', data).astype(np.int32)
        amp = np.sqrt(np.mean(samps ** 2))
        amp = int(amp)

        # Show a visualisation of the RMS, enabled for testing
        if False:
            print(('*' * int((amp / 32768) * 500)).center(300))

        # Pass the data down through the pipeline
        for i in self.pipeline:
            data = i(data, sequence, amp)
            # Someone wants us to stop
            if data is None:
                break
