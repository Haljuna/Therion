from therion.agent.presentation import speech_text


def test_speech_omits_generated_source_footer_and_preserves_numbers():
    original='Às 14:30, o valor é R$ 12,50.'
    assert speech_text('completed',original+'\n\nFontes consultadas:\nnote:1 — C:/fixture.md')==original


def test_partial_and_uncertain_remain_explicit_in_voice():
    assert speech_text('partial','Encontrei parte dos dados.').startswith('Concluí apenas parte')
    assert speech_text('partial','Não consegui preparar a ação.') == 'Não consegui preparar a ação.'
    assert 'Não consegui confirmar' in speech_text('uncertain','Texto longo de um resultado incerto.')
    assert 'antes de repetir' in speech_text('uncertain','')


def test_long_response_does_not_cut_sentence_or_exceed_voice_limit():
    text='Primeira parte pública.\n\n'+'x'*3000
    spoken=speech_text('completed',text)
    assert 'Primeira parte pública.' in spoken and 'xxx' not in spoken and len(spoken)<1800
