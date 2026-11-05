"""Prévia isolada: dados fictícios, sem modelo, rede, microfone ou configuração pessoal.

Uso: .venv/Scripts/python.exe scripts/preview-constellation.py --all-sizes
     --seconds 120 mede apenas o renderizador; não é ensaio de voz/modelo reais.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds',type=float,default=4)
    parser.add_argument('--all-sizes',action='store_true')
    parser.add_argument('--all-pages',action='store_true')
    parser.add_argument('--activity-panels',action='store_true')
    parser.add_argument('--free-windows',action='store_true',help='Exercitar arraste nativo sobre menu e rodapé, sem serviços pessoais.')
    parser.add_argument('--integrated-panels',action='store_true',help='Capturar capacidades, autonomia e confirmações na mesma cena, com estado fictício.')
    parser.add_argument('--mailbox',action='store_true',help='Caixa de demonstração, sem conta Google ou rede.')
    parser.add_argument('--briefing',action='store_true',help='Panorama visual fictício em janelas separadas; não consulta serviços.')
    parser.add_argument('--exercise',action='store_true',help='Alternar janelas e tamanhos durante o ensaio, com dados fictícios.')
    parser.add_argument('--motion-demo',action='store_true',help='Estados e intensidade sintéticos para conferir a animação, sem áudio real.')
    parser.add_argument('--scene-demo',action='store_true',help='Demonstrar a paralaxe com movimento de ponteiro sintético.')
    parser.add_argument('--autonomous-scene',action='store_true',help='Fixar o ponteiro no centro para validar o cenário sem interação.')
    parser.add_argument('--video',action='store_true',help='Exportar a janela em MP4; esta execução não mede desempenho.')
    parser.add_argument('--workspace-demo',action='store_true',help='Demonstrar abertura, organização e recolhimento de janelas fictícias.')
    parser.add_argument('--reference',action='store_true',help='Captura de composição com a agenda compacta e dados fictícios.')
    parser.add_argument('--states',action='store_true')
    parser.add_argument('--sessions',action='store_true',help='Conferir o navegador recolhível de sessões com perfil fictício.')
    parser.add_argument('--static',action='store_true')
    parser.add_argument('--output',default='tmp/constellation-preview')
    parser.add_argument('--scale',default='1')
    parser.add_argument('--size',default='1920x1080')
    parser.add_argument('--quality',choices=['auto','high','medium','low'],default='auto')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = (root/args.output).resolve(); output.mkdir(parents=True,exist_ok=True)
    # Tudo que o desktop eventualmente inicializar permanece no ambiente fictício.
    for variable,folder in [('APPDATA','roaming'),('LOCALAPPDATA','local'),('TEMP','temp'),('TMP','temp')]:
        path=output/'fixture'/folder; path.mkdir(parents=True,exist_ok=True); os.environ[variable]=str(path)
    os.environ['QT_SCALE_FACTOR'] = args.scale
    sys.path.insert(0,str(root))
    from unittest.mock import patch
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel
    from therion.interface.desktop import MainWindow, STYLESHEET
    from therion.interface.dashboard_data import DashboardSource
    from therion.agent.contracts import ToolResult
    from therion.interface.graphics import prepare_graphics

    prepare_graphics()
    app=QApplication([]); app.setStyleSheet(STYLESHEET)
    demo_config={'ui':{'interface':'classic','graphics_quality':args.quality},'ai':{'enabled':False},
                 'tts':{'enabled':False},'calendar':{'enabled':False}}
    autonomy=None
    if args.integrated_panels:
        from therion.autonomy.store import EvidenceStore
        from therion.autonomy.runtime import AutonomyRuntime
        autonomy=AutonomyRuntime(EvidenceStore(output/'fixture'/'autonomy.sqlite3'),lambda:demo_config,lambda config:None)
    with patch.object(MainWindow,'_setup_tray'):
        window=MainWindow(app,config=demo_config,config_loader=lambda:demo_config,
            config_writer=lambda config:None,log_dir=output/'fixture'/'logs',autonomy_runtime=autonomy)
    window._v4_timer.stop()
    if args.mailbox or args.briefing:
        from tests.mailbox_fixture import ReadingMailbox
        mail_fixture=ReadingMailbox()
        window._orchestrator._agent_config.update(enabled=True,gmail_enabled=True)
        window._orchestrator._gmail_adapter_factory=lambda mode:mail_fixture
    if args.static:
        from functools import partial
        from therion.interface.constellation import Constellation
        with patch('therion.interface.dashboard.Constellation',partial(Constellation,static=True)):
            window._select_interface('constellation',persist=False)
    else:window._select_interface('constellation',persist=False)
    dashboard=window._dashboard
    if args.autonomous_scene:
        pointer=dashboard.constellation.set_scene_pointer
        dashboard.constellation.set_scene_pointer=lambda x,y:pointer(0.,0.)
        pointer(0.,0.)
    if args.mailbox:dashboard.mailbox.footnote.setText(dashboard.mailbox.footnote.text()+'\nDEMONSTRAÇÃO · MENSAGENS FICTÍCIAS · SEM CONTA GOOGLE')
    class DemoSource(DashboardSource):
        def identity(self): return (self.host.session_id,'demo',None,False)
        def calendar(self,day,token):
            token.check()
            return {'state':'ready','items':[{'time':t,'title':s} for t,s in [
                ('09:00','Reunião de alinhamento'),('11:30','Revisão do projeto'),
                ('15:00','Planejamento da semana'),('18:30','Academia')]]}
        def tasks(self,token):
            token.check()
            return {'state':'ready','saved':[dict(id=str(i),title=s,state='completed' if i==0 else 'pending') for i,s in enumerate([
                'Finalizar apresentação','Responder e-mails','Revisar documento','Estudar novas referências'])],
                'temporary':[dict(id=1,title='Organizar as ideias desta conversa',completed=False)]}
        def action(self,operation,arguments,token):
            return ToolResult('blocked',message='Esta é uma demonstração com dados fictícios.')
    dashboard.source=DemoSource(window._orchestrator)
    dashboard.epochs['calendar']+=1; dashboard.epochs['tasks']+=1
    dashboard.dirty.update(('calendar','tasks'))
    watermark=QLabel('DEMONSTRAÇÃO · DADOS FICTÍCIOS'); watermark.setObjectName('muted')
    dashboard.home.layout().itemAt(0).widget().layout().insertWidget(0,watermark)
    window._append('Você','Therion, me ajude a organizar o dia.')
    window._append('Therion','Tudo começa com uma conexão.\nSua agenda e suas tarefas estão aqui, quando você precisar.')
    if args.reference:
        dashboard._response='';dashboard.last_response.clear();dashboard._sync_home_copy()
    window._update_orbe('idle')
    width,height=map(int,args.size.split('x'))
    window.resize(width,height); window.show()
    metrics=[]
    sampling=not args.video
    benchmark_seconds=None
    swaps=[]
    presentation_gaps=[]
    last_presented=0
    phase='home'
    phase_marks=[]
    swapped_phases=[]
    swapped_states=[]
    demo_state='idle'
    motion_marks=[]
    draw_times=[]
    draw_stalls=[]
    renderer=dashboard.constellation.renderer
    if renderer:
        renderer.set_quality(args.quality)
        renderer.metrics.connect(lambda item:metrics.append(item) if sampling else None)
        def presented():
            nonlocal last_presented
            # QWidget pode recompor a mesma textura após mudar um rótulo.
            # Contar só apresentações com desenho novo evita inflar o FPS.
            if sampling and len(draw_times)>last_presented:
                stamp=time.monotonic()
                if swaps:
                    presentation_gaps.append({'ms':round((stamp-swaps[-1])*1000,3),
                                              'seconds':round(stamp-started,3),
                                              'before':swapped_phases[-1],'after':phase})
                swaps.append(stamp); swapped_phases.append(phase); swapped_states.append(demo_state)
                last_presented=len(draw_times)
        renderer.frameSwapped.connect(presented)
        draw_frame=renderer._paint_frame
        def timed_frame():
            begin=time.perf_counter()
            try: return draw_frame()
            finally:
                if sampling:
                    duration=(time.perf_counter()-begin)*1000;draw_times.append(duration)
                    if duration>50:draw_stalls.append({'ms':round(duration,3),'phase':phase,'seconds':round(time.monotonic()-started,3)})
        renderer._paint_frame=timed_frame
    started=time.monotonic()
    video_timer=None;video=None;video_stream=None;video_frames=0;last_video_tick=-1
    def stop_video():
        nonlocal video
        if video is None:return
        video_timer.stop()
        for packet in video_stream.encode():video.mux(packet)
        video.close();video=None
    if args.video:
        import av
        import numpy as np
        from fractions import Fraction
        from PySide6.QtGui import QImage
        video=av.open(str(output/'scene-preview.mp4'),mode='w',options={'movflags':'faststart'})
        video_stream=video.add_stream('libx264',rate=25)
        video_stream.width=window.width()//2*2;video_stream.height=window.height()//2*2;video_stream.pix_fmt='yuv420p'
        video_stream.options={'crf':'17','preset':'veryfast'}
        def video_frame():
            nonlocal video_frames,last_video_tick
            tick=round((time.monotonic()-started)*25)
            if tick<=last_video_tick:return
            shot=window.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
            pixels=np.frombuffer(shot.constBits(),dtype=np.uint8).reshape(shot.height(),shot.bytesPerLine()//4,4)
            frame=av.VideoFrame.from_ndarray(pixels[:video_stream.height,:video_stream.width,:],format='rgba')
            frame.pts=tick;frame.time_base=Fraction(1,25);last_video_tick=tick
            for packet in video_stream.encode(frame):video.mux(packet)
            video_frames+=1
        video_timer=QTimer(window);video_timer.setInterval(40);video_timer.timeout.connect(video_frame);video_timer.start()
    if args.reference:QTimer.singleShot(350,lambda:dashboard.toggle_activity('calendar'))
    motion_timer=None
    if args.motion_demo or args.scene_demo:
        import math
        from therion.interface.presentation import LABELS
        dashboard.timer.stop()
        demo_states=['idle','preparing','listening','transcribing','thinking','executing','synthesizing',
                     'speaking','awaiting_confirmation','error','idle']
        def animate():
            nonlocal demo_state
            elapsed=time.monotonic()-started
            state=demo_states[min(len(demo_states)-1,int(elapsed/max(.2,args.seconds/len(demo_states))))]
            if not motion_marks or state!=demo_state:
                motion_marks.append({'state':state,'seconds':round(elapsed,3)})
            demo_state=state
            intensity=0.
            if state in {'speaking','listening'}:
                intensity=max(0.,min(1.,.48+.28*math.sin(elapsed*9)+.16*math.sin(elapsed*17)))
                if elapsed%3.8>2.8: intensity=0.
            dashboard.status.setText(LABELS[state])
            dashboard.constellation.set_visual(state,intensity); dashboard.meter.set_level(state,intensity)
            if args.scene_demo:dashboard.constellation.set_scene_pointer(math.sin(elapsed*.33),math.cos(elapsed*.25))
        motion_timer=QTimer(window); motion_timer.setInterval(33);motion_timer.timeout.connect(animate)
        animate();motion_timer.start()
    phase_marks.append({'phase':phase,'seconds':0.})
    if args.exercise:
        def exercise(name,sections,size=None):
            nonlocal phase
            begin=time.monotonic()
            phase=name; phase_marks.append({'phase':name,'seconds':round(time.monotonic()-started,3)})
            dashboard.navigate(0)
            if size: window.resize(*size)
            for section in sections:
                if section in ('capabilities','authorized-history','proposals'):
                    dashboard.agent_tab(('capabilities','authorized-history','proposals').index(section))
                elif section=='autonomy':window._show_autonomy()
                elif section=='procedures':dashboard.procedures()
                elif section in {'mail','mail-read','mail-more'}:
                    dashboard.open_mail('m2' if section=='mail-read' else '')
                    if section=='mail-more':dashboard.mailbox.load_more()
                elif section=='agenda-mail':dashboard.toggle_activity('calendar')
                else:dashboard.navigate(section)
            phase_marks[-1]['dispatch_ms']=round((time.monotonic()-begin)*1000,3)
        duration=max(2.,args.seconds)
        phases=[
            (1/6,'tasks',[3],None),(2/6,'agenda-and-tasks',[2,3],None),
            (3/6,'conversations',[1],None),(4/6,'compact',[3],(960,640)),
            (5/6,'home-restored',[],(width,height))]
        if args.integrated_panels:
            phases=[(1/8,'capabilities',['capabilities'],None),
                    (2/8,'authorized-history',['authorized-history'],None),
                    (3/8,'proposals',['proposals'],None),(4/8,'autonomy',['autonomy'],None),
                    (5/8,'procedures',['procedures'],None),
                    (6/8,'compact-capabilities',['capabilities'],(960,640)),
                    (7/8,'home-restored',[],(width,height))]
        if args.mailbox:
            phases=[(1/6,'mail',['mail'],None),(2/6,'mail-read',['mail-read'],None),
                    (3/6,'mail-more',['mail-more'],None),(4/6,'compact-mail',['mail-read'],(960,640)),
                    (5/6,'agenda-mail',['agenda-mail'],(width,height))]
        for fraction,name,sections,size in phases:
            QTimer.singleShot(round(duration*fraction*1000),lambda n=name,s=sections,z=size:exercise(n,s,z))
    if args.workspace_demo:
        def show_activity():
            dashboard.navigate(2);dashboard.navigate(3);dashboard.workspace.organize(['mail','calendar','tasks'])
        QTimer.singleShot(round(args.seconds*250),lambda:dashboard.open_mail('m2'))
        QTimer.singleShot(round(args.seconds*500),show_activity)
        QTimer.singleShot(round(args.seconds*750),lambda:dashboard.navigate(0))
    captures=[]
    preview_errors=[]
    capture_sizes={}
    drag_results=[]
    def capture(name):
        nonlocal sampling,benchmark_seconds
        stop_video()
        if sampling:
            benchmark_seconds=round(time.monotonic()-started,3);sampling=False
        path=output/name; window.grab().save(str(path)); captures.append(str(path))
        if renderer and renderer.ready:
            renderer.grabFramebuffer().save(str(output/('core-'+name)))
        capture_sizes[name]={'logical':[window.width(),window.height()],'scale':window.devicePixelRatioF()}
        mail=dashboard.mailbox
        capture_sizes[name]['mail_layout']={'compact':mail.compact,
            'split_count':mail.splitter.count(),'sizes':mail.splitter.sizes(),
            'widgets':{key:{'hidden':widget.isHidden(),'visible':widget.isVisible(),'rect':list(widget.geometry().getRect()),
                            'parent':type(widget.parentWidget()).__name__ if widget.parentWidget() else None}
                       for key,widget in [('splitter',mail.splitter),('list',mail.list_page),('reader',mail.reader_page),('rows',mail.list),('body',mail.body),('subject',mail.subject)]}}
        if name=='mailbox-reading.png':mail.grab().save(str(output/'mail-widget.png'))
        if renderer:
            capture_sizes[name]['scene']=[renderer.width(),renderer.height()]
            capture_sizes[name]['focus']=list(renderer._focus().getRect())
            capture_sizes[name]['hero']=list(dashboard.hero_space.geometry().getRect())
    def finish():
        stop_video()
        if motion_timer: motion_timer.stop()
        report={'mode':'static' if not renderer else 'opengl','opengl_ready':bool(renderer and renderer.ready),
            'seconds':round(time.monotonic()-started,2),'metrics':metrics,'captures':captures,'capture_sizes':capture_sizes,
            'notice':dashboard.constellation.notice.text(),
            'exercise':phase_marks,
            'window_drag':drag_results,
            'errors':preview_errors,
            'motion_demo':motion_marks,
            'scene_demo':args.scene_demo,
            'autonomous_scene':args.autonomous_scene,
            'video':{'file':'scene-preview.mp4','frames':video_frames,'fps':25,'not_a_benchmark':True} if args.video else None,
            'benchmark_seconds':benchmark_seconds,
            'capture_readbacks_excluded_from_metrics':True,
            'limitations':'Dados fictícios. Sem inferência ou reprodução de voz reais.'}
        if renderer and renderer.ready:
            report['graphics']={'samples':renderer.context().format().samples(),
                                'framebuffer':'native resolution', 'requested_quality':args.quality,
                                'particle_counts':renderer.quality.COUNTS}
            report['graphics']['active_window']=window.isActiveWindow()
            report['graphics']['longest_gaps']=sorted(presentation_gaps,key=lambda item:item['ms'],reverse=True)[:5]
            if draw_times:
                report['graphics']['draw_dispatch_ms']=round(sum(draw_times)/len(draw_times),3)
                report['graphics']['draw_dispatch_max_ms']=round(max(draw_times),3)
                report['graphics']['slow_draws']=draw_stalls
            if len(swaps)>1:
                gaps=sorted(b-a for a,b in zip(swaps,swaps[1:]))
                report['graphics']['composition']={
                    'frames':len(swaps),
                    'fps':round((len(swaps)-1)/(swaps[-1]-swaps[0]),2),
                    'p95_ms':round(gaps[int(.95*(len(gaps)-1))]*1000,2),
                    'max_ms':round(gaps[-1]*1000,2)}
                phases={}
                for name in dict.fromkeys(swapped_phases):
                    stamps=[value for value,tag in zip(swaps,swapped_phases) if tag==name]
                    if len(stamps)>1:
                        intervals=sorted(b-a for a,b in zip(stamps,stamps[1:]))
                        phases[name]={'frames':len(stamps),'fps':round((len(stamps)-1)/(stamps[-1]-stamps[0]),2),
                                      'p95_ms':round(intervals[int(.95*(len(intervals)-1))]*1000,2),
                                      'max_ms':round(intervals[-1]*1000,2)}
                report['graphics']['phases']=phases
                motion_stats={}
                for name in dict.fromkeys(swapped_states):
                    intervals=[b-a for a,b,first,second in zip(swaps,swaps[1:],swapped_states,swapped_states[1:])
                               if first==second==name]
                    if intervals:
                        ordered=sorted(intervals)
                        motion_stats[name]={'fps':round(len(intervals)/sum(intervals),2),
                                            'p95_ms':round(ordered[int(.95*(len(ordered)-1))]*1000,2)}
                report['graphics']['motion_states']=motion_stats
        (output/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        dashboard.cancel()
        for worker in list(dashboard.workers.values()): worker.wait(1000)
        for worker in list(dashboard.mailbox.jobs.values()):worker.wait(3000)
        if window._v4_worker is not None:window._v4_worker.wait(3000);app.processEvents()
        window._closing=True; window.close(); app.quit()
    delay=max(1800,int(args.seconds*1000))
    steps=[(delay,lambda:capture(args.size+'.png'))]
    if args.all_sizes:
        steps.extend([(0,lambda:window.resize(1440,900)),(700,lambda:capture('1440x900.png')),
                      (0,lambda:window.resize(960,640)),(700,lambda:capture('960x640.png'))])
    if args.all_pages:
        steps.append((0,lambda:window.resize(1440,900)))
        for index in range(7):
            steps.extend([(0,lambda:dashboard.navigate(0)),(0,lambda i=index:dashboard.navigate(i)),
                          (600,lambda i=index:capture('page-'+str(i)+'.png'))])
    if args.activity_panels:
        steps.extend([(0,lambda:window.resize(width,height)),(0,lambda:dashboard.navigate(0)),
                      (0,lambda:dashboard.toggle_activity('calendar')),(600,lambda:capture('agenda-open.png')),
                      (0,lambda:dashboard.navigate(0)),(0,lambda:dashboard.navigate(3)),
                      (600,lambda:capture('tasks-open.png')),
                      (0,lambda:dashboard.navigate(2)),(600,lambda:capture('windows-open.png'))])
    if args.free_windows:
        from PySide6.QtCore import Qt,QPoint,QPointF,QEvent
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtTest import QTest
        def drag_window(key,corner):
            panel=dashboard.workspace.panels[key]
            panel.resize(440,400)
            limits=dashboard.workspace_rect()
            target=QPoint(limits.left() if corner=='top-left' else limits.right()-panel.width()+1,
                          limits.top() if corner=='top-left' else limits.bottom()-panel.height()+1)
            grip=QPoint(60,15)
            QTest.mousePress(panel.title_bar,Qt.LeftButton,Qt.NoModifier,grip)
            destination=dashboard.mapToGlobal(target+panel.title_bar.pos()+grip)
            event=QMouseEvent(QEvent.MouseMove,QPointF(panel.title_bar.mapFromGlobal(destination)),
                             QPointF(destination),Qt.NoButton,Qt.LeftButton,Qt.NoModifier)
            QApplication.sendEvent(panel.title_bar,event)
            QTest.mouseRelease(panel.title_bar,Qt.LeftButton,Qt.NoModifier,grip)
            assert panel.pos()==target
            dashboard._arrange_scene()
            assert panel.pos()==target
            front=dashboard.childAt(panel.geometry().center())
            assert front is panel or panel.isAncestorOf(front)
            drag_results.append({'key':key,'corner':corner,'position':[target.x(),target.y()],
                                 'bounds':list(limits.getRect()),'front':True})
        steps.extend([(0,lambda:window.resize(1440,900)),(0,lambda:dashboard.navigate(0)),
                      (0,lambda:dashboard.navigate(3)),(300,lambda:drag_window('tasks','top-left')),
                      (400,lambda:capture('tasks-top-left.png')),
                      (0,lambda:dashboard.navigate(2)),(300,lambda:drag_window('calendar','bottom-right')),
                      (400,lambda:capture('free-windows.png'))])
    if args.integrated_panels:
        from therion.interface.surface_dialogs import MessageBox
        def section(key,index=0):
            dashboard.workspace.hide_all()
            if key in dashboard.workspace.panels:dashboard.workspace.panels[key].positioned=False
            if key=='capabilities':dashboard.agent_tab(index)
            elif key=='procedures':dashboard.procedures()
            else:window._show_autonomy();window._autonomy_panel.nav.setCurrentRow(index)
        steps.append((0,lambda:window.resize(1440,900)))
        for key,index,name in [('capabilities',0,'capabilities'),('capabilities',1,'history'),
                               ('capabilities',2,'proposals'),('procedures',0,'procedures'),
                               ('autonomy',0,'applications'),('autonomy',1,'routines'),
                               ('autonomy',2,'technical-memory'),('autonomy',3,'evidence')]:
            steps.extend([(0,lambda k=key,i=index:section(k,i)),(700,lambda n=name:capture('integrated-'+n+'.png'))])
        def confirmation():
            def review():
                capture('integrated-confirmation.png')
                dashboard.surfaces.modals[-1][0].button(MessageBox.No).click()
            QTimer.singleShot(400,review)
            MessageBox.question(window,'Confirmação interna · demonstração','Exemplo com dados fictícios. Nenhuma capacidade ou autorização será alterada.')
        steps.append((0,confirmation))
    if args.mailbox:
        def mail_home():
            dashboard.navigate(0);window.resize(1440,900)
            dashboard.workspace.panels['mail'].positioned=False
            dashboard.open_mail()
        def mail_search():dashboard.mailbox.search_field.setText('projeto');dashboard.mailbox.search()
        def small_mail():
            window.resize(960,640);dashboard.mailbox.search_field.clear();dashboard.mailbox.search();dashboard.open_mail('m2')
        steps.extend([(0,mail_home),(700,lambda:capture('mailbox-list.png')),
                      (0,lambda:dashboard.open_mail('m2')),(600,lambda:capture('mailbox-reading.png')),
                      (0,lambda:dashboard.mailbox.read_mode.setCurrentIndex(1)),(300,lambda:capture('mailbox-complete.png')),
                      (0,lambda:dashboard.mailbox.read_mode.setCurrentIndex(0)),
                      (0,lambda:dashboard.mailbox.load_more()),(600,lambda:capture('mailbox-more.png')),
                      (0,mail_search),(600,lambda:capture('mailbox-search.png')),
                      (0,lambda:dashboard.navigate(0)),(0,lambda:dashboard.toggle_activity('calendar')),
                      (600,lambda:capture('mailbox-agenda.png')),
                      (0,small_mail),(600,lambda:capture('mailbox-960x640.png'))])
    if args.sessions:
        steps.extend([(0,lambda:window.resize(1440,900)),(0,lambda:dashboard.navigate(1)),
                      (0,dashboard.toggle_sessions),(600,lambda:capture('sessions-wide.png')),
                      (0,lambda:window.resize(960,640)),(600,lambda:capture('sessions-compact.png')),
                      (0,lambda:dashboard.workspace.panels['sessions'].dismiss()),
                      (400,lambda:capture('sessions-return.png'))])
    if args.states:
        from therion.interface.presentation import LABELS
        def set_state(state):
            if motion_timer: motion_timer.stop()
            dashboard.timer.stop()
            dashboard.status.setText(LABELS[state])
            dashboard.constellation.set_visual(state,.65 if state in {'speaking','listening'} else 0.)
            dashboard.meter.set_level(state,.65 if state in {'speaking','listening'} else 0.)
        steps.append((0,lambda:dashboard.navigate(0)))
        for index,state in enumerate(['idle','preparing','listening','transcribing','thinking','executing','synthesizing','speaking','awaiting_confirmation','error']):
            steps.extend([(0,lambda s=state:set_state(s)),
                          (500,lambda s=state:capture('state-'+s+'.png'))])
    if args.briefing:
        from therion.agent.contracts import CancellationToken
        def demo_briefing():
            dashboard.status.setText('Pronto para conversar');dashboard.constellation.set_visual('idle',0.)
            dashboard.navigate(0);window.resize(width,height);dashboard.open_briefing()
            dashboard.mailbox.filter.blockSignals(True);dashboard.mailbox.filter.setCurrentIndex(0);dashboard.mailbox.filter.blockSignals(False)
            dashboard.mailbox.search_field.clear();dashboard.mailbox.search()
            QTimer.singleShot(350,lambda:dashboard.mailbox.opened('m2'))
            token=CancellationToken()
            rows={'calendar':dashboard.source.calendar(dashboard.day,token),'tasks':dashboard.source.tasks(token),
                'mail':dict(state='ready',first=False,complete=True,count=3,page=dashboard.mailbox.status())}
            for kind,result in rows.items():dashboard.briefing_part(dict(kind=kind,result=result))
            dashboard.briefing_open=False
        def compact_briefing():
            window.resize(960,640);dashboard.workspace.organize(['mail','calendar','tasks'])
        steps.extend([(0,demo_briefing),(900,lambda:capture('command-panorama.png')),
                      (0,compact_briefing),(700,lambda:capture('command-panorama-compact.png'))])
    steps.append((200,finish))
    def next_step():
        if not steps: return
        wait,action=steps.pop(0)
        def run():
            try:action()
            except Exception as error:
                preview_errors.append(str(error));finish();return
            next_step()
        QTimer.singleShot(wait,run)
    next_step()
    app.exec()
    saved=json.loads((output/'report.json').read_text(encoding='utf-8'))
    print(json.dumps({'output':str(output),'opengl_ready':saved['opengl_ready'],'samples':len(metrics)}))
    if preview_errors:raise RuntimeError('; '.join(preview_errors))


if __name__=='__main__': main()
