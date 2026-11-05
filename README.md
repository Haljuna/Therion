# Therion

O Therion é um assistente pessoal de IA para Windows, em português, que roda localmente: interface desktop, conversa por voz e um modelo de linguagem local pelo Ollama. O projeto é pessoal e está em desenvolvimento; não é um produto pronto para uso geral.

## O que funciona hoje

- **Interface desktop** em PySide6, com ícone na bandeja, tela de carregamento animada e uma cena com orbe em OpenGL (com alternativa estática). Há também uma interface de linha de comando.
- **Conversa por voz**: transcrição local (faster-whisper), detecção de fim de fala e resposta falada com Kokoro, Edge TTS ou um servidor de voz local. O microfone fica bloqueado enquanto o Therion fala.
- **IA local** via Ollama, para conversar e classificar pedidos. O código revalida tudo o que o modelo propõe.
- **Agente com ferramentas** (opcional): lê e-mails do Gmail, prepara rascunhos, consulta a agenda, busca na web e lê notas, sempre com propostas que exigem confirmação antes de qualquer efeito.
- **Google Calendar**: consulta e criação de eventos com confirmação, inclusive por voz.
- **Notas do Obsidian**: busca e leitura limitadas às pastas autorizadas.
- **Memória supervisionada**: o que o Therion guarda de uma conversa passa por revisão antes de virar conhecimento.
- **Autonomia controlada**: abrir e fechar aplicativos e rodar rotinas só com permissões concedidas por item, verificadas por caminho e hash do executável.

## Princípios de segurança

O Therion separa interpretação, permissão, confirmação e execução. O modelo só classifica ou prepara; quem decide é o código. Ações com efeito externo (enviar, salvar, criar, abrir) passam por confirmação humana, e reconhecer uma frase não equivale a autorizar uma ação. O projeto não executa comandos arbitrários a pedido do modelo, e a automação de janelas recusa terminais e diálogos de credencial.

Credenciais, tokens, configuração pessoal e registros de conversa ficam fora do repositório, no AppData do usuário.

## Início rápido no Windows

Requer Python 3.14 e, para a IA, o [Ollama](https://ollama.com) com um modelo compatível.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m therion.interface.desktop
```

Dependências opcionais: `requirements-agent.txt` (agente e ferramentas), `requirements-kokoro.txt` e `requirements-edge-tts.txt` (vozes).

Outras formas de abrir:

```powershell
.\.venv\Scripts\pythonw.exe -m therion.interface.launcher   # com tela de carregamento, sem terminal
.\.venv\Scripts\python.exe -m therion.interface.cli         # linha de comando
```

A configuração local fica em `%APPDATA%\Therion\config.json`. Por padrão, a IA, o calendário, o agente e as ações reais ficam desligados; cada integração precisa ser configurada separadamente (há scripts em `scripts/configure-*.py` e `scripts/connect-calendar.py`).

## Testes

```powershell
.\.venv\Scripts\python.exe scripts\test-v4.py tests -q
```

O `test-v4.py` roda o pytest com dados temporários isolados, sem tocar na configuração real.

## Organização do projeto

| Diretório | Responsabilidade |
| --- | --- |
| `therion/core/` | Orquestrador, interpretação de pedidos, provedor Ollama e workflows |
| `therion/interface/` | Aplicação desktop, painéis, orbe e CLI |
| `therion/voice/` | Captura, transcrição, fim de fala e síntese de voz |
| `therion/agent/` e `therion/integrations/` | Agente com ferramentas e seus back-ends (Gmail, navegador, desktop, MCP) |
| `therion/memory/` e `therion/context/` | Memória supervisionada, conhecimento e leitura autorizada de notas |
| `therion/governance/`, `therion/actions/`, `therion/autonomy/` | Permissões, confirmação e execução controlada |
| `therion/calendar/` | Google Calendar |
| `scripts/` | Iniciadores, servidores de voz, benchmarks e avaliações |
| `tests/` | Testes automatizados |

O mapa completo do código está em [docs/CODEBASE_MAP.md](docs/CODEBASE_MAP.md).

## Licença

[MIT](LICENSE) © 2026 Haljuna.
