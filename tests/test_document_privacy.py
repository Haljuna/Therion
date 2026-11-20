"""Leitura ampla de documentos, sem pastas de sistema nem arquivos pessoais."""
import pytest

from therion.integrations.documents import DocumentAdapter


@pytest.mark.parametrize('relative',[
    'AppData/Local/notas.txt', '.ssh/config.md', '.claude/projeto.md', 'Cookies/x.txt',
    'Documentos/senhas.txt', 'Documentos/Minhas Senhas.docx', 'F/Comprovante_-_123.pdf',
    'F/Daily Statement 2296329.pdf', 'F/extrato maio.pdf', 'F/CI 555.docx', 'F/CPF.pdf',
    'F/fatura cartao.pdf', 'F/passwords.csv'])
def test_bloqueia_pastas_de_sistema_e_arquivos_pessoais(tmp_path,relative):
    target=tmp_path/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('x',encoding='utf-8')
    with pytest.raises(ValueError,match='pessoal'):DocumentAdapter([tmp_path],[tmp_path]).read(target)


@pytest.mark.parametrize('relative',['Documentos/Currículo.md','Faculdade/Circuitos.md',
    'notas/aprendizado de citações.txt','projeto/README.md'])
def test_documentos_comuns_continuam_legiveis(tmp_path,relative):
    target=tmp_path/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('conteúdo',encoding='utf-8')
    assert 'conteúdo' in str(DocumentAdapter([tmp_path],[tmp_path]).read(target)['sections'])


def test_raiz_escolhida_dentro_de_appdata_continua_valendo(tmp_path):
    # O bloqueio olha só o caminho abaixo da raiz autorizada.
    root=tmp_path/'AppData'/'Therion';root.mkdir(parents=True);target=root/'nota.md';target.write_text('ok',encoding='utf-8')
    assert DocumentAdapter([root],[root]).read(target)['sections']
