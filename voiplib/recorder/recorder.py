import base64

from ..util.opus import OpusDecoder
from .. import loggers


class Recorder:
    FLUSH_EVERY = 10

    def __init__(self) -> None:
        self.recording = set()
        self.rec_start = {}

        self.recordings = {}
        self._counts = {}
        self._decoders = {}

        self.log = loggers.getLogger(__name__ + '.' + self.__class__.__name__)
    
    def gen_filename(self, client_id: bytes) -> str:
        """
        Generate a filename for a given client id.
        
        :param bytes client_id: The client id being recorded
        """
        return './recording/' + base64.b64encode(client_id).strip(b'=').decode().replace('/', '_')

    def feed(self, client_id: bytes, audio: bytes) -> None:
        """
        Feed a frame of audio into the recorder.

        :param bytes client_id: The client id of the speaker
        :param bytes audio: The frame of audio to record
        """
        # Check if we are actually recording them
        if client_id not in self.recording:
            return

        # Setup initial recording state for new clients
        if client_id not in self.recordings:
            self.recordings[client_id] = Recording(
                self.gen_filename(client_id))
            self._decoders[client_id] = OpusDecoder()
            self._counts[client_id] = 0
        
        # Decode the audio from Opus to PCM
        audio = self._decoders[client_id].decode(audio[2:])
        if audio is None:
            self.log.warning('Failed to decode audio!')
            return
        # Forward the PCM to the recorder
        self.recordings[client_id].write(audio)

        # Increment the counter and check if we need to flush the byffers
        self._counts[client_id] += 1
        if self._counts[client_id] >= self.FLUSH_EVERY:
            self.recordings[client_id].flush()
            self.recordings[client_id].finish()
            self._counts[client_id] = 0
