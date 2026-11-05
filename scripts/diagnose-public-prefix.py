"""Diagnóstico de metadados do stream local; não salva raciocínio nem áudio."""
import asyncio
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


async def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--last-user-no-think',action='store_true')
    args=parser.parse_args()
    import httpx
    from therion.agent import CancellationToken,TurnBudget
    from therion.agent.context import SYSTEM
    from therion.agent.ollama import OllamaAgentProvider
    stats={'closing_tag_seen':False,'opening_tag_seen':False,'thinking_field_characters':0,
        'content_characters':0,'prefixes':0}
    candidate=[]
    async def observe(response):
        # Buffer somente no diagnóstico: não usar estes tempos como benchmark.
        body=await response.aread()
        for line in body.splitlines():
            if not line:continue
            message=json.loads(line).get('message',{})
            content=message.get('content','')
            stats['closing_tag_seen']|=any(tag in content for tag in ('</think>','</analysis>','</reasoning>'))
            stats['opening_tag_seen']|=any(tag in content for tag in ('<think>','<analysis>','<reasoning>'))
            stats['thinking_field_characters']+=len(message.get('thinking',''))
            stats['content_characters']+=len(content)
        # Tags podem estar divididas entre deltas; verificar o conjunto em memória.
        content=''.join(json.loads(line).get('message',{}).get('content','') for line in body.splitlines() if line)
        stats['closing_tag_seen']|=any(tag in content for tag in ('</think>','</analysis>','</reasoning>'))
        stats['opening_tag_seen']|=any(tag in content for tag in ('<think>','<analysis>','<reasoning>'))
    provider=OllamaAgentProvider('http://127.0.0.1:11435/api/chat','qwen3:4b',protocol='native',think=False,
        client_factory=lambda **kw:httpx.AsyncClient(event_hooks={'response':[observe]},**kw))
    def event(kind,**data):
        if kind=='response_prefix':candidate.append(data['text'])
    try:
        result=await provider.decide([{'role':'system','content':SYSTEM},{'role':'user','content':
            'Repita somente o texto entre aspas: “A cidade fictícia Aurora tem uma biblioteca perto da praça. '
            'O encontro de leitura está previsto para as 14:30. Os participantes podem levar um livro e compartilhar suas ideias. '
            'Esta descrição serve apenas para avaliar a voz do assistente em português.”'+
            ('\n/no_think' if args.last_user_no_think else '')}],[],TurnBudget(output_tokens=4096),CancellationToken(),event)
        stats.update(prefixes=len(candidate),prefix_matches_final=bool(candidate and result.message.startswith(candidate[0])),
            final_characters=len(result.message),usage=provider.usage)
    finally:await provider.aclose()
    print(json.dumps(stats,ensure_ascii=False),flush=True)


if __name__=='__main__':asyncio.run(main())
