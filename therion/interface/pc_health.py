"""Leituras de saúde do PC: RAM, VRAM (total e por processo) e disco, direto do que o Windows e o driver já medem.

Nada de abrir programas (tasklist, nvidia-smi): uma consulta aos contadores de desempenho do Windows fica aberta
e cada leitura custa ~5 ms; VRAM total e temperatura vêm do driver da NVIDIA (nvml.dll). Usado pelo painel da
mini orbe (a cada 1 s, só aberto) e pelo vigia do PC (a cada 2 min).
"""
import ctypes
import re
import shutil
import threading
from ctypes import wintypes

from therion.core.local_reports import _Memory

_PDH_FMT_LARGE = 0x400
_PDH_MORE_DATA = 0x800007D2
_VRAM_INSTANCE = re.compile(r'^pid_(\d+)_luid_')
_COUNTERS = (('pid', r'\Process(*)\ID Process'), ('ram', r'\Process(*)\Working Set - Private'),
             ('vram', r'\GPU Process Memory(*)\Dedicated Usage'))
_lock = threading.Lock()   # painel e vigia leem de threads diferentes
_shared = None
_gpu_lock = threading.Lock()
_nvml = None               # (dll, placa) depois de iniciar; False sem driver NVIDIA


class _Item(ctypes.Structure):   # PDH_FMT_COUNTERVALUE_ITEM_W com valor LARGE
    _fields_ = [('name', wintypes.LPWSTR), ('status', wintypes.DWORD), ('value', ctypes.c_longlong)]


def _rows(pdh, counter):
    """[(instância, valor ou None)] na ordem do Windows; o mesmo programa repete o nome (chrome, chrome…)."""
    size, count = wintypes.DWORD(0), wintypes.DWORD(0)
    status = pdh.PdhGetFormattedCounterArrayW(counter, _PDH_FMT_LARGE, ctypes.byref(size), ctypes.byref(count), None)
    if (status & 0xFFFFFFFF) != _PDH_MORE_DATA:
        return []
    buffer = ctypes.create_string_buffer(size.value)
    if pdh.PdhGetFormattedCounterArrayW(counter, _PDH_FMT_LARGE, ctypes.byref(size), ctypes.byref(count), buffer):
        return []
    items = ctypes.cast(buffer, ctypes.POINTER(_Item))
    return [(items[i].name, items[i].value if items[i].status == 0 else None) for i in range(count.value)]


class _Counters:
    """Consulta PDH aberta uma vez e reaproveitada; processos novos entram sozinhos a cada coleta."""
    def __init__(self):
        self._pdh, self._query, self._counters = ctypes.windll.pdh, wintypes.HANDLE(), {}
        if self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)):
            raise OSError('PdhOpenQueryW falhou.')
        for key, path in _COUNTERS:
            counter = wintypes.HANDLE()
            if self._pdh.PdhAddEnglishCounterW(self._query, path, 0, ctypes.byref(counter)):
                self._pdh.PdhCloseQuery(self._query)
                raise OSError(f'Contador indisponível: {path}')
            self._counters[key] = counter

    def read(self):
        if self._pdh.PdhCollectQueryData(self._query):
            raise OSError('PdhCollectQueryData falhou.')
        return {key: _rows(self._pdh, counter) for key, counter in self._counters.items()}


def _read_counters():
    """{'pid': rows, 'ram': rows, 'vram': rows}, ou {} se os contadores do Windows falharem (reabre na próxima)."""
    global _shared
    with _lock:
        try:
            if _shared is None:
                _shared = _Counters()
            return _shared.read()
        except (OSError, AttributeError, ValueError):
            _shared = None
            return {}


def processes_from(pid_rows, ram_rows):
    """{pid: (nome, RAM privada)} juntando os dois contadores pela posição (mesma coleta, mesma ordem)."""
    processes = {}
    for (name, pid), (other, used) in zip(pid_rows, ram_rows):
        if name != other or name in ('_Total', 'Idle') or not pid or used is None:
            continue
        processes[int(pid)] = (name, int(used))
    return processes


def parse_vram(rows):
    """Soma por PID as instâncias 'pid_<n>_luid_…_phys_<k>' (uma por placa); ignora outros nomes."""
    usage = {}
    for name, value in rows:
        found = _VRAM_INSTANCE.match(name or '')
        if found and value is not None:
            usage[int(found.group(1))] = usage.get(int(found.group(1)), 0) + int(value)
    return usage


def measure_live():
    """Mesmo formato de local_reports._measure() (o vigia usa), mais 'vram' {pid: bytes}, sem tasklist."""
    stat = _Memory()
    stat.dwLength = ctypes.sizeof(stat)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        raise OSError('GlobalMemoryStatusEx falhou.')
    disks = {}
    for letter in ('C', 'F'):
        try:
            disks[letter] = shutil.disk_usage(letter + ':\\').free
        except OSError:
            pass
    rows = _read_counters()
    processes = processes_from(rows.get('pid', []), rows.get('ram', []))
    usage = {}
    for name, used in processes.values():
        usage[name] = usage.get(name, 0) + used
    return dict(ram_total=stat.ullTotalPhys, ram_free=stat.ullAvailPhys, commit_total=stat.ullTotalPageFile,
                commit_free=stat.ullAvailPageFile, disks=disks, top=sorted(usage.items(), key=lambda row: -row[1])[:3],
                processes=processes, vram=parse_vram(rows.get('vram', [])))


class _GpuMemory(ctypes.Structure):   # nvmlMemory_t
    _fields_ = [('total', ctypes.c_ulonglong), ('free', ctypes.c_ulonglong), ('used', ctypes.c_ulonglong)]


def gpu_memory():
    """(VRAM usada, VRAM total, °C) da placa NVIDIA pelo driver (nvml.dll), ou None sem placa ou com erro."""
    global _nvml
    with _gpu_lock:
        if _nvml is None:
            _nvml = False
            try:
                dll, card = ctypes.WinDLL('nvml.dll'), ctypes.c_void_p()
                if dll.nvmlInit_v2() == 0 and dll.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(card)) == 0:
                    _nvml = (dll, card)
            except (OSError, AttributeError):
                pass
        if not _nvml:
            return None
        dll, card = _nvml
        memory, temp = _GpuMemory(), ctypes.c_uint()
        try:
            if dll.nvmlDeviceGetMemoryInfo(card, ctypes.byref(memory)) or dll.nvmlDeviceGetTemperature(card, 0, ctypes.byref(temp)):
                return None
        except (OSError, AttributeError):
            return None
        return (memory.used, memory.total, temp.value) if memory.total else None


def full_reading():
    """Leitura do painel: totais, temperatura e os maiores consumidores de RAM e VRAM (somados por programa)."""
    gpu = gpu_memory()
    measure = measure_live()
    processes = measure['processes']
    by_name = {}
    for pid, used in measure['vram'].items():
        if pid in processes:
            by_name[processes[pid][0]] = by_name.get(processes[pid][0], 0) + used
    try:
        disk = shutil.disk_usage('C:\\')
        c_free, c_total = disk.free, disk.total
    except OSError:
        c_free = c_total = None
    ram_used = measure['ram_total'] - measure['ram_free']
    return dict(ram=ram_used / measure['ram_total'] if measure['ram_total'] else None,
                vram=gpu[0] / gpu[1] if gpu else None, c_free=c_free, c_total=c_total,
                ram_used=ram_used, ram_total=measure['ram_total'],
                commit_used=measure['commit_total'] - measure['commit_free'], commit_total=measure['commit_total'],
                vram_used=gpu[0] if gpu else None, vram_total=gpu[1] if gpu else None, gpu_temp=gpu[2] if gpu else None,
                top_ram=measure['top'], top_vram=sorted(by_name.items(), key=lambda row: -row[1])[:3])
