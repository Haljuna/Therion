"""Estado comum de escuta, inferência e playback; baseline sem full-duplex."""
import threading
import time


class VoiceCycle:
    def __init__(self,clock=time.monotonic):
        self.clock=clock
        self.lock=threading.Lock()
        self.processing=False
        self.playing=False
        self.rearm_after=0.0

    def runtime(self,processing):
        with self.lock:self.processing=bool(processing)

    def playback(self,active):
        with self.lock:
            was_active=self.playing
            self.playing=bool(active)
            if was_active and not self.playing:self.rearm_after=self.clock()+.6

    def state(self,capture_state):
        with self.lock:
            if capture_state in {'starting','recording','finishing'}:return 'capturing'
            if capture_state=='transcribing':return 'transcribing'
            if self.processing:return 'processing'
            if self.playing:return 'speaking'
            if self.clock()<self.rearm_after:return 'rearming'
            return 'idle'

    @property
    def can_capture(self):
        with self.lock:return not self.processing and not self.playing and self.clock()>=self.rearm_after
