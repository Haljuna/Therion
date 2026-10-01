# Ideia futura — Letta e memória persistente do Thérion

**Estado:** referência para estudo futuro; nenhuma integração aprovada.
**Registro:** 2026-09-29.

Marcus trouxe o [Letta](https://github.com/letta-ai/letta) após assistir a um vídeo sobre IA pessoal. O possível valor para o Thérion é memória duradoura entre conversas: preferências estáveis, informações úteis e continuidade controlada, além do contexto da sessão e da leitura atual do Segundo Cérebro. Isso não torna automaticamente o modelo mais inteligente e não resolve a frente atual de transcrição por voz.

Letta não é uma skill pequena para copiar. A plataforma atual inclui memória de agente, runtime de conversas e execução de ferramentas. Por isso, uma integração direta poderia duplicar partes do Orchestrator e criar outro caminho para ações externas. Se algum dia for avaliada, toda ação ainda deverá respeitar as confirmações existentes e a futura proposta de Thérion Guard/Action Broker; memória não concede permissão. Diferenciar explicitamente o armazenamento local do modo cloud, no qual histórico e memórias podem ficar fora do computador.

**Quando retomar:** depois de estabilizar V2.1 e quando houver necessidade concreta de memória entre sessões. Fazer primeiro uma comparação read-only entre (a) capacidades de memória já existentes no Thérion/Segundo Cérebro, (b) uma solução nativa menor e (c) Letta local. Definir quais dados podem ser lembrados, quem aprova/corrige/esquece uma memória, prazo de retenção, exportação, privacidade, latência e impacto nas permissões. Somente então propor um piloto isolado e mensurável, se Letta acrescentar valor real.

**Fora do escopo atual:** instalar Letta, conectar contas, enviar dados à nuvem, substituir o Orchestrator, alterar a memória do Thérion, criar ferramentas ou ampliar autonomia. Esta nota registra uma hipótese, não autoriza implementação nem muda a prioridade da V2.1.

Referências oficiais: [memória no Letta](https://docs.letta.com/configuration/memory), [App Server e armazenamento local/cloud](https://docs.letta.com/self-hosting/app-server).
