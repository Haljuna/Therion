"""Vigia do PC: avisa sozinho, uma vez por problema, quando o disco C, a memória ou a placa de vídeo apertam.

Mesmos limites do "por que o PC está lento" (core/local_reports.pc_report). Volta a avisar só depois de o PC
se recuperar com folga. No aviso de disco diz o que cresceu desde a foto do dia e oferece a limpeza segura
(core/pc_cleanup), que só roda com o "sim" do usuário. Também prevê o disco enchendo, guarda o pior momento
do jogo para um resumo na saída e acompanha cada processo para pegar vazamento. Ligado por padrão (ui.pc_watch).
"""
import json
import os
import subprocess
import time
from collections import deque
from datetime import datetime, timedelta

from therion.core import pc_cleanup
from therion.core.local_reports import _GB, _gb
from therion.interface import pc_health

HOT, COOL = 85, 80        # °C da placa de vídeo
HOUR = 3600
LEAK_GROWTH = _GB          # cresceu isso em ~1 h subindo quase sempre: vazamento
_DISK_KEYS = {'disk', 'disk_critical', 'forecast'}


def _measure():
    """Memória, discos e processos pelos contadores do Windows (~5 ms; o tasklist levava ~400 ms)."""
    return pc_health.measure_live()


def gpu_temperature():
    """Temperatura da placa NVIDIA em °C pelo driver, ou None sem placa."""
    gpu = pc_health.gpu_memory()
    return gpu[2] if gpu else None


def service_of(pid):
    """Serviço dentro de um svchost (ex.: StorSvc), ou None."""
    try:
        done = subprocess.run(['tasklist', '/svc', '/fi', f'PID eq {int(pid)}', '/fo', 'csv', '/nh'], capture_output=True,
                              text=True, errors='replace', timeout=10, stdin=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    parts = [part.strip('"') for part in (done.stdout or '').strip().split('","')]
    services = parts[2].strip('"') if len(parts) >= 3 and parts[2] not in ('', 'N/A', 'N/D') else None
    return ', '.join(services.split(',')[:2]) if services else None   # um svchost pode ter dez serviços


def folder_sizes():
    """Pastas de sempre do C, mais pagefile e hiberfil; lento (anda nas pastas), só numa thread."""
    sizes = {}
    for name, folder, _ in pc_cleanup.targets():
        sizes[name] = sizes.get(name, 0) + pc_cleanup.size(folder)
    for name, folder in (('Downloads', os.path.join(os.environ.get('USERPROFILE', ''), 'Downloads')),
                         ('Lixeira', 'C:\\$Recycle.Bin'), ('Atualizações do Windows', r'C:\Windows\SoftwareDistribution\Download')):
        if os.path.isabs(folder):
            sizes[name] = pc_cleanup.size(folder)
    try:
        with os.scandir('C:\\') as entries:   # o scandir lê o tamanho sem abrir o arquivo travado
            for entry in entries:
                if entry.name.lower() in ('pagefile.sys', 'hiberfil.sys', 'swapfile.sys'):
                    key = 'Hibernação' if entry.name.lower() == 'hiberfil.sys' else 'Memória virtual'
                    sizes[key] = sizes.get(key, 0) + entry.stat().st_size
    except OSError:
        pass
    return sizes


def _since(taken, now):
    day = 'hoje' if taken.date() == now.date() else 'ontem' if taken.date() == now.date() - timedelta(days=1) else taken.strftime('%d/%m')
    return f'desde {day} às {taken:%H:%M}'


def explain(photo, free_now, sizes_now, now):
    """Frase com a causa da queda do C comparada à foto do dia, ou '' sem foto ou sem queda."""
    if not photo:
        return ''
    try:
        taken, lost = datetime.fromisoformat(photo['time']), photo['free'] - free_now
    except (KeyError, TypeError, ValueError):
        return ''
    if lost < _GB // 2:
        return ''
    grew = sorted(((name, sizes_now.get(name, 0) - before) for name, before in (photo.get('sizes') or {}).items()),
                  key=lambda row: -row[1])
    grew = [row for row in grew if row[1] >= 300 * 1024 ** 2][:2]
    start = f' O C perdeu {_gb(lost)} {_since(taken, now)}'
    if grew and grew[0][0] == 'Memória virtual':
        return start + f': foi a memória virtual, não arquivo; o pagefile cresceu {_gb(grew[0][1])}. Fechar programas pesados devolve espaço.'
    if grew:
        return start + '; quem cresceu: ' + ', '.join(f'{name} (+{_gb(value)})' for name, value in grew) + '.'
    return start + '; não foi nas pastas de sempre, pode ser atualização ou programa novo.'


class PcWatch:
    def __init__(self, photo_path=None, service=service_of, clock=time.monotonic):
        self._active = set()   # problemas já avisados que ainda não passaram
        self._hot = 0
        self._disk = deque()   # (instante, livres no C) da última hora
        self._procs = {}       # pid -> deque((instante, bytes))
        self._service, self._clock = service, clock
        self._photo_path = photo_path or os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Therion', 'pc_watch.json')
        self.fired = []
        self.in_game = False
        self._worst = {}

    def tight(self):
        """True se há problema do PC em aberto; vazamento já avisado não deixa a mini orbe âmbar."""
        return any(not key.startswith('leak:') for key in tuple(self._active))   # o vigia muda o conjunto numa thread

    # --- jogo -------------------------------------------------------------------------------------------------
    def game(self, on):
        """Entrar zera o pior momento; sair devolve o resumo da partida, ou None se nada apertou."""
        if on:
            self.in_game, self._worst = True, {}
            return None
        self.in_game, worst, self._worst = False, self._worst, {}
        parts = []
        if worst.get('gpu', 0) >= HOT:
            parts.append(f'a placa chegou a {worst["gpu"]} °C')
        if worst.get('ram', 1) < .15:
            parts.append('a RAM ficou quase cheia')
        if worst.get('commit', 1) < .10:
            parts.append('a memória virtual quase acabou')
        if 'c' in worst and worst['c'] < 5 * _GB:
            parts.append(f'o disco C desceu a {_gb(worst["c"])}')
        if not parts:
            return None
        return 'Senhor, na partida ' + (', '.join(parts[:-1]) + ' e ' + parts[-1] if len(parts) > 1 else parts[0]) + '.'

    def _keep_worst(self, measure, gpu_temp):
        worst = self._worst
        if gpu_temp is not None:
            worst['gpu'] = max(worst.get('gpu', 0), gpu_temp)
        for key, free, total in (('ram', measure['ram_free'], measure['ram_total']), ('commit', measure['commit_free'], measure['commit_total'])):
            if total:
                worst[key] = min(worst.get(key, 1), free / total)
        if measure['disks'].get('C') is not None:
            worst['c'] = min(worst.get('c', measure['disks']['C']), measure['disks']['C'])

    # --- medição na thread ------------------------------------------------------------------------------------
    def poll(self, now=None):
        """[(frase, oferece limpeza)] novos; roda fora da thread da janela (tasklist e pastas levam segundos)."""
        try:
            measure = _measure()
        except (OSError, AttributeError):
            return []
        messages = self.check(measure, gpu_temperature())
        free = measure['disks'].get('C')
        now = now or datetime.now()
        photo = self._read_photo()
        if free is None:
            return [(text, False) for text in messages]
        # Cada chave em `fired` gerou uma frase, na mesma ordem.
        disk = next((i for i, key in enumerate(self.fired) if key in _DISK_KEYS), None)
        new_day = not photo or photo.get('day') != now.date().isoformat()
        sizes = folder_sizes() if disk is not None or new_day else None
        result = []
        for i, text in enumerate(messages):
            if i == disk:
                text += explain(photo, free, sizes, now)
                spare = pc_cleanup.estimate()
                if spare >= 200 * 1024 ** 2:
                    result.append((text + f' Quer que eu limpe os temporários seguros? Dá uns {_gb(spare)}.', True))
                    continue
            result.append((text, False))
        if new_day:
            self._write_photo(dict(day=now.date().isoformat(), time=now.isoformat(timespec='minutes'), free=free, sizes=sizes))
        return result

    def _read_photo(self):
        try:
            with open(self._photo_path, encoding='utf-8') as file:
                photo = json.load(file)
            return photo if isinstance(photo, dict) else None
        except (OSError, ValueError):
            return None

    def _write_photo(self, photo):
        try:
            os.makedirs(os.path.dirname(self._photo_path), exist_ok=True)
            temporary = self._photo_path + '.tmp'
            with open(temporary, 'w', encoding='utf-8') as file:
                json.dump(photo, file)
            os.replace(temporary, self._photo_path)
        except OSError:
            pass   # sem a foto, o próximo aviso só não diz a causa

    # --- regras -----------------------------------------------------------------------------------------------
    def _flag(self, key, bad, recovered):
        """True só na primeira vez que o problema aparece."""
        if recovered:
            self._active.discard(key)
        if not bad or key in self._active:
            return False
        self._active.add(key)
        self.fired.append(key)
        return True

    def check(self, measure, gpu_temp=None):
        messages, self.fired = [], []
        now = self._clock()
        if self.in_game:
            self._keep_worst(measure, gpu_temp)
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
            messages += self._check_disk(free, now)
        if gpu_temp is not None:
            self._hot = self._hot + 1 if gpu_temp >= HOT else 0
            if self._flag('gpu', self._hot >= 2, gpu_temp < COOL):
                messages.append(f'Senhor, a placa de vídeo está a {gpu_temp} °C há alguns minutos.')
        messages += self._check_leaks(measure.get('processes') or {}, now)
        return messages

    def _check_disk(self, free, now):
        self._disk.append((now, free))
        while self._disk and now - self._disk[0][0] > HOUR:
            self._disk.popleft()
        if self._flag('disk_critical', free < _GB, free >= 2 * _GB):
            self._active.add('disk')   # já crítico: o aviso comum seria repetido
            return [f'Senhor, o disco C está crítico: só {_gb(free)} livres. Programas podem começar a falhar.']
        if self._flag('disk', free < 5 * _GB, free >= 6 * _GB):
            return [f'Senhor, o disco C está quase cheio: {_gb(free)} livres.']
        # Previsão: caiu ≥ 1 GB na última hora e, no ritmo da última meia hora, chega a 1 GB em menos de 1 h.
        recent = [row for row in self._disk if now - row[0] <= HOUR / 2]
        span = now - recent[0][0]
        rate = (recent[0][1] - free) / span if span >= 20 * 60 else 0.
        dropped = self._disk[0][1] - free >= _GB
        minutes = (free - _GB) / rate / 60 if rate > 0 and free > _GB else None
        if self._flag('forecast', dropped and minutes is not None and minutes < 60 and 'disk_critical' not in self._active,
                      rate <= 0):   # volta a valer quando o C para de cair
            return [f'Senhor, o disco C está caindo rápido: no ritmo da última meia hora, chega a 1 GB em uns '
                    f'{max(5, round(minutes / 5) * 5)} minutos ({_gb(free)} livres agora).']
        return []

    def _check_leaks(self, processes, now):
        messages = []
        for pid in set(self._procs) - set(processes):
            del self._procs[pid]   # processo fechado
        for pid, (name, used) in processes.items():
            history = self._procs.setdefault(pid, deque())
            history.append((now, used))
            while history and now - history[0][0] > HOUR:
                history.popleft()
            values = [value for _, value in history]
            span = now - history[0][0]
            ups = sum(1 for before, after in zip(values, values[1:]) if after > before)
            steady = len(values) >= 10 and ups >= .7 * (len(values) - 1)   # um salto só (modelo carregando) não conta
            never_let_go = all(value >= .9 * max(values[:i + 1]) for i, value in enumerate(values))
            leaking = span >= 50 * 60 and values[-1] - values[0] >= LEAK_GROWTH and steady and never_let_go
            if self._flag(f'leak:{pid}', leaking, False):
                label = name.removesuffix('.exe')
                if label.lower() == 'svchost':
                    service = self._service(pid)
                    label += f' ({service})' if service else ''
                messages.append(f'Senhor, o {label} foi de {_gb(values[0])} para {_gb(values[-1])} em 1 hora e não para de crescer; '
                                'parece vazamento. Reiniciar o programa, ou o PC, resolve.')
        return messages
