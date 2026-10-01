# Planejamento da V2 — Voz do Therion

**Estado:** planejamento; política conceitual V2.0 aprovada pelo usuário; implementação não autorizada.  
**Registro:** 2026-09-23.  
**Papel deste documento:** preservar o desenho e a pesquisa para continuidade entre chats e agentes. Não substitui `Roadmap.md`, `Estado Atual.md`, `Decisões.md` nem a governança do Segundo Cérebro. Propostas técnicas e recomendações abaixo não são decisões de implementação.

## 1. Objetivo e fronteira arquitetural

Voz será uma camada de entrada e saída do Therion, não um segundo agente. O fluxo-base é:

`microfone → STT → transcrição revisável → envio manual → Therion textual atual → resposta textual → TTS → alto-falante`

O Orchestrator e os mecanismos atuais de permissões, ReadScope, memória, ações, confirmação e auditoria continuam sendo as autoridades. Nenhum adaptador de áudio decide acesso, executa ação diretamente ou amplia autonomia. A V2.1 começa com push-to-talk; transcrição visível/editável; e botão explícito de Enviar. Reconhecer uma frase não equivale a autorizá-la ou executá-la.

O desenho em etapas permite inspecionar o texto antes do envio e substituir STT/TTS sem trocar o núcleo. Home Assistant Assist e as arquiteturas de voz da OpenAI são referências, não modelos a copiar integralmente.

## 2. Política conceitual V2.0 aprovada

O usuário aprovou conceitualmente as dez decisões abaixo, com as ressalvas após a lista:

1. V2.1 local-first e com push-to-talk.
2. Transcrição visível e editável; somente **Enviar** encaminha texto ao Therion.
3. STT cloud pode existir como opção explícita futura, nunca como fallback silencioso.
4. TTS cloud pode existir como opção explícita futura, nunca como fallback silencioso.
5. Conteúdo do Segundo Cérebro fica bloqueado por padrão para TTS cloud.
6. Áudio bruto não deve ser persistido deliberadamente por padrão.
7. Transcrição antes de Enviar é rascunho efêmero e descartável.
8. Depois de Enviar, a transcrição segue o fluxo textual existente, inclusive suas regras reais de memória e auditoria.
9. Confirmações de ações protegidas permanecem no mecanismo atual do Therion.
10. Nenhum provider definitivo será escolhido antes de avaliação na máquina real.

**Ressalvas obrigatórias:** “não guardar áudio” ainda exige verificar se captura/STT usam arquivos temporários ou buffers persistentes. “Transcrição efêmera” vale antes de Enviar; após Enviar, não prometer ausência de registro sem auditar memória e audit log atuais. Cloud permitida no desenho não significa cloud incluída na V2.1. Consentimento para enviar áudio a STT cloud é distinto de consentimento para enviar texto de resposta a TTS cloud. Nenhum desses consentimentos amplia permissões do Therion.

O microfone deve captar apenas durante push-to-talk. Logs específicos de voz devem preferir metadados operacionais mínimos (etapa, duração, provider, erro), sem áudio ou transcrição integral por padrão. A política exata de arquivos temporários, retenção e descarte permanece dependente da auditoria técnica. Cancelar antes de Enviar descarta o rascunho; cancelar depois de Enviar não promete desfazer processamento ou ação já autorizada.

## 3. STT — candidatos e evidência disponível

| Candidato | Evidência documentada | Vantagem provável | Ponto a verificar |
| --- | --- | --- | --- |
| `faster-whisper` | API Python; execução local em CPU/GPU; PyAV; requisitos de GPU específicos. | Menor atrito aparente para um protótipo Python. | Compatibilidade com o Python/Windows do Therion, latência, RAM, precisão PT-BR e comportamento com ruído. |
| `whisper.cpp` | Execução local em Windows/CPU e diferentes backends; exemplo simples de microfone. | Isolamento do runtime Python e possível adequação a CPU. | Integração, instalação, latência e precisão no computador real; o exemplo de streaming não prova experiência conversacional pronta. |
| Vosk | Offline, API de reconhecimento contínuo e modelos de português brasileiro. | Comparador leve, especialmente para comandos restritos. | Qualidade para frases livres e nomes próprios; resultados publicados de corpus não são comparação direta com os demais. |
| OpenAI transcription | API para áudio capturado e alternativa distinta para transcrição ao vivo. | Comparador cloud sem inferência pesada local. | Consentimento anterior ao envio de áudio, rede, custo, retenção aplicável, precisão e latência reais. |

**Recomendação provisória, não decisão:** avaliar primeiro STT local de turno completo após soltar o botão. Comparar `faster-whisper` e `whisper.cpp` na máquina-alvo, com frases em PT-BR que incluam nomes, datas, horários, comandos do Therion, ruído e pausas. Não declarar vencedor com benchmarks de fornecedores ou de outras máquinas. A modalidade realtime/streaming fica para etapa posterior.

## 4. TTS — candidatos e evidência disponível

| Candidato | Evidência documentada | Vantagem provável | Ponto a verificar |
| --- | --- | --- | --- |
| Piper | Motor local/offline, API Python e vozes `pt_BR`. | Texto da resposta permanece local; possível base da V2.2. | Naturalidade, latência, recursos, licenças do motor e de cada voz e compatibilidade com o ambiente. |
| ElevenLabs | Modelos multilíngues com PT-BR, vozes expressivas e streaming. | Candidato opcional para voz de saída mais natural. | Custo/créditos, latência fim a fim, retenção, limites do plano e risco de enviar texto pessoal à nuvem. |
| OpenAI TTS | API e streaming. | Comparador cloud intercambiável. | Qualidade PT-BR na prática; vozes documentadas como otimizadas para inglês; custo e controles de dados aplicáveis. |

**ElevenLabs:** é candidato forte para TTS opcional da V2.2, não dependência nem padrão automático da V2.1. A latência de cerca de 75 ms divulgada para Flash refere-se à inferência do modelo, não ao tempo total até ouvir o áudio. A documentação relata retenção padrão; Zero Retention Mode é restrito a clientes Enterprise selecionados e não pode ser presumido para a conta do usuário. Sua adequação a respostas com conteúdo do Segundo Cérebro depende de decisão específica de privacidade; o bloqueio por padrão já foi aprovado. Interromper reprodução local não desfaz texto enviado ao provider.

**Recomendação provisória, não decisão:** avaliar Piper como base local e ElevenLabs/OpenAI TTS como opções cloud separadas. Comparar por escuta PT-BR, latência real, custo esperado, funcionamento offline, streaming e cancelamento. Nenhum fornecedor foi escolhido.

**Referência adicional para avaliar na V2 — VoiceStudio:** projeto local-first com API de transcrição, opção de texto parcial em streaming e múltiplos motores de STT/TTS. Pode ser comparado como backend isolado na V2.1 (STT) e na V2.2 (TTS), sem substituir a interface, a `VoiceSession` ou a autoridade do Therion. Não há escolha de provider nem autorização de instalação. Antes de um piloto, verificar na máquina real precisão e naturalidade em PT-BR, latência, RAM/VRAM, espaço em disco, temporários/retenção, cancelamento e compatibilidade no Windows. Conferir separadamente a licença AGPL do aplicativo e as licenças dos modelos/pesos utilizados. Não importar o aplicativo inteiro nem presumir que as capacidades anunciadas funcionarão com o hardware disponível.

## 5. VoiceSession efêmera

A `VoiceSession` proposta cuida somente do ciclo de interação por áudio. Estados mínimos sugeridos:

`ociosa → capturando → transcrevendo → aguardando revisão → texto enviado → resposta disponível → falando → concluída`

`cancelada` e `erro` são saídas possíveis dos estados aplicáveis. O desenho deve registrar a identidade do turno e descartar resultados tardios de STT/TTS que pertençam a sessão cancelada ou substituída. A sessão pode controlar dispositivo, início/fim de captura, timeout, rascunho, reprodução e cancelamento, mas nunca guardar autoridade de acesso, decidir ações ou alimentar `allowed_roots`.

- Falha de STT: informar e permitir nova tentativa; não enviar texto vazio/incerto ao Therion.
- Falha de TTS: manter a resposta textual disponível.
- Cancelamento antes de Enviar: parar captura/processamento e descartar rascunho conforme a política de retenção definida.
- Cancelamento após Enviar: não prometer rollback da tarefa ou ação.
- Confirmação de ação: continua no mecanismo atual; transcrição revisada não substitui confirmação específica.
- Push-to-talk inicial evita depender de detecção automática de fim de fala e reduz a necessidade de microfone/alto-falante simultâneos.

VAD, turn detection, streaming, barge-in, wake word e echo cancellation ficam como pontos de extensão futuros. Barge-in deverá separar “parar de falar” de “cancelar trabalho no backend”; não presumir que sejam a mesma coisa. Echo cancellation e tempo de resposta exigem teste em hardware real. Uma arquitetura full-duplex futura só faz sentido mantendo Therion como backend/autorizador.

## 6. Etapas propostas, sem autorização de implementação

1. **V2.0 — política e encaixe:** política conceitual aprovada; verificar retenção, temporários, limites de cloud e pontos de integração por auditoria read-only. Congelar critérios de aceite antes de código.
2. **V2.1 — entrada segura:** push-to-talk → STT local → transcrição visível/editável → Enviar manual → fluxo textual existente; incluir cancelamento e erros básicos. Sem TTS obrigatório.
3. **Marco de observabilidade/segurança:** medir captura, STT, envio, falhas e cancelamento; logs apenas conforme política aprovada. Não inferir qualidade a partir de alegações de fornecedor.
4. **V2.2 — saída falada:** TTS intercambiável, com avaliação local versus cloud e proteção do Segundo Cérebro.
5. **V2.x posteriores:** streaming, VAD/turn detection, barge-in e wake word. A ordem entre eles ainda não está congelada.
6. **Futuro:** voz realtime/full-duplex, preservando o Therion como autoridade sobre contexto, ferramentas e ações.

O `Roadmap.md` atual põe V2 — Voz como próxima prioridade e afirma que a trilha pós-V1 de inteligência externa não altera essa prioridade. Uma conversa posterior levantou a possibilidade de priorizar pesquisa web e escalonamento assistido para GPT antes da voz. **Essa repriorização não foi aprovada nem registrada no Roadmap.** Exige plano read-only e decisão separada do usuário/Gerente Geral. Este documento preserva o planejamento da voz independentemente de sua posição final na sequência.

## 7. Lacunas, riscos e medições

**Evidência documentada:** disponibilidade de APIs, idiomas/vozes anunciados, execução local/cloud, opções de streaming e políticas publicadas nas fontes abaixo. Alegações de desempenho dos fornecedores não são medições do Therion.

**Hipóteses:** `faster-whisper` pode integrar mais facilmente; Piper pode ser suficiente como voz local; ElevenLabs pode justificar o custo; push-to-talk pode oferecer latência aceitável. Nenhuma está validada na máquina-alvo.

**Medir no computador real:** precisão PT-BR em frases representativas, nomes próprios e ruído; RAM/CPU/GPU; tempo entre soltar botão e ver a transcrição; tempo até o primeiro áudio e até terminar de falar; qualidade das vozes; cancelamento; funcionamento offline; custo no volume de uso esperado; compatibilidade de instalação.

**Riscos arquiteturais:** transcrição errada virar comando; resultado tardio alcançar outro turno; retenção involuntária de áudio temporário; vazamento de texto pessoal para TTS cloud; uso de histórico/voz como permissão; fallback silencioso local→cloud; acoplamento da VoiceSession ao Orchestrator; confirmação falada ambígua; dependência de fornecedor/custo. O envio manual e os mecanismos atuais de autorização são fronteiras essenciais, não garantias suficientes sem teste.

## 8. Decisões ainda abertas e próximo passo

Ainda precisam de decisão própria: critérios mensuráveis de aceite, duração máxima de captura e timeouts, semântica exata de cancelamento após Enviar, política final de temporários e retenção, momento/formato do consentimento cloud, possibilidade e limite de enviar respostas comuns a TTS cloud, eventual exceção específica para conteúdo do Segundo Cérebro, provider de cada etapa e posição da V2 em relação à trilha de inteligência externa. Não converter essas lacunas em defaults permissivos.

**Próximo passo recomendado:** auditoria read-only do Therion para localizar entrada textual, UI, cancelamento, memória/auditoria, arquivos temporários e pontos de encaixe de VoiceSession/STT/TTS. Depois apresentar o menor plano de V2.1 ao usuário e ao Gerente Geral. Nenhuma implementação, teste, instalação, Git ou contratação é autorizada por este documento.

## 9. Visão de experiência futura — conversa natural com ações em etapas

**Referência trazida pelo usuário em 2026-09-28:** demonstração em vídeo de um assistente chamado Cosmo. Na transcrição fornecida, o usuário pede por voz a criação de um jogo, solicita abri-lo no navegador, comenta o resultado, pede uma alteração e continua conversando informalmente. O vídeo serve como referência de experiência desejada, não como evidência de latência, autonomia real, qualidade técnica ou funcionamento contínuo sem edição.

**Objetivo para o Therion:** conversar por voz com naturalidade e baixa espera percebida, manter a referência à tarefa em andamento e permitir ajustes após o usuário ver o resultado. A interface deve permanecer responsiva durante o processamento. Nenhum desses objetivos dispensa confirmação, escopo explícito ou os mecanismos existentes de permissão e auditoria.

**Separação de frentes:**

- **Base anterior à voz:** concluir a E1 e tratar o bloqueio da interface durante comandos demorados.
- **V2 — Voz:** entrada e saída faladas, continuidade e evolução gradual da latência percebida, sem criar um segundo agente ou ampliar autoridade.
- **Capacidade futura distinta:** criar, abrir e editar projetos/arquivos em etapas somente dentro de raízes e ações autorizadas, com revisão do resultado e confirmações proporcionais. Não é requisito nem autorização de implementação da V2.1.

**Critério de realidade:** comparar a experiência em tarefas reais no computador do usuário. Saltos na transcrição e possíveis erros de reconhecimento não permitem concluir quanto tempo a demonstração levou nem quais partes foram executadas automaticamente.

## 10. Fontes técnicas consultadas

- [Home Assistant — Assist pipelines](https://developers.home-assistant.io/docs/voice/pipelines/)
- [OpenAI — arquiteturas de voz](https://developers.openai.com/api/docs/guides/voice-agents)
- [whisper.cpp — documentação do projeto](https://github.com/ggml-org/whisper.cpp/blob/master/README.md)
- [faster-whisper — documentação do projeto](https://github.com/SYSTRAN/faster-whisper)
- [Vosk — modelos](https://alphacephei.com/vosk/models)
- [OpenAI — transcrição de áudio](https://developers.openai.com/api/docs/guides/speech-to-text)
- [OpenAI — transcrição ao vivo](https://developers.openai.com/api/docs/guides/realtime-transcription)
- [Piper — projeto e vozes](https://github.com/OHF-Voice/piper1-gpl)
- [Piper — lista de vozes](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md)
- [ElevenLabs — TTS](https://elevenlabs.io/docs/overview/capabilities/text-to-speech)
- [ElevenLabs — latência](https://elevenlabs.io/docs/eleven-api/guides/how-to/best-practices/latency-optimization)
- [ElevenLabs — Zero Retention Mode](https://elevenlabs.io/docs/eleven-api/resources/zero-retention-mode)
- [OpenAI — TTS](https://developers.openai.com/api/docs/guides/text-to-speech)
- [OpenAI — controles de dados da API](https://developers.openai.com/api/docs/guides/your-data)
- [VoiceStudio — repositório](https://github.com/debpalash/VoiceStudio)
- [VoiceStudio — integração e transcrição](https://github.com/debpalash/VoiceStudio/blob/main/docs/speech-platform.md)
- [VoiceStudio — instalação no Windows](https://github.com/debpalash/VoiceStudio/blob/main/docs/install/windows.md)
- [VoiceStudio — licenças](https://github.com/debpalash/VoiceStudio/blob/main/LICENSE-NOTICE.md)

As políticas, disponibilidades, preços e requisitos externos podem mudar; revalidá-los antes de contratar ou implementar.
