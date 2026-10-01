# Referência futura — qualidade de código

**Estado:** pesquisa futura; nenhuma ferramenta aprovada para instalação ou integração.
**Registro:** 2026-09-28.

Catálogo encontrado pelo usuário: [GitHub — code-quality](https://github.com/topics/code-quality). A página reúne projetos diferentes; popularidade não demonstra adequação ao Therion.

Repositórios para avaliar somente quando houver uma lacuna concreta:

- [Ruff](https://github.com/astral-sh/ruff): primeira opção para um piloto de checagem estática de código Python, inicialmente somente leitura e sem correções automáticas. Conferir antes o que o projeto já utiliza.
- [Pyrefly](https://github.com/facebook/pyrefly): verificação de tipos em Python; considerar se erros de tipos ou contratos entre módulos se tornarem recorrentes. Não introduzir uma nova exigência para todo o projeto sem medir o impacto.
- [jscpd](https://github.com/kucherenko/jscpd): detecção de código duplicado; considerar apenas se duplicações reais estiverem dificultando manutenção ou revisão. Não transformar achados em refatoração automática.

**Regra para reabrir:** identificar problema repetido e mensurável, verificar o repositório original, licença, dependências e manutenção atual, comparar com as checagens existentes e propor um piloto pequeno com resultado verificável. Testes funcionais e revisão humana de escopo continuam necessários.

**Fora do escopo atual:** instalar ferramentas, alterar configurações ou código, criar automações de revisão, reformar arquivos em massa, mudar o roadmap ou fazer checkpoint.
