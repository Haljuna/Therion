"""Estado transitório e mensurável da preparação, sem texto ou áudio do usuário."""
from dataclasses import dataclass
import time


@dataclass
class PreparationStage:
    state: str
    started: float
    timeout: float
    seconds: float = 0.0


class VoicePreparation:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.active = False
        self.stages = {}

    def begin(self, states, limits):
        now = self.clock()
        self.active = True
        self.stages = {name: PreparationStage(state, now, limits[name])
                       for name, state in states.items()}

    def finish(self, name, state='ready'):
        if not self.active or name not in self.stages:
            return
        stage = self.stages[name]
        if stage.state != 'preparing':
            return
        stage.state = state
        stage.seconds = max(0.0, self.clock() - stage.started)

    def expired(self):
        if not self.active:
            return None
        for name, stage in self.stages.items():
            if stage.state == 'preparing' and self.clock() - stage.started >= stage.timeout:
                self.finish(name, 'timeout')
                return name
        return None

    def stop(self):
        for name in self.stages:
            self.finish(name, 'stopped')
        self.active = False

    def snapshot(self):
        now = self.clock()
        return {name: {'state': stage.state, 'seconds': round(
            max(0.0, now - stage.started) if stage.state == 'preparing' else stage.seconds, 1)}
                for name, stage in self.stages.items()}

    @property
    def ready(self):
        return self.active and bool(self.stages) and all(
            stage.state == 'ready' for stage in self.stages.values())
