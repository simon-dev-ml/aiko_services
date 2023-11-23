# Installation (Ubuntu)
# ~~~~~~~~~~~~
# sudo apt-get install portaudio19-dev  # Provides "portaudio.h"
# pip install pyaudio sounddevice
#
# Usage
# ~~~~~
# aiko_pipeline create ../../examples/pipeline/pipeline_mic_fft_graph.json
#
# On "Spectrum" window, press "x" to exit
#
# Resources
# ~~~~~~~~~
# https://people.csail.mit.edu/hubert/pyaudio/#downloads  # Install PyAudio
# https://realpython.com/playing-and-recording-sound-python
# https://stackoverflow.com/questions/62159107/python-install-correct-pyaudio
#
# To Do
# ~~~~~
# - Ensure that Registar interaction occurs prior to flooding the Pipeline !
#
# - Implement Microphone PipelineElement start_stream(), move __init__() code

from hashlib import md5
from io import BytesIO
import numpy as np
from typing import Tuple
import zlib

from aiko_services import aiko, PipelineElement
from aiko_services.utilities import get_namespace

__all__ = [
    "PE_AudioFilter", "PE_AudioResampler",
    "PE_FFT", "PE_GraphXY",
    "PE_MicrophonePA", "PE_MicrophoneSD", "PE_Speaker"
]

_LOGGER = aiko.logger(__name__)

# --------------------------------------------------------------------------- #
# TODO: Turn some of these literals into PipelineElement parameters
# TODO: Place some of these PipelineElement parameters into self.state[]
# TODO: Update via ECProducer

AF_AMPLITUDE_MINIMUM = 0.1
AF_AMPLITUDE_MAXIMUM = 12
AF_FREQUENCY_MINIMUM = 10    # Hertz
AF_FREQUENCY_MAXIMUM = 9000  # Hertz
AF_SAMPLES_MAXIMUM = 100

class PE_AudioFilter(PipelineElement):
    def __init__(self,
        implementations, name, protocol, tags, transport,
        definition, pipeline):

        protocol = "audio_filter:0"
        implementations["PipelineElement"].__init__(self,
            implementations, name, protocol, tags, transport,
            definition, pipeline)

    def process_frame(self,
        context, amplitudes, frequencies) -> Tuple[bool, dict]:

        data = list(zip(np.abs(frequencies), amplitudes))
        data = [(x,y) for x,y in data if y >= AF_AMPLITUDE_MINIMUM]
        data = [(x,y) for x,y in data if x >= AF_FREQUENCY_MINIMUM]
        data = [(x,y) for x,y in data if y <= AF_AMPLITUDE_MAXIMUM]
        data = [(x,y) for x,y in data if x <= AF_FREQUENCY_MAXIMUM]
        amplitude_key = 1
        data = sorted(data, key=lambda x: x[amplitude_key], reverse=True)
        data = data[:AF_SAMPLES_MAXIMUM]
        if len(data):
            frequencies, amplitudes = zip(*data)
        else:
            frequencies, amplitudes = [], []

        return True, {"amplitudes": amplitudes, "frequencies": frequencies}

# --------------------------------------------------------------------------- #
# TODO: Turn some of these literals into PipelineElement parameters
# TODO: Place some of these PipelineElement parameters into self.state[]
# TODO: Update via ECProducer

AR_BAND_COUNT = 8

class PE_AudioResampler(PipelineElement):
    def __init__(self,
        implementations, name, protocol, tags, transport,
        definition, pipeline):

        protocol = "resample:0"
        implementations["PipelineElement"].__init__(self,
            implementations, name, protocol, tags, transport,
            definition, pipeline)

        self.counter = 0

# Frequencies: [0:2399] --> 0, 10, 20, ... 23990 Hz
# Extract 0 to 8000 Hz
# Consolidate that into 8 bands !
# Check the maths and the normalization !

    def process_frame(self,
        context, amplitudes, frequencies) -> Tuple[bool, dict]:

        amplitudes = amplitudes[0:len(amplitudes) // 2]     # len: 2400
        frequencies = frequencies[0:len(frequencies) // 2]  # len: 2400

        frequency_range = frequencies[-1] - frequencies[0]  # 23990.0
        band_width = frequency_range / AR_BAND_COUNT / 10      # 299.875  # TODO: MAGIC NUMBER !!
        band_frequencies = []
        band_amplitudes = []

        for band in range(AR_BAND_COUNT):
            band_start = band * band_width
            band_end = band_start + band_width

        # TODO: Easier to just use indices / slices, rather than a mask ?
            mask = (frequencies >= band_start) & (frequencies < band_end)
            amplitudes_sum = np.sum(amplitudes[mask])

            band_frequency_count = np.sum(mask)
            normalized_amplitudes_sum = amplitudes_sum / band_frequency_count

            band_frequencies.append((band_start + band_end) / 2)
            band_amplitudes.append(amplitudes_sum)
        #   band_amplitudes.append(normalized_amplitudes_sum)

        frequencies = np.array(band_frequencies)
        amplitudes = np.array(band_amplitudes)

        topic_path = "aiko/esp32_ed6cxc/0/0/in"
        self.counter += 1
        if self.counter % 5:
            aiko.message.publish(topic_path, "(led:fill 0 0 0)")
            x = 0
            for frequency, amplitude in zip(frequencies, amplitudes):
                print(f"Band: {frequency:.0f} Hz, amplitude: {amplitude:.4f}")
                a = f"{amplitude:.0f}"
                payload_out = f"(led:line 255 0 0 {x} 0 {x} {a})"
                aiko.message.publish(topic_path, payload_out)
                x += 1
            aiko.message.publish(topic_path, "(led:write)")

        return True, {}

# --------------------------------------------------------------------------- #
# TODO: Turn some of these literals into PipelineElement parameters
# TODO: Place some of these PipelineElement parameters into self.state[]
# TODO: Update via ECProducer

FFT_AMPLITUDE_SCALER = 1_000_000

class PE_FFT(PipelineElement):
    def __init__(self,
        implementations, name, protocol, tags, transport,
        definition, pipeline):

        protocol = "fft:0"
        implementations["PipelineElement"].__init__(self,
            implementations, name, protocol, tags, transport,
            definition, pipeline)

    def process_frame(self, context, audio) -> Tuple[bool, dict]:
        fft_output = np.fft.fft(audio)

        amplitudes = np.abs(fft_output / FFT_AMPLITUDE_SCALER)
        top_index = np.argmax(amplitudes)

        frequencies = np.fft.fftfreq(
            PA_AUDIO_CHUNK_SIZE, 1 / PA_AUDIO_SAMPLE_RATE)
        top_amplitude = int(amplitudes[top_index])
        top_frequency = np.abs(frequencies[top_index])
        _LOGGER.debug(
            f"{self._id(context)} Loudest: {top_frequency} Hz: {top_amplitude}")

        return True, {"amplitudes": amplitudes, "frequencies": frequencies}

# --------------------------------------------------------------------------- #
# TODO: Turn some of these literals into PipelineElement parameters
# TODO: Place some of these PipelineElement parameters into self.state[]
# TODO: Update via ECProducer

import cv2
import io
from PIL import Image
import pygal

GRAPH_FRAME_PERIOD = 1  # milliseconds
GRAPH_TITLE = "Spectrum"
WINDOW_TITLE = GRAPH_TITLE

class PE_GraphXY(PipelineElement):
    def __init__(self,
        implementations, name, protocol, tags, transport,
        definition, pipeline):

        protocol = "graph_xy:0"
        implementations["PipelineElement"].__init__(self,
            implementations, name, protocol, tags, transport,
            definition, pipeline)

    def process_frame(self,
        context, amplitudes, frequencies) -> Tuple[bool, dict]:

        data = list(zip(np.abs(frequencies), amplitudes))

        graph = pygal.XY(
            x_title="Frequency (Hz)", y_title="Amplitude", stroke=False)
        graph.title = GRAPH_TITLE
    #   graph.x_limit = [0, AF_FREQUENCY_MAXIMUM]  # Fails :(
    #   graph.y_limit = [0, AF_AMPLITUDE_MAXIMUM]  # Fails :(
        graph.add("Audio", data)
        graph.add("Limit",
            [(0, 0), (AF_FREQUENCY_MAXIMUM, AF_AMPLITUDE_MAXIMUM)])

        memory_file = io.BytesIO()
        graph.render_to_png(memory_file)
        memory_file.seek(0)
        image = Image.open(memory_file)
        image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        cv2.imshow(WINDOW_TITLE, image)
        if cv2.waitKey(GRAPH_FRAME_PERIOD) & 0xff == ord('x'):
            return False, {}
        else:
            return True, {"amplitudes": amplitudes, "frequencies": frequencies}

# --------------------------------------------------------------------------- #
# TODO: Turn some of these literals into PipelineElement parameters
# TODO: Place some of these PipelineElement parameters into self.state[]
# TODO: Update via ECProducer

import pyaudio
from threading import Thread

PA_AUDIO_CHANNELS = 1              # 1 or 2 channels
PA_AUDIO_FORMAT = pyaudio.paInt16

PA_AUDIO_SAMPLE_RATE = 16000       # voice 16,000 or 44,100 or 48,000 Hz
# PA_AUDIO_SAMPLE_RATE = 48000     # music / spectrum analyser

PA_AUDIO_CHUNK_SIZE = PA_AUDIO_SAMPLE_RATE * 2          # Voice: 2.0 seconds
# PA_AUDIO_CHUNK_SIZE = int(PA_AUDIO_SAMPLE_RATE / 10)  # FFT:   0.1 seconds

def py_error_handler(filename, line, function, err, fmt):
    pass

from ctypes import *

def hide_alsa_messages():
    ERROR_HANDLER_FUNC = CFUNCTYPE(
        None, c_char_p, c_int, c_char_p, c_int, c_char_p)
    c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
    asound = cdll.LoadLibrary("libasound.so")
    asound.snd_lib_error_set_handler(c_error_handler)

import os
import platform
import sys

def pyaudio_initialize():
    if platform.system() == "Linux":
        hide_alsa_messages()  # Fails on Mac OS X and Windows
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    sys.stderr.flush()
    os.dup2(devnull, 2)
    os.close(devnull)

    py_audio = pyaudio.PyAudio()

    os.dup2(old_stderr, 2)
    os.close(old_stderr)
    return py_audio

class PE_MicrophonePA(PipelineElement):
    def __init__(self,
        implementations, name, protocol, tags, transport,
        definition, pipeline):

        protocol = "microphone:0"
        implementations["PipelineElement"].__init__(self,
            implementations, name, protocol, tags, transport,
            definition, pipeline)

        self.state["frame_id"] = -1

        self.py_audio = pyaudio_initialize()
        self.audio_stream = self.py_audio.open(
            channels=PA_AUDIO_CHANNELS,
            format=PA_AUDIO_FORMAT,
            frames_per_buffer=PA_AUDIO_CHUNK_SIZE,
            input=True,
            rate=PA_AUDIO_SAMPLE_RATE)
        self.pipeline.create_stream(0)
        self.thread = Thread(target=self._audio_run).start()

    def _audio_run(self):
        self.terminate = False
        while not self.terminate:
            audio_sample_raw = self.audio_stream.read(PA_AUDIO_CHUNK_SIZE)
            audio_sample = np.frombuffer(audio_sample_raw, dtype=np.int16)

            frame_id = self.state["frame_id"] + 1
            self.ec_producer.update("frame_id", frame_id)
            context = {"stream_id": 0, "frame_id": frame_id}
            self.pipeline.create_frame(context, {"audio": audio_sample})

        self.audio_stream.close()
        self.py_audio.terminate()

    def process_frame(self, context, audio) -> Tuple[bool, dict]:
    #   _LOGGER.debug(f"{self._id(context)} len(audio): {len(audio)}")
        return True, {"audio": audio}

    def stop_stream(self, context, stream_id):
        _LOGGER.debug(f"{self._id(context)}: stop_stream()")
        self.terminate = True

# --------------------------------------------------------------------------- #
# TODO: Turn some of these literals into Pipeline parameters

SD_AUDIO_CHANNELS = 1            # 1 or 2 channels

SD_AUDIO_CHUNK_DURATION = 3.0    # voice: audio chunk duration in seconds
# SD_AUDIO_CHUNK_DURATION = 0.1  # music / spectrum analyser

SD_AUDIO_SAMPLE_DURATION = 3.0   # audio sample size to process
SD_AUDIO_SAMPLE_RATE = 16000     # voice 16,000 or 44,100 or 48,000 Hz
# SD_AUDIO_SAMPLE_RATE = 48000   # music / spectrum analyser

SD_SAMPLES_PER_CHUNK = SD_AUDIO_SAMPLE_RATE * SD_AUDIO_CHUNK_DURATION

import sounddevice as sd

class PE_MicrophoneSD(PipelineElement):
    def __init__(self,
        implementations, name, protocol, tags, transport,
        definition, pipeline):

        protocol = "microphone:0"
        implementations["PipelineElement"].__init__(self,
            implementations, name, protocol, tags, transport,
            definition, pipeline)

        self.state["frame_id"] = -1
        self.pipeline.create_stream(0)
        self._thread = Thread(target=self._audio_run).start()

    def _audio_run(self):
        self.terminate = False
        self._audio_sampler_start()
        with sd.InputStream(callback=self._audio_sampler,
            channels=SD_AUDIO_CHANNELS, samplerate=SD_AUDIO_SAMPLE_RATE):

            while not self.terminate:
                sd.sleep(int(SD_AUDIO_CHUNK_DURATION * 1000))

    def _audio_sampler_start(self):
        frame_id = self.state["frame_id"] + 1
        self.ec_producer.update("frame_id", frame_id)
        self._audio_sample = np.empty((0, 1), dtype=np.float32)
        return frame_id - 1

    def _audio_sampler(self, indata, frames, time_, status):
        if status:
            _LOGGER.error(f"SoundDevice error: {status}")
        else:
        #   _LOGGER.debug(f"SoundDevice callback: {len(indata)} bytes")
            self._audio_sample = np.concatenate(
                (self._audio_sample, indata.copy().astype(np.float32)), axis=0)
            if len(self._audio_sample) > SD_SAMPLES_PER_CHUNK:
                audio_sample = self._audio_sample
                frame_id = self._audio_sampler_start()
                context = {"stream_id": 0, "frame_id": frame_id}
                self.pipeline.create_frame(context, {"audio": audio_sample})

    def process_frame(self, context, audio) -> Tuple[bool, dict]:
    #   _LOGGER.debug(f"{self._id(context)} len(audio): {len(audio)}")
        return True, {"audio": audio}

    def stop_stream(self, context, stream_id):
        _LOGGER.debug(f"{self._id(context)}: stop_stream()")
        self.terminate = True

# --------------------------------------------------------------------------- #

TOPIC_AUDIO = f"{get_namespace()}/audio"

class PE_RemoteReceive0(PipelineElement):
    def __init__(self,
        implementations, name, protocol, tags, transport,
        definition, pipeline):

        protocol = "remote_receive:0"
        implementations["PipelineElement"].__init__(self,
            implementations, name, protocol, tags, transport,
            definition, pipeline)

        self.state["frame_id"] = 0
        self.state["topic_audio"] = f"{TOPIC_AUDIO}/{self.name[-1]}"
        self.add_message_handler(
            self._audio_receive, self.state["topic_audio"], binary=True)

    def _audio_receive(self, aiko, topic, payload_in):
        payload_in = zlib.decompress(payload_in)
        payload_in = BytesIO(payload_in)
        if False:
            buffer = payload_in.getbuffer()
            digest = md5(buffer).hexdigest()
            print(f"payload_in: len: {len(buffer)}, md5: {digest}")
        audio_sample = np.load(payload_in, allow_pickle=True)
        frame_id = self.state["frame_id"]
        self.ec_producer.update("frame_id", frame_id + 1)
        context = {"stream_id": 0, "frame_id": frame_id}
        self.pipeline.create_frame(context, {"audio": audio_sample})

    def process_frame(self, context, audio) -> Tuple[bool, dict]:
        return True, {"audio": audio}

class PE_RemoteReceive1(PE_RemoteReceive0):
    pass

# --------------------------------------------------------------------------- #

class PE_RemoteSend0(PipelineElement):
    def __init__(self,
        implementations, name, protocol, tags, transport,
        definition, pipeline):

        protocol = "remote_send:0"
        implementations["PipelineElement"].__init__(self,
            implementations, name, protocol, tags, transport,
            definition, pipeline)

        self.state["topic_audio"] = f"{TOPIC_AUDIO}/{self.name[-1]}"

    def process_frame(self, context, audio) -> Tuple[bool, dict]:
        payload_out = BytesIO()
        np.save(payload_out, audio, allow_pickle=True)
        if False:
            buffer = payload_out.getbuffer()
            digest = md5(buffer).hexdigest()
            print(f"{self._id(context)}, len: {len(buffer)}, md5: {digest}")
        payload_out = zlib.compress(payload_out.getvalue())
        aiko.message.publish(self.state["topic_audio"], payload_out)
        return True, {}

class PE_RemoteSend1(PE_RemoteSend0):
    pass

# --------------------------------------------------------------------------- #

import time

# SP_AUDIO_SAMPLE_RATE = PA_AUDIO_SAMPLE_RATE
# SP_AUDIO_SAMPLE_RATE = SD_AUDIO_SAMPLE_RATE
SP_AUDIO_SAMPLE_RATE = 22050                   # coqui.ai text-to-speech

class PE_Speaker(PipelineElement):
    def __init__(self,
        implementations, name, protocol, tags, transport,
        definition, pipeline):

        protocol = "speaker:0"
        implementations["PipelineElement"].__init__(self,
            implementations, name, protocol, tags, transport,
            definition, pipeline)

    def process_frame(self, context, audio) -> Tuple[bool, dict]:
    #   _LOGGER.debug(f"{self._id(context)} len(audio): {len(audio)}")
        sd.play(audio, SP_AUDIO_SAMPLE_RATE)
    #   time.sleep(len(audio) / SD_AUDIO_SAMPLE_RATE)
        return True, {"audio": audio}

# --------------------------------------------------------------------------- #
