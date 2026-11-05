"""Roteiro limitado com conteúdo inteiramente fictício e modelo local atual."""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from therion.core.ai_core import AICore
from therion.core.ai_provider_ollama import OllamaProvider
from therion.core.orchestrator import Orchestrator


def main():
    root=Path(tempfile.mkdtemp(prefix='therion-search-followup-eval-'))
    project=root/'vault'/'10 - Projetos'/'Therion';project.mkdir(parents=True)
    notes={'Aetherion.md':'# Aetherion\nProjeto fictício de teste, sem relação com os dados pessoais.',
           'a-Objetivos.md':'# Objetivos\nAetherion: experimentar progresso fictício.',
           'b-Perfil.md':'# Perfil\nAetherion: estudo fictício.',
           'c-Experiencia.md':'# Experiência\nAetherion: interação fictícia.',
           'd-Personagem e Classes.md':'# Personagem e Classes\nAetherion: representação de progresso fictício.\n'+
                'Introdução de teste. '*30+'\nLista completa de classes fictícias: Explorador, Artífice e Guardião. São três classes.'}
    for name,text in notes.items():(project/name).write_text(text,encoding='utf-8')
    provider=OllamaProvider(model='hf.co/pramodlohra/Qween3_4B_thinking_finetune:Q4_K_M',
                           endpoint='http://127.0.0.1:11435/api/chat',think=True)
    orch=Orchestrator(vault_root=str(root/'vault'),log_dir=str(root/'logs'),ai_core=AICore(provider,[]))
    report={'root':str(root),'commands':[]};target=root/'report.json';print('REPORT='+str(target),flush=True)
    try:
        for command in ['Busque no Segundo Cérebro informações sobre Aetherion',
                        'resuma os trechos disponíveis','fale mais sobre o trecho 5',
                        'Quantas classes tem no Aetherion?', 'Quantas classes tem no Aetéreum?']:
            result=orch.process_command(command)
            row={'command':command,'status':result.status,'answer':result.message}
            report['commands'].append(row);target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(row,ensure_ascii=True),flush=True)
    finally:orch.close()


if __name__=='__main__':main()
