from unittest.mock import patch
import json
from therion.core.ai_provider_ollama import OllamaProvider

CONTENT = json.dumps({'type':'chat','message':'Olá!','intent':None,'arguments':{}})


def test_fast_mode_is_scoped_to_voice_and_preserves_structured_validation():
    provider = OllamaProvider(model='hf.co/pramodlohra/Qween3_4B_thinking_finetune:Q4_K_M',think=True)
    with patch.object(provider,'_send_request',return_value=CONTENT) as send:
        response=provider.generate('olá',{'voice_conversation':True},[])
        payload=send.call_args.args[0]
        assert payload['think'] is False
        assert payload['keep_alive']=='5m'
        assert payload['options']['num_ctx']==8192
        assert response.type=='chat'
        provider.generate('olá',{},[])
        payload=send.call_args.args[0]
        assert payload['think'] is True
        assert 'keep_alive' not in payload


def test_warmup_does_not_add_a_fake_turn():
    provider=OllamaProvider(think=True)
    with patch.object(provider,'_send_request',return_value='') as send:
        provider.warmup()
        payload=send.call_args.args[0]
        assert payload['messages']==[]
        assert 'format' not in payload
