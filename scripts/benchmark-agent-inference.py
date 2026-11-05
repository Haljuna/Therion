"""Dois pedidos idênticos, sem ferramentas: modelo descarregado e residente.

Somente servidor experimental já criado pelo ensaio com voz. Não registra
conteúdo gerado nem campos de raciocínio do modelo.
"""
import argparse
import json
from pathlib import Path
import sys
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--voice-profile',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    if args.output.exists():raise ValueError('Saída já existe.')
    profile=json.loads(args.voice_profile.read_text(encoding='utf-8'))
    if profile['environment'].get('OLLAMA_HOST')!='127.0.0.1:11436':raise ValueError('Servidor não corresponde ao ensaio isolado.')
    if time.time()>profile['soak_started']+profile['minimum_seconds']-300:raise ValueError('Janela de vida do servidor insuficiente para esta medição.')
    state=json.loads(args.voice_profile.with_name(args.voice_profile.name.replace('.voice-profile.json','.state.json')).read_text(encoding='utf-8'))
    if state['status']!='completed':raise ValueError('A matriz ainda está ativa; não concorrer com sua inferência.')
    from agent_resources import sample
    from therion.agent.ollama import final_text
    import httpx
    model='hf.co/pramodlohra/Qween3_4B_thinking_finetune:Q4_K_M';endpoint='http://127.0.0.1:11436/api/'
    report={'model':model,'scope':'Mesmo pedido com modelo inicialmente descarregado e depois residente; cache do SO não foi limpo. Voz sintética residente em outro processo. Não é avaliação funcional de ferramentas.','context':8192,'output_tokens':256,'think':False,'runs':[]}
    with httpx.Client(trust_env=False,follow_redirects=False,timeout=90) as client:
        if client.get(endpoint+'ps').json().get('models'):raise ValueError('Há modelo carregado; não alterei seu estado.')
        resources=sample()
        if resources['commit_available_bytes']<4_644_766_060 or resources['ram_available_bytes']<1536*1024**2:raise ValueError('Pesos e reserva não cabem na margem atual.')
        try:
            for kind in ('cold','warm'):
                before=sample();started=time.perf_counter()
                reply=client.post(endpoint+'chat',json={'model':model,'stream':False,'think':False,'messages':[{'role':'user','content':'Responda apenas PRONTO, sem explicação.'}],
                    'options':{'num_ctx':8192,'num_predict':256,'temperature':0}})
                reply.raise_for_status();data=reply.json()
                try:correct=final_text(data.get('message',{}).get('content','')).strip().rstrip('.').casefold()=='pronto'
                except ValueError:correct=False
                report['runs'].append({'kind':kind,'elapsed_seconds':time.perf_counter()-started,'expected_final':correct,
                    'usage':{key:data.get(key) for key in ('load_duration','total_duration','prompt_eval_duration','eval_duration','prompt_eval_count','eval_count')},'resources_before':before,'resources_after':sample()})
        finally:client.post(endpoint+'generate',json={'model':model,'keep_alive':0},timeout=15)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps([{'kind':row['kind'],'elapsed_seconds':row['elapsed_seconds'],'load_seconds':row['usage']['load_duration']/1e9,'expected_final':row['expected_final']} for row in report['runs']]),flush=True)


if __name__=='__main__':main()
