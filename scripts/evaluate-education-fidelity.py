"""Avaliação local com perfil e cursos inteiramente fictícios; sem microfone."""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from therion.core.ai_core import AICore
from therion.core.ai_provider_ollama import OllamaProvider
from therion.core.orchestrator import Orchestrator
from therion.context.source_education import formation_context


def main():
    root = Path(tempfile.mkdtemp(prefix='therion-education-fidelity-'))
    project = root/'vault'/'10 - Projetos'/'Therion'
    project.mkdir(parents=True)
    profile = '''# Perfil fictício
## Formação
### Faculdade
- Curso: Engenharia Biomédica
- Período letivo atual: 2028.1
- Disciplinas: Geometria Descritiva
### Formação técnica
- Curso técnico em Instrumentação no Instituto Fictício
- Período: 2020 a 2022
- Situação: concluído
'''
    notes = {'Perfil fictício.md': profile,
             'Geometria Descritiva.md': '# Geometria Descritiva\nAtividade fictícia: representar vistas de um sólido.'}
    for name, content in notes.items():
        (project/name).write_text(content, encoding='utf-8')
    originals = {path: path.read_bytes() for path in project.glob('*.md')}
    provider = OllamaProvider(model='hf.co/pramodlohra/Qween3_4B_thinking_finetune:Q4_K_M',
                             endpoint='http://127.0.0.1:11435/api/chat', think=True, timeout=90)
    assistant = Orchestrator(vault_root=str(root/'vault'), log_dir=str(root/'logs'),
                             ai_core=AICore(provider, []))
    report = {'commands': []}
    output = root/'report.json'
    print('REPORT=' + str(output), flush=True)
    try:
        for command in ('busque no Segundo Cérebro Geometria Descritiva',
                        'busque no Segundo Cérebro Instrumentação',
                        'leia a nota Perfil fictício.md',
                        'Qual formação está concluída e qual curso é atual?'):
            result = assistant.process_command(command)
            evidence = assistant._last_tool_evidence
            valid = result.status == 'success'
            row = {'command': command, 'status': result.status, 'answer': result.message,
                   'completed': valid, 'evidence': evidence}
            report['commands'].append(row)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'command': command, 'status': result.status, 'answer': result.message,
                              'completed': valid}, ensure_ascii=True), flush=True)
            assert valid, row
        assert all(path.read_bytes() == value for path, value in originals.items())
        final = report['commands'][-1]['answer'].casefold()
        assert 'instrumentação' in final and 'biomédica' in final
        assert ('conclu' in final or 'termin' in final) and ('atual' in final or 'cursa' in final)
        report['source_notes_unchanged'] = True
        alternate = '''# Perfil alternativo fictício
## Graduação concluída
- Curso: Engenharia Biomédica
- Período: 2020 a 2022
- Situação: concluído
## Curso técnico atual
- Curso técnico em Instrumentação no Instituto Fictício
- Período letivo atual: 2028.1
- Situação: em andamento
'''
        evidence = {'kind': 'note', 'path': 'Perfil alternativo fictício.md', 'content': alternate,
                    'formation_context': formation_context(alternate), 'partial': False}
        answer = provider.describe_result('Neste perfil alternativo, qual curso já terminou e qual é atual?', evidence, {})
        report['counterfactual'] = {'evidence': evidence, 'answer': answer}
        print(json.dumps({'counterfactual_answer': answer}, ensure_ascii=True), flush=True)
        assert 'biomédica' in answer.casefold() and 'instrumentação' in answer.casefold()
        assert ('conclu' in answer.casefold() or 'termin' in answer.casefold())
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        assistant.close()


if __name__ == '__main__':
    main()
