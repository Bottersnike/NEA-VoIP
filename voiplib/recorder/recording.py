from io import BytesIO
import threading
import os

from .wav_file import WAVFile


class Recording:
    def __init__(self, path: str) -> None:
        # Parse the path and split it
        path = os.path.abspath(os.path.expanduser(path))
        self._dirname = os.path.dirname(path)
        self._filename = os.path.basename(path)
        os.makedirs(self._dirname, exist_ok=True)

        # Create the in-memory PCM buffer
        self._buffer = BytesIO()

        # Temp file lock
        self._temp_lock = threading.Lock()

    @property
    def path(self):
        """
        The path to be used for the final recording
        """
        return os.path.join(self._dirname, self._filename + '.wav')
    
    @property
    def tmp_path(self) -> str:
        """
        The path to be used for the tempfile
        """
        return os.path.join(self._dirname, '~' + self._filename + '.pcm')
    
    def write(self, pcm: bytes) -> None:
        """
        Write a frame of PCM audio to the memory buffer
        """
        self._buffer.write(pcm)
    
    def flush(self) -> None:
        """
        Flush the PCM buffer from memory to disk
        """
        with self._temp_lock:
            self._buffer.seek(0)
            # Open the file for writing and flush the buffer
            with open(self.tmp_path, 'ab') as file_:
                file_.write(self._buffer.read())
            # Truncate the buffer at the start to clear it
            self._buffer.seek(0)
            self._buffer.truncate()
        
    def finish(self) -> None:
        """
        Flush the PCM buffer from disk to the final output WAV file
        """
        with self._temp_lock:
            if os.path.exists(self.tmp_path):
                new = not os.path.exists(self.path)

                # Open both files for reading and writing
                with open(self.path, 'wb' if new else 'r+b') as wav_file:
                    with open(self.tmp_path, 'rb') as pcm_file:
                        # Write the wav file
                        wav = WAVFile(wav_file, new=new)
                        wav.write(pcm_file.read())

                # Clean up the PCM buffer
                os.remove(self.tmp_path)
