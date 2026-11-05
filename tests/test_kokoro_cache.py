"""Cache é opcional: sua falha não pode tornar a voz indisponível."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from therion.voice.kokoro_worker import create_engine


@pytest.mark.parametrize('failure', ['save', 'corrupt'])
def test_cache_failure_still_loads_original(tmp_path, monkeypatch, failure):
    source = tmp_path / 'kokoro-v1.0.onnx'
    source.write_bytes(b'model')
    cache_directory = tmp_path / 'runtime-cache'
    cache_directory.mkdir()
    stat = source.stat()
    cache = cache_directory / f'kokoro-cpu-test-{stat.st_size}-{stat.st_mtime_ns}.onnx'
    if failure == 'corrupt':
        cache.write_bytes(b'corrupt')
    successful_sources = []

    def load(path, sess_options, providers):
        if path == str(cache):
            raise RuntimeError('Invalid graph')
        if failure == 'save' and getattr(sess_options, 'optimized_model_filepath', ''):
            raise RuntimeError('Cannot write optimized graph')
        successful_sources.append(path)
        return SimpleNamespace(get_inputs=lambda: [])

    ort = SimpleNamespace(
        __version__='test', SessionOptions=lambda: SimpleNamespace(add_session_config_entry=Mock()),
        GraphOptimizationLevel=SimpleNamespace(ORT_DISABLE_ALL=0, ORT_ENABLE_ALL=1),
        InferenceSession=load,
    )
    monkeypatch.setitem(sys.modules, 'onnxruntime', ort)
    monkeypatch.setitem(sys.modules, 'numpy', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'kokoro_onnx', SimpleNamespace(
        Kokoro=SimpleNamespace(from_session=lambda *args: SimpleNamespace())))
    timings = {}
    engine = create_engine(tmp_path, timings, cache_directory=cache_directory)
    assert engine.sess.get_inputs() == []
    assert successful_sources == [str(source)]
    assert timings['cache_hit'] is False
    assert source.read_bytes() == b'model'
    assert not list(cache_directory.glob('preparing-*'))


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    source = tmp_path / 'kokoro-v1.0.onnx'
    source.write_bytes(b'original-model')
    cache = tmp_path / 'temporary-cache'
    calls = []

    def load(path, sess_options, providers):
        from pathlib import Path
        path = Path(path)
        calls.append((path, sess_options))
        if path.suffix == '.ort' and path.read_bytes() != b'valid-ort':
            raise ValueError('Cache interrompido')
        output = getattr(sess_options, 'optimized_model_filepath', '')
        if output:
            Path(output).write_bytes(b'valid-ort')
        return SimpleNamespace(get_inputs=lambda: [])

    ort = SimpleNamespace(
        __version__='test', SessionOptions=lambda: SimpleNamespace(add_session_config_entry=Mock()),
        GraphOptimizationLevel=SimpleNamespace(ORT_DISABLE_ALL=0, ORT_ENABLE_ALL=1),
        InferenceSession=load,
    )
    monkeypatch.setitem(sys.modules, 'onnxruntime', ort)
    monkeypatch.setitem(sys.modules, 'numpy', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'kokoro_onnx', SimpleNamespace(
        Kokoro=SimpleNamespace(from_session=lambda *args: SimpleNamespace())))
    return source, cache, calls, ort


def test_prepared_ort_is_published_and_reused_without_reopening_onnx(runtime):
    source, cache, calls, _ = runtime
    first, second = {}, {}
    create_engine(source.parent, first, cache_directory=cache)
    prepared, = cache.glob('*.ort')
    create_engine(source.parent, second, cache_directory=cache)
    assert [item[0] for item in calls] == [source, prepared]
    assert second['cache_format'] == 'ort' and second['cache_hit']
    assert calls[1][1].graph_optimization_level == 0
    calls[0][1].add_session_config_entry.assert_called_once_with('session.save_model_format', 'ORT')
    assert source.read_bytes() == b'original-model'
    assert not list(cache.glob('preparing-*'))


def test_corrupt_ort_is_rebuilt_from_original(runtime):
    source, cache, calls, _ = runtime
    create_engine(source.parent, cache_directory=cache)
    prepared, = cache.glob('*.ort')
    prepared.write_bytes(b'interrupted')
    timings = {}
    create_engine(source.parent, timings, cache_directory=cache)
    assert [item[0] for item in calls] == [source, prepared, source]
    assert prepared.read_bytes() == b'valid-ort'
    assert not timings['cache_hit']
    assert source.read_bytes() == b'original-model'


def test_failed_export_never_publishes_partial_file(runtime):
    from pathlib import Path
    source, cache, calls, ort = runtime
    original_load = ort.InferenceSession

    def interrupted_export(path, sess_options, providers):
        output = getattr(sess_options, 'optimized_model_filepath', '')
        if output:
            Path(output).write_bytes(b'incomplete-ort')
            calls.append((Path(path), sess_options))
            raise OSError('Exportação interrompida após criar arquivo')
        return original_load(path, sess_options, providers)

    ort.InferenceSession = interrupted_export
    timings = {}
    create_engine(source.parent, timings, cache_directory=cache)
    assert [item[0] for item in calls] == [source, source]
    assert not list(cache.glob('*.ort'))
    assert not list(cache.glob('preparing-*'))
    assert not timings['cache_hit']
    assert source.read_bytes() == b'original-model'


def test_full_disk_skips_cache_export_and_loads_once(runtime, monkeypatch):
    source, cache, calls, _ = runtime
    monkeypatch.setattr('therion.voice.kokoro_worker.shutil.disk_usage',
                        lambda path: SimpleNamespace(free=0))
    create_engine(source.parent, cache_directory=cache)
    assert [item[0] for item in calls] == [source]
    assert not getattr(calls[0][1], 'optimized_model_filepath', '')
    assert not list(cache.glob('*.ort'))


def test_unwritable_cache_does_not_prevent_loading(runtime, monkeypatch):
    from pathlib import Path
    source, cache, calls, _ = runtime
    original = Path.mkdir

    def mkdir(path, *args, **kwargs):
        if path == cache:
            raise PermissionError('Temporários indisponíveis')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'mkdir', mkdir)
    create_engine(source.parent, cache_directory=cache)
    assert [item[0] for item in calls] == [source]
    assert not cache.exists()


def test_publication_failure_removes_only_owned_temporary(runtime, monkeypatch):
    from pathlib import Path
    source, cache, calls, _ = runtime
    cache.mkdir()
    unrelated = cache / 'unrelated.txt'
    unrelated.write_text('preservar')
    original = Path.replace

    def replace(path, destination):
        if path.name.startswith('preparing-'):
            raise PermissionError('Cache bloqueado')
        return original(path, destination)

    monkeypatch.setattr(Path, 'replace', replace)
    create_engine(source.parent, cache_directory=cache)
    assert [item[0] for item in calls] == [source]
    assert not list(cache.glob('preparing-*'))
    assert unrelated.read_text() == 'preservar'
    assert source.read_bytes() == b'original-model'


def test_existing_onnx_cache_is_read_only_and_can_prepare_ort(runtime):
    source, cache, calls, _ = runtime
    legacy_root = source.parent / 'runtime-cache'
    legacy_root.mkdir()
    stat = source.stat()
    legacy = legacy_root / f'kokoro-cpu-test-{stat.st_size}-{stat.st_mtime_ns}.onnx'
    legacy.write_bytes(b'previous-cache')
    timings = {}
    create_engine(source.parent, timings, cache_directory=cache)
    assert calls[0][0] == legacy
    assert timings['cache_format'] == 'onnx'
    assert legacy.read_bytes() == b'previous-cache'
    assert list(cache.glob('*.ort'))
    assert source.read_bytes() == b'original-model'


def test_modified_model_and_different_origin_cannot_reuse_old_graph(runtime, tmp_path):
    import os
    source, cache, calls, _ = runtime
    create_engine(source.parent, cache_directory=cache)
    source.write_bytes(b'changed-model-larger')
    create_engine(source.parent, cache_directory=cache)
    other_root = tmp_path / 'other-model'
    other_root.mkdir()
    other = other_root / source.name
    other.write_bytes(source.read_bytes())
    os.utime(other, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns))
    create_engine(other_root, cache_directory=cache)
    assert [item[0] for item in calls] == [source, source, other]
    assert len(list(cache.glob('*.ort'))) == 3


def test_concurrent_preparations_publish_complete_cache(runtime):
    from concurrent.futures import ThreadPoolExecutor
    source, cache, _, _ = runtime
    with ThreadPoolExecutor(max_workers=2) as pool:
        engines = list(pool.map(lambda _: create_engine(source.parent, cache_directory=cache), range(2)))
    assert len(engines) == 2
    prepared, = cache.glob('*.ort')
    assert prepared.read_bytes() == b'valid-ort'
    assert not list(cache.glob('preparing-*'))
    assert source.read_bytes() == b'original-model'
