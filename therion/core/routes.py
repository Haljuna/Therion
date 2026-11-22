"""Qual regra fixa atende a frase, na ordem do orquestrador; None = vai para a IA ou para o reconhecedor de intenção.

Só nomeia a rota (registro de conversa e banco de frases); quem responde continua sendo o orquestrador.
"""
from types import SimpleNamespace


def fixed_route(phrase, projects=None):
    from therion.agent.briefing import briefing_command
    from therion.integrations.task_query import task_query_request, task_state_request
    if briefing_command(phrase):
        return 'panorama'
    if task_query_request(phrase):
        return 'tarefas'
    from therion.agent.mailbox import mail_window_request, mail_count_request
    if mail_window_request(phrase):
        return 'abrir e-mails'
    if mail_count_request(phrase):
        return 'contar e-mails'
    from therion.core.screenshot import screenshot_request
    if screenshot_request(phrase):
        return 'print'
    from therion.memory.commands import memory_request
    if memory_request(phrase):
        return 'memória'
    from therion.core.workflows import read_only_workflow
    if read_only_workflow(phrase):
        return 'composto'
    from therion.context.conversation_frame import app_close_request, repeat_request
    if app_close_request(phrase):
        return 'fechar aplicativo'
    state = task_state_request(phrase)
    if state:
        return 'concluir tarefa' if state['state'] == 'completed' else 'reabrir tarefa'
    from therion.core.voice_reminders import reminder_request
    if reminder_request(phrase, SimpleNamespace(desktop_timers=True)):
        return 'lembrete'
    from therion.core.focus import focus_request
    if focus_request(phrase):
        return 'foco'
    from therion.core.local_reports import game_mode_request, report_request, wake_off_request
    if wake_off_request(phrase):
        return 'wake_off'
    from therion.core.pc_cleanup import cleanup_request, cleanup_then_game
    if game_mode_request(phrase) is not None or cleanup_then_game(phrase):
        return 'modo jogo'
    if cleanup_request(phrase):
        return 'limpar espaço'
    if report_request(phrase, projects) is not None:
        return 'relatório local'
    from therion.agent.gmail_queries import recent_mail_request
    mail = recent_mail_request(phrase)
    if mail:
        return 'último e-mail' if mail[0] == 'peek' else 'e-mail'
    if repeat_request(phrase):
        return 'repetir'
    return None
