"""Saúde do PC pelos contadores do Windows e pelo driver da NVIDIA, sem abrir tasklist nem nvidia-smi."""
import pytest

from therion.interface import pc_health

MB = 1024 ** 2
GB = 1024 ** 3


@pytest.fixture(autouse=True)
def no_real_counters(monkeypatch):
    """Nenhum teste lê os contadores nem o driver de verdade; quem precisa troca estes falsos."""
    monkeypatch.setattr(pc_health, '_read_counters', lambda: {})
    monkeypatch.setattr(pc_health, '_nvml', False)


def test_parse_vram_sums_every_adapter_of_a_process_and_ignores_other_names():
    rows = [('pid_100_luid_0x0_0x1_phys_0', 300 * MB), ('pid_100_luid_0x0_0x2_phys_0', 100 * MB),
            ('pid_200_luid_0x0_0x1_phys_0', 50 * MB), ('pid_300_luid_0x0_0x1_phys_0', None), ('_Total', 999 * MB), ('lixo', 1)]
    assert pc_health.parse_vram(rows) == {100: 400 * MB, 200: 50 * MB}


def test_processes_pair_both_counters_by_position_and_skip_totals():
    pids = [('chrome', 10), ('chrome', 11), ('_Total', 0), ('Idle', 0), ('svchost', 12), ('morto', 13)]
    ram = [('chrome', 3 * GB), ('chrome', GB), ('_Total', 9 * GB), ('Idle', 0), ('outro', MB), ('morto', None)]
    assert pc_health.processes_from(pids, ram) == {10: ('chrome', 3 * GB), 11: ('chrome', GB)}


def test_measure_live_groups_ram_by_program_and_keeps_every_pid(monkeypatch):
    rows = {'pid': [('chrome', 10), ('chrome', 11), ('ollama', 20), ('discord', 30)],
            'ram': [('chrome', 2 * GB), ('chrome', GB), ('ollama', 2.5 * GB), ('discord', 500 * MB)],
            'vram': [('pid_20_luid_0x0_0x1_phys_0', 3 * GB)]}
    monkeypatch.setattr(pc_health, '_read_counters', lambda: rows)
    measure = pc_health.measure_live()
    assert measure['top'] == [('chrome', 3 * GB), ('ollama', 2.5 * GB), ('discord', 500 * MB)]
    assert measure['processes'][11] == ('chrome', GB) and measure['vram'] == {20: 3 * GB}
    assert measure['ram_total'] > 0 and 'C' in measure['disks']


def test_measure_live_still_answers_when_the_windows_counters_fail():
    measure = pc_health.measure_live()   # _read_counters → {} (fixture)
    assert measure['processes'] == {} and measure['top'] == [] and measure['vram'] == {}
    assert measure['ram_total'] > 0


class FakeNvml:
    def __init__(self, init=0, memory=0):
        self.init, self.memory = init, memory

    def nvmlInit_v2(self):
        return self.init

    def nvmlDeviceGetHandleByIndex_v2(self, index, card):
        return 0

    def nvmlDeviceGetMemoryInfo(self, card, memory):
        memory._obj.used, memory._obj.total = 1447 * MB, 8192 * MB
        return self.memory

    def nvmlDeviceGetTemperature(self, card, sensor, temp):
        temp._obj.value = 40
        return 0


def test_gpu_memory_comes_from_the_driver_and_gives_up_quietly(monkeypatch):
    monkeypatch.setattr(pc_health, '_nvml', None)
    monkeypatch.setattr(pc_health.ctypes, 'WinDLL', lambda name: FakeNvml())
    assert pc_health.gpu_memory() == (1447 * MB, 8192 * MB, 40)
    monkeypatch.setattr(pc_health, '_nvml', None)
    monkeypatch.setattr(pc_health.ctypes, 'WinDLL', lambda name: FakeNvml(init=1))   # driver não inicia
    assert pc_health.gpu_memory() is None and pc_health._nvml is False
    monkeypatch.setattr(pc_health, '_nvml', (FakeNvml(memory=1), None))          # leitura falha
    assert pc_health.gpu_memory() is None

    def missing(name):
        raise OSError('sem nvml.dll')
    monkeypatch.setattr(pc_health, '_nvml', None)
    monkeypatch.setattr(pc_health.ctypes, 'WinDLL', missing)
    assert pc_health.gpu_memory() is None


def test_full_reading_reads_the_gpu_once_and_groups_vram_by_program_name(monkeypatch):
    measure = dict(ram_total=16 * GB, ram_free=6 * GB, commit_total=30 * GB, commit_free=20 * GB, disks={'C': 5 * GB},
                   top=[('chrome', 3 * GB), ('ollama', GB)],
                   processes={1: ('chrome', 0), 2: ('chrome', 0), 3: ('ollama', 0)},
                   vram={1: 300 * MB, 2: 400 * MB, 3: 600 * MB, 99: GB})
    calls = []
    monkeypatch.setattr(pc_health, 'measure_live', lambda: measure)
    monkeypatch.setattr(pc_health, 'gpu_memory', lambda: calls.append(1) or (2 * GB, 8 * GB, 41))
    usage = type('Usage', (), {'free': 4 * GB, 'total': 100 * GB})()
    monkeypatch.setattr(pc_health.shutil, 'disk_usage', lambda path: usage)
    reading = pc_health.full_reading()
    assert len(calls) == 1
    assert reading['top_vram'] == [('chrome', 700 * MB), ('ollama', 600 * MB)]   # PID 99 sem nome fica de fora
    assert reading['top_ram'] == [('chrome', 3 * GB), ('ollama', GB)]
    assert (reading['ram_used'], reading['commit_used'], reading['gpu_temp']) == (10 * GB, 10 * GB, 41)
    assert reading['vram'] == .25 and reading['ram'] == 10 / 16
    assert reading['c_free'] == 4 * GB and reading['c_total'] == 100 * GB


def test_full_reading_without_nvidia_says_unavailable_and_keeps_the_rest(monkeypatch):
    reading = pc_health.full_reading()   # sem driver (fixture) e sem contadores
    assert reading['vram'] is None and reading['vram_used'] is None and reading['gpu_temp'] is None
    assert reading['top_vram'] == [] and reading['ram_total'] > 0
