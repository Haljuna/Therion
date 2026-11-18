"""Leituras de saúde do PC para a mini orbe: RAM, VRAM (total e por processo) e disco C."""
import ctypes
import re
import shutil
import subprocess
from ctypes import wintypes

from therion.core.local_reports import _Memory, _gb, _measure

_PDH_FMT_LARGE = 0x400
_PDH_MORE_DATA = 0x800007D2
_VRAM_INSTANCE = re.compile(r'^pid_(\d+)_luid_')


def gpu_memory():
    """(VRAM usada, VRAM total, °C) da placa NVIDIA, ou None sem nvidia-smi ou com leitura estranha."""
    try:
        done = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,memory.total,temperature.gpu',
                               '--format=csv,noheader,nounits'], capture_output=True, text=True, errors='replace',
                              timeout=5, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    parts = [part.strip() for part in (done.stdout or '').strip().split('\n')[0].split(',')]
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    used, total, temp = (int(part) for part in parts)
    return used * 1024 ** 2, total * 1024 ** 2, temp


def parse_vram(rows):
    """Soma por PID as instâncias 'pid_<n>_luid_…_phys_<k>' (uma por placa); ignora outros nomes."""
    usage = {}
    for name, value in rows:
        found = _VRAM_INSTANCE.match(name)
        if found:
            usage[int(found.group(1))] = usage.get(int(found.group(1)), 0) + int(value)
    return usage


class _Item(ctypes.Structure):   # PDH_FMT_COUNTERVALUE_ITEM_W com valor LARGE
    _fields_ = [('name', wintypes.LPWSTR), ('status', wintypes.DWORD), ('value', ctypes.c_longlong)]


def vram_by_pid():
    """VRAM dedicada por PID via contador de desempenho do Windows; {} em qualquer falha."""
    pdh = ctypes.windll.pdh
    query = wintypes.HANDLE()
    try:
        if pdh.PdhOpenQueryW(None, 0, ctypes.byref(query)):
            return {}
        counter = wintypes.HANDLE()
        if pdh.PdhAddEnglishCounterW(query, r'\GPU Process Memory(*)\Dedicated Usage', 0, ctypes.byref(counter)):
            return {}
        if pdh.PdhCollectQueryData(query):
            return {}
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        status = pdh.PdhGetFormattedCounterArrayW(counter, _PDH_FMT_LARGE, ctypes.byref(size), ctypes.byref(count), None)
        if (status & 0xFFFFFFFF) != _PDH_MORE_DATA:
            return {}
        buffer = ctypes.create_string_buffer(size.value)
        if pdh.PdhGetFormattedCounterArrayW(counter, _PDH_FMT_LARGE, ctypes.byref(size), ctypes.byref(count), buffer):
            return {}
        items = ctypes.cast(buffer, ctypes.POINTER(_Item))
        return parse_vram([(items[i].name, items[i].value) for i in range(count.value) if items[i].status == 0])
    except (OSError, AttributeError, ValueError):
        return {}
    finally:
        if query.value:
            pdh.PdhCloseQuery(query)


def quick_reading(gpu=...):
    """Leitura barata (sem tasklist) para a etiqueta ao passar o mouse; `gpu` evita ler a placa de novo."""
    if gpu is ...:
        gpu = gpu_memory()
    stat = _Memory()
    stat.dwLength = ctypes.sizeof(stat)
    ram = None
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)) and stat.ullTotalPhys:
        ram = 1 - stat.ullAvailPhys / stat.ullTotalPhys
    try:
        disk = shutil.disk_usage('C:\\')
        c_free, c_total = disk.free, disk.total
    except OSError:
        c_free = c_total = None
    return {'ram': ram, 'vram': gpu[0] / gpu[1] if gpu else None, 'c_free': c_free, 'c_total': c_total}


def _name(exe):
    return exe[:-4] if exe.lower().endswith('.exe') else exe


def full_reading():
    """Leitura completa para o painel: totais, temperatura e os maiores consumidores de RAM e VRAM."""
    gpu = gpu_memory()
    reading = quick_reading(gpu)
    measure = _measure()
    processes = measure['processes']
    by_name = {}   # como a RAM: o mesmo programa em vários processos soma numa linha só
    for pid, used in vram_by_pid().items():
        if pid in processes:
            name = _name(processes[pid][0])
            by_name[name] = by_name.get(name, 0) + used
    vram = sorted(by_name.items(), key=lambda row: -row[1])
    reading.update(
        ram_used=measure['ram_total'] - measure['ram_free'], ram_total=measure['ram_total'],
        commit_used=measure['commit_total'] - measure['commit_free'], commit_total=measure['commit_total'],
        vram_used=gpu[0] if gpu else None, vram_total=gpu[1] if gpu else None, gpu_temp=gpu[2] if gpu else None,
        top_ram=[(_name(name), used) for name, used in measure['top']],
        top_vram=vram[:3])
    return reading


def label_text(reading):
    parts = [f"RAM {round(reading['ram'] * 100)}%"]
    parts.append(f"VRAM {round(reading['vram'] * 100)}%" if reading['vram'] is not None else 'VRAM indisponível')
    if reading['c_free'] is not None:
        parts.append(f"C {_gb(reading['c_free'])}")
    return ' · '.join(parts)
