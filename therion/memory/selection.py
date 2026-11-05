"""Filtro conservador de utilidade; não comprova verdade ou sensibilidade."""
import re
from therion.context.language import control


def useful_selection(row):
    evidence = control(row['evidence'])
    summary = control(row['summary'])
    # Um rótulo escolhido pelo modelo não transforma uma observação em procedimento.
    if re.search(r'\b(?:ignore as regras|autorizacao permanente|execute uma acao externa)\b', evidence):
        return False
    actions = r'\b(?:valid\w*|verifi\w*|confir\w*|compar\w*|escrev\w*|public\w*|revalid\w*|teste\w*|testar|preserv\w*|cance\w*|revis\w*|consulte|consultar)\b'
    if row['kind'] == 'procedimento':
        return bool(re.search(actions, evidence) and re.search(actions, summary))
    if row['kind'] == 'limitação':
        # Remover orações que negam a ocorrência: mencionar "falha" não é evidência de falha.
        positive = ' '.join(sentence for sentence in re.split(r'[.!?;]', evidence)
                            if not re.search(r'\b(?:nao houve|sem ocorrencia|nenhuma falha|nao ocorreu)\b', sentence))
        return bool(re.search(r'\b(?:falh\w*|limit\w*|indispon\w*|exced\w*|desconhecid\w*|nao confirma\w*|nao comprov\w*)\b', positive)
                    and re.search(r'\b(?:falh\w*|limit\w*|desconhecid\w*|nao|incert\w*)\b', summary))
    # Hipóteses e sugestões precisam indicar ação ou consequência concreta na fonte.
    return bool(re.search(actions, evidence) and re.search(actions, summary))
