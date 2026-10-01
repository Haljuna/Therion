# Ideia futura — Thérion Guard

**Estado:** proposta arquitetural para estudo; não aprovada para implementação.
**Registro:** 2026-09-29.

Marcus propôs uma camada independente entre o raciocínio do Thérion e qualquer ação real. O usuário continua sendo a autoridade sobre a política; o modelo não concede permissões a si próprio.

Fluxo pretendido: **Core propõe ação estruturada → Guard decide permitir, pedir confirmação ou bloquear → confirmação humana específica, quando exigida → Action Broker revalida e executa → auditoria registra decisão e resultado.** O Guard deve aplicar regras determinísticas, com bloqueio por padrão para ação desconhecida; um segundo modelo não deve ser autoridade final. Um simples “sim” não deve transformar ação bloqueada em permitida: uma exceção requer mudança de política separada e explícita.

**Base atual observada:** há validação de ações, allowlist de aplicativos, confirmação para abrir aplicativo, escopo de leitura e log de tarefas. Porém calendário, aliases, leitura e abertura de aplicativo usam verificações distribuídas, sem um ponto obrigatório e único de decisão imediatamente antes de toda execução. Uma centralização no mesmo processo reduziria erros de fluxo, mas não impediria código malicioso com os mesmos privilégios de contorná-la. Para uma fronteira forte, estudar Broker em processo separado, credenciais fora do Core e permissões do sistema operacional.

**Ordem de investigação sugerida:** (1) inventariar todos os caminhos de leitura, escrita, rede, processo e credenciais, incluindo desktop e CLI; (2) definir matriz de risco e contrato de `ActionRequest`/`Decision`; (3) centralizar gradualmente uma ação por vez, com confirmação vinculada à operação e argumentos exatos, uso único e revalidação na execução; (4) acrescentar auditoria da política aplicada e testes de contorno; (5) antes de ampliar para arquivos com escrita, navegador, Gmail ou terminal, prototipar isolamento de processo/sandbox no Windows. OPA, Cedar e OpenShell são referências de arquitetura, não dependências aprovadas. OpenShell não deve ser instalado por inferência.

**Riscos a estudar:** prompt injection em notas/páginas/e-mails, vazamento após leitura autorizada, caminhos com junctions e troca entre autorização e uso, confirmação reaproveitada ou alterada, fadiga de confirmação, ações em lote, falha da auditoria, credenciais expostas, transcrição de voz incorreta e caminhos alternativos que evitem o Guard.

**Fora do escopo atual:** implementação, mudança de permissões, acesso amplo a ferramentas, instalação de plataformas de segurança, alteração da prioridade da V2 e qualquer commit/push. Antes de retomar, conferir o código e o estado do projeto; esta nota é contexto, não autorização.

Referências para estudo: [OWASP — Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/), [NIST SP 800-207 — Zero Trust](https://csrc.nist.gov/pubs/sp/800/207/final), [NVIDIA OpenShell — arquitetura](https://docs.nvidia.com/openshell/latest/about/architecture), [Microsoft — AppContainer](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation).
