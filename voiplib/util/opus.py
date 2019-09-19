from ctypes import (
    POINTER, c_int, c_int32, c_char_p, Structure, c_int16, CDLL, byref, cast, c_char, cdll
)
import ctypes.util
import array
import sys
import os


if sys.platform == 'win32':
    opuslib = CDLL(os.path.join(os.path.dirname(__file__), '../bin/libopus-0.x64.dll'))
else:
    opuslib = cdll.LoadLibrary(ctypes.util.find_library('opus'))


class OpusEncoder_(Structure): pass
class OpusDecoder_(Structure): pass
class OpusError(Exception): pass


FUNCTIONS = {
    'opus_encoder_create': (
        (c_int, c_int, c_int, POINTER(c_int)),
        POINTER(OpusEncoder_)),
    'opus_encoder_ctl': (None, c_int32),

    'opus_decoder_create': (
        (c_int, c_int, POINTER(c_int)),
        POINTER(OpusDecoder_)),

    'opus_decode': (
        (POINTER(OpusDecoder_), c_char_p, c_int32, POINTER(c_int16), c_int, c_int),
        c_int),
    'opus_encode': (
        (POINTER(OpusEncoder_), POINTER(c_int16), c_int, c_char_p, c_int32),
        c_int32),

    'opus_encoder_destroy': ((POINTER(OpusEncoder_), ), None),
    'opus_decoder_destroy': ((POINTER(OpusDecoder_), ), None),

    'opus_packet_get_samples_per_frame': ((c_char_p, c_int), c_int),
    'opus_packet_get_nb_frames': ((c_char_p, c_int), c_int),
    'opus_packet_get_nb_channels': ((c_char_p, ), c_int),
}
for i in FUNCTIONS:
    func = getattr(opuslib, i)
    if FUNCTIONS[i][0] is not None:
        func.argtypes = FUNCTIONS[i][0]
    func.restype = FUNCTIONS[i][1]


class OpusEncoder:
    SAMPLE_RATE = 48000
    CHANNELS = 1

    FRAME_LENGTH = 20
    SAMPLE_SIZE = 2 # (bit_rate / 8) * CHANNELS (bit_rate == 16)
    SAMPLES_PER_FRAME = int(SAMPLE_RATE / 1000 * FRAME_LENGTH)

    FRAME_SIZE = SAMPLES_PER_FRAME * SAMPLE_SIZE

    APPLICATION_AUDIO    = 2049
    APPLICATION_VOIP     = 2048
    APPLICATION_LOWDELAY = 2051
    CTL_SET_BITRATE      = 4002
    CTL_SET_BANDWIDTH    = 4008
    CTL_SET_FEC          = 4012
    CTL_SET_PLP          = 4014
    CTL_SET_SIGNAL       = 4024

    def __init__(self):
        err = c_int()
        self.encoder = opuslib.opus_encoder_create(
            self.SAMPLE_RATE, self.CHANNELS, self.APPLICATION_VOIP, byref(err)
        )
        if err.value < 0:
            raise OpusError(err)
        self.set_bitrate(128)

    def set_bitrate(self, kbps):
        opuslib.opus_encoder_ctl(
            self.encoder, self.CTL_SET_BITRATE, int(kbps * 1024)
        )

    def encode(self, pcm, frame_size=None):
        if frame_size is None:
            frame_size = self.SAMPLES_PER_FRAME

        max_data_bytes = len(pcm)
        pcm = cast(pcm, POINTER(c_int16))
        data = (c_char * max_data_bytes)()

        res = opuslib.opus_encode(self.encoder, pcm, frame_size, data, max_data_bytes)
        if res < 0:
            raise OpusError(res)

        return array.array('b', data[:res]).tobytes()


class OpusDecoder:
    def __init__(self):
        err = c_int()
        self.decoder = opuslib.opus_decoder_create(
            OpusEncoder.SAMPLE_RATE, OpusEncoder.CHANNELS, byref(err)
        )
        if err.value < 0:
            raise OpusError(err)

    def decode(self, data, frame_size=None, fec=False):
        if frame_size is None:
            frames = opuslib.opus_packet_get_nb_frames(data, len(data))
            samples_per_frame = opuslib.opus_packet_get_samples_per_frame(data, OpusEncoder.SAMPLE_RATE)
            # channels = opuslib.opus_packet_get_nb_channels(data)

            frame_size = frames * samples_per_frame

        pcm_size = frame_size * OpusEncoder.CHANNELS
        pcm = (c_int16 * pcm_size)()
        pcm_ptr = cast(pcm, POINTER(c_int16))

        res = opuslib.opus_decode(self.decoder, data, len(data), pcm_ptr, frame_size, int(fec))
        if res < 0:
            raise OpusError(res)

        return array.array('h', pcm).tobytes()
