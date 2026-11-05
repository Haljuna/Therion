"""Resumo do usuário deve ser breve e não assumir a identidade do perfil."""
import json
from unittest.mock import patch

from tests.test_personal_context_flow import case
from tests.test_agent_voice_calendar_search import enable,send
from therion.core.ai_provider_ollama import OllamaProvider
from therion.core.personal_context import personal_summary_style,checked_personal_summary


GOOD='Você cursa Engenharia Biomédica e já concluiu o técnico em Instrumentação. Seu objetivo é construir um sensor de teste.'


def test_first_person_is_repaired_before_display_and_speech(case):
    host,provider,_,profile=case
    enable(host);host.voice_conversation=True
    before=profile.read_bytes()
    provider.describe_result.side_effect=['Sou Luana. Concluí o técnico em Instrumentação.',GOOD]
    result=send(host,'Resume quem sou eu.')
    assert result.status=='success'
    assert result.speech_message==GOOD and result.message.startswith(GOOD)
    assert 'Sou Luana' not in result.message
    assert provider.describe_result.call_count==2
    assert provider.describe_result.call_args.args[2]['personal_summary_repair'] is True
    assert profile.read_bytes()==before
    provider.generate.assert_not_called()


def test_repeated_identity_error_is_not_spoken_or_recorded(case):
    host,provider,_,_=case
    enable(host)
    provider.describe_result.return_value='Sou Luana. Meu curso é Engenharia Biomédica.'
    result=send(host,'Resume quem sou eu.')
    assert 'Não consegui compor um resumo breve' in result.speech_message
    assert 'Sou Luana' not in result.message
    assert all('Sou Luana' not in turn.text for turn in host.memory.turns)
    assert provider.describe_result.call_count==2


def test_long_summary_keeps_only_complete_sentences_within_budget(case):
    host,provider,_,_=case
    enable(host)
    provider.describe_result.return_value=GOOD+' Você organiza estudos. Você trabalha em projetos. Você também tem interesses diversos.'
    result=send(host,'Resume quem sou eu.')
    assert len(result.speech_message.split())<=60
    assert result.speech_message.count('.')<=3
    assert 'interesses diversos' not in result.speech_message
    assert provider.describe_result.call_count==1


def test_summary_repair_rechecks_permission(case):
    host,provider,_,_=case
    enable(host)
    def revoke(*args):
        host.second_brain.allowed_roots=[]
        return 'Sou Luana.'
    provider.describe_result.side_effect=revoke
    result=send(host,'Resume quem sou eu.')
    assert result.status=='cancelled'
    assert 'Sou Luana' not in result.message
    assert provider.describe_result.call_count==1


def test_profile_description_prompt_has_no_first_person_instruction():
    provider=OllamaProvider()
    evidence={'kind':'personal_context','purpose':'personal_summary','notes':[],
              'response_style':personal_summary_style('Resume quem sou eu.')}
    with patch.object(provider,'_send_request',return_value=json.dumps({'message':GOOD})) as call:
        assert provider.describe_result('Resume quem sou eu.',evidence,{})==GOOD
    payload=call.call_args.args[0]
    system=payload['messages'][0]['content']
    assert 'Responda naturalmente em primeira pessoa' not in system
    assert '3 frases e 60 palavras' in system
    assert payload['think'] is False
    assert payload['options']['num_predict']==280


def test_detailed_summary_has_separate_budget():
    brief=personal_summary_style('Resume quem sou eu.')
    detailed=personal_summary_style('Faça um resumo detalhado sobre mim.')
    assert detailed['max_words']>brief['max_words']
    assert checked_personal_summary('Sou uma estudante.',brief) is None
