import subprocess

from therion.interface import pc_health

MB = 1024 ** 2
GB = 1024 ** 3


def test_label_shows_the_three_numbers_and_says_when_vram_is_missing():
    assert pc_health.label_text({'ram': .62, 'vram': .18, 'c_free': 2.5 * GB}) == 'RAM 62% · VRAM 18% · C 2,5 GB'
    assert pc_health.label_text({'ram': .62, 'vram': None, 'c_free': None}) == 'RAM 62% · VRAM indisponível'


def test_parse_vram_sums_every_adapter_of_a_process_and_ignores_other_names():
    rows = [('pid_100_luid_0x0_0x1_phys_0', 300 * MB), ('pid_100_luid_0x0_0x2_phys_0', 100 * MB),
            ('pid_200_luid_0x0_0x1_phys_0', 50 * MB), ('_Total', 999 * MB), ('lixo', 1)]
    assert pc_health.parse_vram(rows) == {100: 400 * MB, 200: 50 * MB}


def test_gpu_memory_reads_nvidia_smi_in_mib_and_gives_up_quietly(monkeypatch):
    def fake(stdout, code=0):
        return lambda *a, **k: subprocess.CompletedProcess(a, code, stdout=stdout, stderr='')

    monkeypatch.setattr(subprocess, 'run', fake('1447, 8192, 40\n'))
    assert pc_health.gpu_memory() == (1447 * MB, 8192 * MB, 40)
    monkeypatch.setattr(subprocess, 'run', fake('', 1))
    assert pc_health.gpu_memory() is None
    monkeypatch.setattr(subprocess, 'run', fake('[N/A], [N/A], [N/A]\n'))
    assert pc_health.gpu_memory() is None

    def missing(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(subprocess, 'run', missing)
    assert pc_health.gpu_memory() is None


def test_full_reading_names_the_top_vram_users_and_survives_without_pdh(monkeypatch):
    measure = dict(ram_total=16 * GB, ram_free=6 * GB, commit_total=30 * GB, commit_free=20 * GB, disks={'C': 5 * GB},
                   top=[('chrome.exe', 3 * GB), ('ollama.exe', GB)],
                   processes={100: ('chrome.exe', 3 * GB), 200: ('ollama.exe', GB)})
    monkeypatch.setattr(pc_health, '_measure', lambda: measure)
    monkeypatch.setattr(pc_health, 'gpu_memory', lambda: (2 * GB, 8 * GB, 41))
    monkeypatch.setattr(pc_health, 'vram_by_pid', lambda: {200: 2 * GB, 100: 400 * MB})
    reading = pc_health.full_reading()
    assert reading['top_vram'] == [('ollama', 2 * GB), ('chrome', 400 * MB)]
    assert reading['top_ram'] == [('chrome', 3 * GB), ('ollama', GB)]
    assert (reading['ram_used'], reading['commit_used'], reading['gpu_temp']) == (10 * GB, 10 * GB, 41)
    assert reading['vram'] == .25

    monkeypatch.setattr(pc_health, 'vram_by_pid', lambda: {})
    assert pc_health.full_reading()['top_vram'] == []


def test_full_reading_reads_the_gpu_once_and_groups_vram_by_program_name(monkeypatch):
    measure = dict(ram_total=16 * GB, ram_free=6 * GB, commit_total=30 * GB, commit_free=20 * GB, disks={'C': 5 * GB},
                   top=[], processes={1: ('chrome.exe', 0), 2: ('chrome.exe', 0), 3: ('ollama.exe', 0)})
    calls = []
    monkeypatch.setattr(pc_health, '_measure', lambda: measure)
    monkeypatch.setattr(pc_health, 'gpu_memory', lambda: calls.append(1) or (2 * GB, 8 * GB, 41))
    monkeypatch.setattr(pc_health, 'vram_by_pid', lambda: {1: 300 * MB, 2: 400 * MB, 3: 600 * MB})
    reading = pc_health.full_reading()
    assert len(calls) == 1
    assert reading['top_vram'] == [('chrome', 700 * MB), ('ollama', 600 * MB)]


def test_quick_reading_reports_the_total_of_disk_c_for_the_panel_bar(monkeypatch):
    usage = type('Usage', (), {'free': 4 * GB, 'total': 100 * GB})()
    monkeypatch.setattr(pc_health.shutil, 'disk_usage', lambda path: usage)
    monkeypatch.setattr(pc_health, 'gpu_memory', lambda: None)
    reading = pc_health.quick_reading()
    assert reading['c_free'] == 4 * GB and reading['c_total'] == 100 * GB
