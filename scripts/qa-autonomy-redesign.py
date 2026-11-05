"""Host isolado; --functional permite testar somente o Mapa de Caracteres real.

Os demais executáveis são fictícios e não devem ser abertos no modo funcional.
Permissões, notas e atalhos ficam exclusivamente na fixture do projeto.
"""
from pathlib import Path
import os
import sys
from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
state=ROOT/'tmp'/'v4-tests'/'visual-redesign'
state.mkdir(parents=True,exist_ok=True)
for key in ('APPDATA','LOCALAPPDATA','TMP','TEMP'):
    destination=state/key;destination.mkdir(exist_ok=True);os.environ[key]=str(destination)

from tests.test_autonomy_panel_v4 import PanelTests
from therion.autonomy.apps import ApplicationCatalog
from therion.autonomy.integration import implementation_version
import therion.interface.autonomy_panel as module

PanelTests.setUpClass()
fixture=PanelTests();fixture.setUp()
functional='--functional' in sys.argv
if functional:
    fixture.config['runtime']=dict(real_actions_enabled=True)
    fixture.config['autonomy']=dict(app_opening_mode='real')
catalog=ApplicationCatalog(fixture.runtime)
rows=[]
for name in ('Editor de teste','Navegador de teste','Notas de teste','Música de teste'):
    path=fixture.root/(name+'.exe');path.write_bytes(b'visual fixture - never execute')
    rows.append(dict(name=name,path=str(path),source='Fixture visual'))
for row in rows[:2]:
    app=catalog.register(row['name'],row['path'])
    fixture.seed('open_app',app.id,implementation_version(fixture.runtime,app.as_dict()))
if functional:
    actual=catalog.register('Mapa de Caracteres — teste real',str(Path(os.environ['WINDIR'])/'System32'/'charmap.exe'))
    fixture.seed('open_app',actual.id,implementation_version(fixture.runtime,actual.as_dict()))
module.discover_applications=lambda:rows
if functional:
    from therion.memory.runtime import KnowledgeRuntime
    from therion.interface.desktop import MainWindow
    from therion.autonomy.windows import StartupShortcut
    from PySide6.QtCore import QTimer
    vault=fixture.root/'vault'
    destination=vault/'90 - Sistema da IA'/'Notas de Rascunho da IA'/'Registros'
    destination.mkdir(parents=True)
    notes=vault/'10 - Projetos'/'Therion';notes.mkdir(parents=True)
    note=notes/'Nota fictícia.md';note.write_text('Procedimento de teste visual.\n',encoding='utf-8')
    fixture.config['knowledge_access']=dict(read_all=True,supervised_memory=True,
        authorization='Fixture isolada para QA autorizado pelo usuário.',
        expires_at=(fixture.now+timedelta(days=60)).isoformat(),revision=1)
    knowledge=KnowledgeRuntime(vault,fixture.root/'knowledge',lambda:deepcopy(fixture.config),
        clock=lambda:fixture.now,config_writer=fixture.write)
    class Calendar:
        def list_events_for_day(self,day):return []
    with patch.object(MainWindow,'_setup_tray'),patch.object(MainWindow,'_build_calendar_adapter',return_value=Calendar()):
        window=MainWindow(PanelTests.app,fixture.config,knowledge_runtime=knowledge,
            config_loader=lambda:deepcopy(fixture.config),config_writer=fixture.write,
            autonomy_runtime=fixture.runtime,log_dir=str(fixture.root/'logs'))
    window._v4_timer.stop();window._memory_timer.stop()
    startup=fixture.root/'startup';startup.mkdir()
    module.StartupShortcut=lambda:StartupShortcut(startup=startup)
    window._procedure_memory.configure(str(destination))
    specs=[window._routine_service.configure('daily_summary',8,0),
        window._routine_service.configure('review_notes',18,0,[str(note)],6)]
    for spec in specs:fixture.seed(spec.operation,spec.id,window._routine_service.version(spec))
    target,version,_=window._procedure_memory.scope()
    fixture.seed('remember_procedure',target,version)
    # Controle de relógio somente para expiração na fixture; nenhuma ação é
    # executada por esse canal. Remover o arquivo após leitura evita repetição.
    control=state/'clock.json'
    def advance_clock():
        if control.exists():
            delta=json.loads(control.read_text(encoding='utf-8'))['days']
            control.unlink();fixture.now+=timedelta(days=delta)
            if window._autonomy_panel:window._autonomy_panel.refresh()
    clock_timer=QTimer(window);clock_timer.timeout.connect(advance_clock);clock_timer.start(500)
else:
    window=fixture.window()
window.setWindowTitle('Therion QA — ambiente fictício')
window.show()
if not functional:window._routine_service.configure('daily_summary',8,0)
window._show_autonomy()
panel=window._autonomy_panel
if '--standalone' in sys.argv:
    # Permite ao cliente de automação selecionar o HWND do painel diretamente,
    # evitando que teclas direcionadas ao HWND pai mudem o foco para a conversa.
    panel.setParent(None)
panel.setWindowTitle('Therion — QA do redesign (dados fictícios)')
panel.show();panel.raise_();panel.activateWindow()
fixture.wait(window)
panel.grab().save(str(state/'aplicativos.png'))
if '--snapshots' in sys.argv:
    from therion.interface.autonomy_widgets import ApplicationGallery
    for index,name in enumerate(('aplicativos','rotinas','memoria','evidencias')):
        panel.nav.setCurrentRow(index);PanelTests.app.processEvents()
        panel.grab().save(str(state/(name+'.png')))
    gallery=ApplicationGallery(panel,rows);gallery.show();PanelTests.app.processEvents()
    gallery.tiles[2].check.setChecked(True);PanelTests.app.processEvents()
    gallery.grab().save(str(state/'galeria.png'));gallery.close()
    panel.resize(860,640);panel.nav.setCurrentRow(0);PanelTests.app.processEvents()
    panel.grab().save(str(state/'aplicativos-860.png'))
    panel.close();window.close()
else:
    PanelTests.app.exec()
if functional:
    report=dict(config=fixture.config,evidence=[dict(operation=e.operation,status=e.status,mode=e.mode)
        for e in fixture.store.recent()],drafts=[p.name for p in destination.glob('*.md')],
        startup=[p.name for p in startup.iterdir()],fixture_root=str(fixture.root))
    (state/'functional-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
window._orchestrator.close()
fixture.doCleanups()
fixture.tearDown()
