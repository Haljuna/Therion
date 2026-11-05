"""Paralaxe suave da cena; nenhuma captura, ação ou dado pessoal."""
import math


class SceneMotion:
    def __init__(self):
        self.pointer=[0.,0.]
        self.target=[0.,0.]
        self.phase=0.

    def aim(self,x,y):
        self.target=[max(-1.,min(1.,float(v))) if math.isfinite(float(v)) else 0. for v in (x,y)]

    def advance(self,seconds,*,reduced=False):
        if reduced:
            self.pointer=[0.,0.]
            return
        if not math.isfinite(seconds) or seconds<=0:return
        dt=min(.1,seconds);self.phase+=dt
        blend=1.-math.exp(-dt/.45)
        self.pointer=[a+(b-a)*blend for a,b in zip(self.pointer,self.target)]
