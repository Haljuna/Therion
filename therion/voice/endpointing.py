"""Detecção leve de fim de frase, com silêncio e duração limitados."""
import numpy as np


class SpeechEndpoint:
    def __init__(self, sample_rate=16000, silence_seconds=0.7, max_seconds=90, activity=None):
        self.sample_rate = sample_rate
        self.silence_seconds = silence_seconds
        self.max_seconds = max_seconds
        self.elapsed = 0.0
        self.last_voice = 0.0
        self.speech_seconds = 0.0
        self.noise = 0.001
        self.complete = False
        self.reason = None
        self.first_voice = None
        self.activity = activity

    def feed(self, samples):
        if self.complete:
            return
        duration = len(samples) / self.sample_rate
        self.elapsed += duration
        rms = float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0
        threshold = max(0.004, min(0.025, self.noise * 3.0))
        try:
            voiced = bool(self.activity(samples)) if self.activity is not None else rms > threshold
        except Exception:
            self.complete, self.reason = True, 'detector_error'
            return
        if voiced:
            if self.first_voice is None:
                self.first_voice = self.elapsed-duration
            self.last_voice = self.elapsed
            self.speech_seconds += duration
        elif not self.speech_seconds:
            self.noise = 0.97 * self.noise + 0.03 * rms
        if self.speech_seconds >= 0.2 and self.elapsed - self.last_voice >= self.silence_seconds:
            self.complete, self.reason = True, 'silence'
        elif self.first_voice is not None and self.elapsed-self.first_voice >= self.max_seconds:
            self.complete, self.reason = True, 'limit'
        elif self.first_voice is None and self.elapsed >= 20:
            self.complete, self.reason = True, 'idle'
