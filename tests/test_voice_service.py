"""Testes do VoiceModelService — sem carregar modelo real."""

import inspect
import threading
from pathlib import Path

from PySide6.QtCore import Qt

import therion.voice.service as voice_module
from therion.voice import VoiceModelService

_TIMEOUT = 5.0


def _connect(signal, handler) -> threading.Event:
    event = threading.Event()
    signal.connect(handler, Qt.ConnectionType.DirectConnection)
    return event


def _wait(event: threading.Event, label: str) -> None:
    assert event.wait(_TIMEOUT), f"timeout aguardando {label}"


def test_caminho_valido_carrega_em_background(tmp_path):
    calls = []
    fake = object()

    def factory(path):
        calls.append(path)
        return fake

    service = VoiceModelService(str(tmp_path), model_factory=factory)
    states = []
    service.state_changed.connect(
        lambda s: states.append(s), Qt.ConnectionType.DirectConnection
    )
    loaded_event = threading.Event()
    received = []
    service.loaded.connect(
        lambda inst: (received.append(inst), loaded_event.set()),
        Qt.ConnectionType.DirectConnection,
    )

    assert service.state == "unloaded"
    assert service.load() is True
    _wait(loaded_event, "loaded")

    assert calls == [str(tmp_path)]
    assert states == ["loading", "ready"]
    assert service.state == "ready"
    assert service.model is fake
    assert received == [fake]


def test_caminho_inexistente_sem_factory(tmp_path):
    missing = tmp_path / "nao_existe"
    calls = []

    def factory(path):
        calls.append(path)
        return object()

    service = VoiceModelService(str(missing), model_factory=factory)
    failed_event = threading.Event()
    service.load_failed.connect(
        lambda msg: failed_event.set(), Qt.ConnectionType.DirectConnection
    )

    assert service.load() is False
    _wait(failed_event, "load_failed")
    assert calls == []
    assert service.state == "error"
    assert service.load() is False
    assert service.state == "error"


def test_factory_com_excecao(tmp_path):
    def factory(path):
        raise RuntimeError("falhou ao carregar")

    service = VoiceModelService(str(tmp_path), model_factory=factory)
    failed_event = threading.Event()
    messages = []
    service.load_failed.connect(
        lambda msg: (messages.append(msg), failed_event.set()),
        Qt.ConnectionType.DirectConnection,
    )

    assert service.load() is True
    _wait(failed_event, "load_failed")
    assert service.state == "error"
    assert service.model is None
    assert messages and "falhou ao carregar" in messages[0]


def test_retry_apos_falha(tmp_path):
    attempts = []

    def factory(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise RuntimeError("primeira falha")
        return "modelo-ok"

    service = VoiceModelService(str(tmp_path), model_factory=factory)
    ready_event = threading.Event()
    service.state_changed.connect(
        lambda s: ready_event.set() if s == "ready" else None,
        Qt.ConnectionType.DirectConnection,
    )
    failed_event = threading.Event()
    service.load_failed.connect(
        lambda msg: failed_event.set(), Qt.ConnectionType.DirectConnection
    )

    assert service.load() is True
    _wait(failed_event, "primeira falha")
    assert service.state == "error"

    assert service.load() is True
    _wait(ready_event, "ready")
    assert service.state == "ready"
    assert service.model == "modelo-ok"
    assert len(attempts) == 2


def test_concorrencia_segunda_chamada_false(tmp_path):
    gate = threading.Event()
    calls = []

    def factory(path):
        calls.append(path)
        gate.wait(_TIMEOUT)
        return "instancia"

    service = VoiceModelService(str(tmp_path), model_factory=factory)
    ready_event = threading.Event()
    service.state_changed.connect(
        lambda s: ready_event.set() if s == "ready" else None,
        Qt.ConnectionType.DirectConnection,
    )

    assert service.load() is True
    assert service.load() is False
    assert service.load() is False
    gate.set()
    _wait(ready_event, "ready")
    assert service.state == "ready"
    assert len(calls) == 1


def test_factory_roda_fora_da_thread_principal(tmp_path):
    ident = {}

    def factory(path):
        ident["value"] = threading.get_ident()
        return "ok"

    service = VoiceModelService(str(tmp_path), model_factory=factory)
    loaded_event = threading.Event()
    service.loaded.connect(
        lambda inst: loaded_event.set(), Qt.ConnectionType.DirectConnection
    )

    assert service.load() is True
    _wait(loaded_event, "loaded")
    assert ident["value"] != threading.main_thread().ident


def test_sem_acao_automatica():
    source = inspect.getsource(voice_module)
    for proibido in ("sounddevice", "InputStream", "start_capture", "transcribe"):
        assert proibido not in source, f"conteudo proibido: {proibido}"


def test_independencia_do_piloto():
    pacote = Path(voice_module.__file__).parent
    arquivos = [
        item for item in pacote.iterdir()
        if item.is_file() and item.suffix == ".py"
    ]
    assert arquivos
    proibidos = (
        "Therion-V2-Piloto",
        "models--",
        "glob(",
        "next(",
        "snapshot_download",
        "HF_",
    )
    for arquivo in arquivos:
        texto = arquivo.read_text(encoding="utf-8")
        for proibido in proibidos:
            assert proibido not in texto, f"{arquivo.name}: contem {proibido}"


def test_reentrancia_sem_deadlock(tmp_path):
    sentinel = object()
    calls = []
    initial = []
    state_results = []
    failed_results = []
    loaded_results = []
    errors = []
    final = threading.Event()
    failed_done = threading.Event()

    def factory(path):
        calls.append(path)
        if len(calls) == 1:
            raise RuntimeError("primeira falha")
        return sentinel

    service = VoiceModelService(str(tmp_path), model_factory=factory)

    def on_state(state):
        if state == "loading":
            state_results.append(service.load())

    def on_failed(msg):
        try:
            failed_results.append(service.load())
        finally:
            failed_done.set()

    def on_loaded(instance):
        loaded_results.append(service.load())
        final.set()

    service.state_changed.connect(on_state, Qt.ConnectionType.DirectConnection)
    service.load_failed.connect(on_failed, Qt.ConnectionType.DirectConnection)
    service.loaded.connect(on_loaded, Qt.ConnectionType.DirectConnection)

    def sequence():
        try:
            initial.append(service.load())
        except BaseException as exc:  # noqa: BLE001 - vira falha do teste
            errors.append(exc)
            final.set()

    runner = threading.Thread(target=sequence, daemon=True)
    runner.start()

    assert final.wait(10.0), "deadlock: reentrancia nao terminou em 10s"
    _wait(failed_done, "termino do callback on_failed")
    runner.join(_TIMEOUT)
    assert not runner.is_alive(), "thread runner nao terminou"
    assert not errors, f"excecao na sequencia: {errors}"
    assert initial == [True]
    assert state_results == [False, False]
    assert failed_results == [True]
    assert loaded_results == [False]
    assert len(calls) == 2
    assert service.state == "ready"
    assert service.model is sentinel


def test_estado_loading_antes_de_ready(tmp_path):
    def factory(path):
        return "instantaneo"

    service = VoiceModelService(str(tmp_path), model_factory=factory)
    states = []
    ready_event = threading.Event()

    def on_state(state):
        states.append(state)
        if state == "ready":
            ready_event.set()

    service.state_changed.connect(on_state, Qt.ConnectionType.DirectConnection)

    assert service.load() is True
    _wait(ready_event, "ready")
    assert states == ["loading", "ready"]
