from therion.agent.gmail_presentation import format_message,readable_body,sender_name
from therion.agent.presentation import speech_text


def test_newsletter_preserves_information_without_urls_images_or_repeated_title():
    source='''<https://social.example.test/>

Boletim de teste
<https://example.test/boletim>
[image: capa.jpg]
Hospital Universitário

O estudo apresenta os resultados
dos cenários preliminares. Saiba mais.
<https://example.test/boletim#N1>
------------------------------
► Política de autoavaliação e
planejamento
------------------------------
► Novo regimento para acessibilidade

Aviso: Enviar pedidos até 10h pela plataforma ATEND+.
Coordenação de Projeto: Pessoa fictícia
'''
    original=source
    result=format_message({'subject':'Boletim de teste','from':'"Equipe de Comunicação" <fixture@example.test>'},source)
    assert result.count('Boletim de teste')==1
    assert 'De: Equipe de Comunicação' in result
    assert 'O estudo apresenta os resultados dos cenários preliminares. Saiba mais.' in result
    assert '• Política de autoavaliação e planejamento' in result
    assert '• Novo regimento para acessibilidade' in result
    assert 'até 10h pela plataforma ATEND+' in result
    assert 'Coordenação de Projeto: Pessoa fictícia' in result
    assert all(noise not in result for noise in ('https://','[image:','-----','fixture@example.test'))
    assert source==original


def test_deadlines_amounts_negation_and_written_contacts_are_preserved():
    body='Não confirme ainda.\n\nPague R$ 12,50 até 22/10 às 14:30.\n\nContato: fixture@example.test'
    assert readable_body(body)==body


def test_named_link_keeps_label_and_image_only_mail_is_explicit():
    assert readable_body('Confira [Edital de estágio](https://example.test/edital).')=='Confira Edital de estágio.'
    assert 'não contém texto legível' in readable_body('<https://example.test/>\n[image: capa.png]')


def test_sender_without_display_name_keeps_address():
    assert sender_name('fixture@example.test')=='fixture@example.test'


def test_voice_omits_gmail_identifiers_but_keeps_numbers_and_content():
    message='Assunto: Aula\n\nComeça às 19:00.\n\n[gmail:abc123]\n\nFontes consultadas:\ngmail:abc123 — https://mail.google.com/'
    spoken=speech_text('success',message)
    assert '19:00' in spoken and 'Começa' in spoken
    assert all(noise not in spoken for noise in ('gmail:','abc123','https://','Fontes consultadas'))
