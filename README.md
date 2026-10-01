# Therion

O Therion é um assistente pessoal de IA para Windows, desenvolvido com foco em funcionamento local, controle explícito das ações e integração gradual com ferramentas do usuário. O projeto está em desenvolvimento e ainda não é um produto pronto para uso geral.

## O que funciona hoje

- Interface desktop em PySide6, com histórico de conversa, ícone na bandeja e processamento sem bloquear a janela; há também uma interface de linha de comando.
- Conversa e classificação de pedidos com um modelo local via Ollama, quando a IA está habilitada na configuração.
- Abertura controlada do Obsidian após confirmação. O modelo não recebe acesso livre ao terminal nem permissão para abrir qualquer aplicativo.
- Busca textual em notas do Segundo Cérebro, limitada às raízes de leitura autorizadas.
- Consulta ao Google Calendar e criação de eventos mediante confirmação, quando a integração está configurada.
- Criação e recuperação de planos de tamanho normal durante a sessão. Planos muito extensos ainda são uma limitação conhecida.

A entrada por voz (V2.1) está em desenvolvimento. Existe uma fundação para carregar um modelo local, mas **a voz ainda não está integrada ao fluxo principal do Therion**. O piloto de transcrição é separado; ele não deve ser confundido com uma funcionalidade pronta do aplicativo.

## Princípios de segurança

O Therion separa interpretação de pedidos, verificação de permissões, confirmação e execução. Ações com efeito externo passam por regras restritas e, quando necessário, por confirmação do usuário. Reconhecer ou transcrever uma frase não equivale a autorizar uma ação. O projeto não oferece execução arbitrária de comandos por solicitação do modelo.

O funcionamento local é a preferência para a IA e a futura voz. Integrações externas, como o Google Calendar, exigem configuração própria. Não coloque credenciais, tokens, arquivos de configuração pessoais ou registros de conversa no Git.

## Início rápido no Windows

Na pasta do projeto, com Python disponível:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m therion.interface.desktop
```

Para abrir sem janela de terminal, depois de preparar o ambiente:

```powershell
.\.venv\Scripts\pythonw.exe -m therion.interface.desktop
```

A interface de linha de comando pode ser iniciada com:

```powershell
.\.venv\Scripts\python.exe -m therion.interface.cli
```

O arquivo de configuração local fica em `%APPDATA%\Therion\config.json`. Por padrão, a IA, o calendário e as ações reais ficam desabilitados; cada integração precisa ser configurada e testada separadamente. Para usar a IA local, também é necessário instalar e executar o Ollama com um modelo compatível. A instalação das dependências Python não baixa automaticamente o modelo de voz.

## Organização do projeto

| Diretório | Responsabilidade |
| --- | --- |
| `therion/core/` | Interpretação, orquestração e planos |
| `therion/governance/` e `therion/actions/` | Permissões, confirmação e execução controlada |
| `therion/interface/` | Aplicação desktop e CLI |
| `therion/context/` e `therion/memory/` | Leitura autorizada e contexto de sessão |
| `therion/calendar/` | Integração com calendário |
| `therion/voice/` | Fundação da futura entrada por voz |
| `tests/` | Testes automatizados |

O estado de implementação e as decisões de produto são acompanhados em `Estado Atual.md` e `Roadmap.md`. Esses documentos podem conter detalhes internos; revise-os antes de publicar o repositório.

## Estado do projeto

O desenvolvimento é incremental. Estão pendentes, entre outros pontos, a integração segura da voz, a investigação de possíveis picos de memória no aplicativo e o tratamento de planos muito extensos. Nenhuma dessas frentes deve ser considerada concluída apenas por aparecer no roteiro.

Ainda não há um arquivo `LICENSE` neste repositório. Antes de uma publicação pública ou de aceitar contribuições externas, é necessário definir e registrar a licença do projeto.
