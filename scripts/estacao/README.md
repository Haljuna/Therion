# Estação Therion

Um tablet antigo vira a estação do Therion na mesa: uma tela de terminal com o anel de onda, o status do PC (RAM, VRAM, Ollama, voz, transcrição, Therion) e 4 botões que religam as peças do Therion. O porteiro (`porteiro.py`) roda no PC, sempre ligado, e serve a página para o tablet pela rede de casa.

## Instalação

1. **Reserve o IP do tablet** no roteador (DHCP fixo), para ele não mudar.
2. **Crie** `%LOCALAPPDATA%\Therion\estacao\config.json`:

   ```json
   {"client_ip": "192.168.0.X", "bind": "192.168.0.Y", "port": 3904}
   ```

   `client_ip` é o IP do tablet; `bind` é o IP deste PC na rede de casa.
3. **Libere a porta no firewall** (só para o tablet, só na rede privada). Rode você mesmo, num PowerShell como administrador:

   ```powershell
   New-NetFirewallRule -DisplayName 'Therion Estacao' -Direction Inbound -Protocol TCP -LocalPort 3904 -RemoteAddress <IP do tablet> -Profile Private -Action Allow
   ```

4. **Ligue o porteiro junto com o Windows:** `powershell -File scripts\estacao\Install-Estacao.ps1` (para tirar: `-Remover`).
5. **Pareie o tablet:** rode `.venv\Scripts\python.exe scripts\estacao\porteiro.py --parear`, abra `http://<IP do PC>:3904/` no tablet e digite o código (vale por 5 minutos).
6. **No tablet:** em Configurações → Tela, tempo limite em "Nunca", e deixe a página aberta (ou use o modo estação, abaixo).

## Botões

| Botão | O que faz |
|---|---|
| `[1] LIGAR THERION` | roda `Launch-Therion.ps1` (se já estiver aberto, só avisa) |
| `[2] SUBIR OLLAMA` | roda `start-local-ollama.ps1` |
| `[3] REINICIAR OLLAMA` | toque duplo; encerra só o Ollama da porta 11435 e sobe de novo |
| `[4] RELIGAR VOZ` | toque duplo; roda `VoiceStartup.ps1` |

A saída da última ação fica em `%LOCALAPPDATA%\Therion\estacao\acoes.log` e `acoes.err`.

## Conferência no tablet

- [ ] A página abre e o pareamento funciona.
- [ ] O anel anima sem engasgar, deitado e em pé.
- [ ] Derrubar o Ollama muda o status para `OLLAMA caiu`.
- [ ] O botão 3, com toque duplo, religa o Ollama.
- [ ] Parar o porteiro mostra `PORTEIRO SEM RESPOSTA`, e religar volta sozinho.
