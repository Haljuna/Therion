"""Vigia do PC: avisa sozinho, uma vez por problema, quando o disco C, a memória ou a placa de vídeo apertam.

Mesmos limites do "por que o PC está lento" (core/local_reports.pc_report). Só lê; não fecha nem apaga nada.
Volta a avisar só depois de o PC se recuperar com folga. Ligado por padrão (ui.pc_watch).
"""
import subprocess

from therion.core.local_reports import _GB, _gb, _measure

HOT, COOL = 85, 80   # °C da placa de vídeo


def gpu_temperature():
    """Temperatura da placa NVIDIA em °C, ou None sem nvidia-smi ou com leitura estranha."""
    try:
        done = subprocess.run(['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader'], capture_output=True,
                              text=True, errors='replace', timeout=5, stdin=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = (done.stdout or '').strip().split('\n')[0].strip() if done.returncode == 0 else ''
    return int(first) if first.isdigit() else None


class PcWatch:
    def __init__(self):
        self._active = set()   # problemas já avisados que ainda não passaram
        self._hot = 0

    def poll(self):
        """Mede e devolve os avisos novos; roda fora da thread da janela (o tasklist leva até 10 s)."""
        try:
            measure = _measure()
        except (OSError, AttributeError):
            return []
        return self.check(measure, gpu_temperature())

    def _flag(self, key, bad, recovered):
        """True só na primeira vez que o problema aparece."""
        if recovered:
            self._active.discard(key)
        if not bad or key in self._active:
            return False
        self._active.add(key)
        return True

    def check(self, measure, gpu_temp=None):
        messages = []
        top = measure.get('top') or []
        heavy = f' O que mais usa memória: {top[0][0].removesuffix(".exe")} ({_gb(top[0][1])}).' if top else ''
        total, free = measure['commit_total'], measure['commit_free']
        if total and self._flag('commit', free < total * .10, free >= total * .15):
            messages.append(f'Senhor, a memória virtual está quase esgotada: {_gb(free)} livres de {_gb(total)}; '
                            'é esse limite que derruba o meu modelo.' + heavy)
        total, free = measure['ram_total'], measure['ram_free']
        if total and self._flag('ram', free < total * .15, free >= total * .20):
            messages.append(f'Senhor, a memória RAM está quase cheia: {_gb(free)} livres de {_gb(total)}.' + heavy)
        free = measure['disks'].get('C')
        if free is not None:
            if self._flag('disk_critical', free < _GB, free >= 2 * _GB):
                self._active.add('disk')   # já crítico: o aviso comum seria repetido
                messages.append(f'Senhor, o disco C está crítico: só {_gb(free)} livres. Programas podem começar a falhar.')
            elif self._flag('disk', free < 5 * _GB, free >= 6 * _GB):
                messages.append(f'Senhor, o disco C está quase cheio: {_gb(free)} livres.')
        if gpu_temp is not None:
            self._hot = self._hot + 1 if gpu_temp >= HOT else 0
            if self._flag('gpu', self._hot >= 2, gpu_temp < COOL):
                messages.append(f'Senhor, a placa de vídeo está a {gpu_temp} °C há alguns minutos.')
        return messages
