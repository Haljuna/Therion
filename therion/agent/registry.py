"""Registro com validação estrita e autorização reavaliada por chamada."""
import math
import re
from .contracts import AgentError, ToolResult,ToolSpec


def validate(value, schema, path='arguments'):
    kind = schema.get('type')
    checks = {'object': lambda: isinstance(value, dict), 'array': lambda: isinstance(value, list),
              'string': lambda: isinstance(value, str), 'integer': lambda: type(value) is int,
              'number': lambda: type(value) in (int, float) and math.isfinite(value),
              'boolean': lambda: type(value) is bool, 'null': lambda: value is None}
    if kind not in checks or not checks[kind]():
        raise AgentError(f'{path}: tipo inválido; esperado {kind}.')
    if 'enum' in schema and value not in schema['enum']:
        raise AgentError(f'{path}: valor não permitido; opções: {schema["enum"]}.')
    if kind == 'object':
        properties = schema.get('properties', {})
        missing=set(schema.get('required', ())) - set(value)
        unknown=set(value) - set(properties)
        if missing or unknown:
            problems=[]
            if missing:problems.append('campos obrigatórios ausentes: '+', '.join(sorted(missing)))
            if unknown:problems.append('campos desconhecidos; permitidos: '+', '.join(properties))
            raise AgentError(path+': '+'; '.join(problems)+'.')
        for key, item in value.items():
            validate(item, properties[key], path+'.'+key)
    if kind == 'array':
        if len(value) > schema.get('maxItems', 100):
            raise AgentError('Lista acima do limite.')
        for item in value:
            validate(item, schema['items'], path+'[]')
    if kind in {'integer','number'} and (value<schema.get('minimum',float('-inf')) or value>schema.get('maximum',float('inf'))):
        raise AgentError(f'{path}: número fora do intervalo permitido [{schema.get("minimum", "sem mínimo")}, {schema.get("maximum", "sem máximo")}].')
    if kind == 'string' and not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 4000):
        raise AgentError(f'{path}: comprimento fora do limite [{schema.get("minLength", 0)}, {schema.get("maxLength", 4000)}].')
    if kind in {'integer', 'number'} and not schema.get('minimum', -math.inf) <= value <= schema.get('maximum', math.inf):
        raise AgentError('Número fora do limite.')


def object_schema(**properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


TEXT = dict(type='string', minLength=1, maxLength=1000)


def initial_tools(command):
    """Schemas pertinentes ao pedido humano; não altera autorização alguma."""
    from therion.context.language import control
    text=control(command)
    from therion.skills.ecc import explicit_ecc_request, technical_ecc_request
    if explicit_ecc_request(text):return {'ecc_catalog','ecc_read'}
    if re.search(r'\b(?:cybersecurity|ciberseguranca|ciberseguridade|cyberseguranca|auditoria de seguranca|skills? de seguranca)\b',text):
        return {'cybersecurity_catalog','cybersecurity_read'}
    if re.search(r'\bgraphify\b',text):return {'graphify_skill','graphify_prepare_build','graphify_query'}
    if re.fullmatch(r'(?:(?:me )?(?:conta|conte) (?:uma )?(?:historia|piada)(?: (?:curta|breve))?|'
                    r'(?:bom dia|boa tarde|boa noite|ola|oi)(?:,? (?:therion|terion|eterion|senhor))?|'
                    r'(?:fala|e ai)(?:,? (?:therion|terion|eterion))?(?:,? beleza)?)',text):
        return set()
    if re.search(r'\b(?:historico|conversas? anterior(?:es)?|(?:ultima|outra) conversa|sessao anterior|decidimos|combinamos|falamos)\b',text):
        return {'search_history','search_session','search_memory'}
    if re.search(r'\b(?:e[- ]?mails?|gmail|rascunhos?|threads?)\b',text):
        if not re.search(r'\b(?:envi\w*|mand\w*|respond\w*|respost\w*|rascunh\w*|escrev\w*|redij\w*|organiz\w*|arquiv\w*|rotul\w*|marqu\w*|apagu\w*|exclu\w*)\b',text):
            return {'gmail_search','gmail_message_headers'}
        return {'gmail_search','gmail_thread','gmail_prepare_draft','gmail_prepare_send','prepare_task','list_inbox'}
    if technical_ecc_request(text):return {'ecc_catalog','ecc_read'}
    if re.search(r'\b(?:pdf|docx|xlsx|csv|documentos?|arquivos?)\b',text):
        return {'document_read','document_prepare_write','search_notes','read_source','web_search','web_read_source'}
    if re.search(r'\b(?:pesquise|pesquisar|pesquisa|web|internet)\b',text):
        return {'web_search','web_read_source','search_notes','read_source'}
    if re.search(r'\b(?:site|pagina|navegador)\b',text):
        return {'browser_open','browser_read','browser_prepare_action','web_search','web_read_source'}
    if re.search(r'\b(?:rotina|rotinas)\b',text):return {'routine_list','routine_prepare_run','operation_receipts'}
    if re.search(r'\b(?:procedimento|procedimentos|skills?)\b',text):return {'procedure_index','procedure_read','search_memory'}
    return {'search_notes','read_source','search_memory','calendar_day','prepare_existing_action'}


class ToolRegistry:
    def __init__(self, *, control_tools=True):
        self._tools = {}
        self.advertised = None
        async def ask(arguments,token):
            token.check()
            return ToolResult('awaiting_clarification',message=arguments['question'])
        if control_tools:
            self.register(ToolSpec('ask_user','Pedir dado que falta e aguardar resposta humana. Não confirma operações nem concede permissões.',
                object_schema(question=dict(type='string',minLength=1,maxLength=2000)),ask,effect='prepare',authorize=lambda args:True))

    def register(self, spec):
        if spec.name in self._tools or spec.effect not in {'read', 'prepare', 'write', 'external'}:
            raise AgentError('Registro duplicado ou efeito inválido.')
        self._tools[spec.name] = spec

    def schemas(self):
        return [spec.schema() for spec in self._tools.values() if self._available(spec)
                and (self.advertised is None or spec.name in self.advertised)]

    @staticmethod
    def _available(spec):
        try:
            return spec.available() is True
        except Exception:
            return False

    def prepare(self, call):
        spec = self._tools.get(call.name)
        if spec is None:
            raise AgentError('Ferramenta fora do registro.')
        if self.advertised is not None and call.name not in self.advertised:
            raise AgentError('Consulte o catálogo e carregue a ferramenta antes de usá-la.')
        validate(call.arguments, spec.argument_schema(), call.name+'.arguments')
        if not self._available(spec):
            return spec, ToolResult('unavailable', message='Integração indisponível; não equivale a resultado vazio.')
        if spec.authorize(call.arguments) is not True:
            return spec, ToolResult('blocked', message='Operação fora do escopo autorizado.')
        return spec, None

    def enable_discovery(self, initial):
        from .contracts import ToolSpec
        base=set(initial)|{'tool_catalog','load_tools','ask_user'}
        async def catalog(args,token):
            token.check()
            query=args.get('query','').strip().casefold();offset=args.get('offset',0);limit=args.get('limit',6)
            rows=[{'name':spec.name,'description':spec.description[:200],'available':self._available(spec)}
                for spec in self._tools.values() if spec.name not in {'tool_catalog','load_tools'}
                and (not query or query in (spec.name+' '+spec.description).casefold())]
            rows.sort(key=lambda row:row['name'] in base)
            return ToolResult('success',data={'tools':rows[offset:offset+limit],'total':len(rows),
                'next_offset':offset+limit if offset+limit<len(rows) else None,'partial':offset>0 or offset+limit<len(rows)},
                message='Este índice não executou nenhuma consulta de conteúdo. Para usar uma ferramenta disponível encontrada, chame load_tools com seu nome exato e depois execute-a com argumentos válidos.')
        async def load(args,token):
            token.check()
            names=args['names']
            if any(name not in self._tools or not self._available(self._tools[name]) for name in names):
                return ToolResult('blocked',message='Ferramenta não registrada ou indisponível.')
            self.advertised=base|set(names)
            return ToolResult('success',data={'loaded':names},message='Schemas carregados. Nenhuma ferramenta foi executada; use a ferramenta para obter o resultado.')
        catalog_schema=object_schema();catalog_schema['properties'].update(query=dict(type='string',maxLength=100),offset=dict(type='integer',minimum=0,maximum=10000),limit=dict(type='integer',minimum=1,maximum=8))
        self.register(ToolSpec('tool_catalog','Catálogo de ferramentas, não de conteúdos. Busque capacidades por nome; para procedimentos use procedure_index. Vazio não significa ausência de dados.',catalog_schema,catalog,authorize=lambda args:True))
        self.register(ToolSpec('load_tools','Carregar até quatro capacidades do catálogo, substituindo extras anteriores. Recarregue ferramentas antigas se precisar.',object_schema(names={'type':'array','maxItems':4,'items':TEXT}),load,authorize=lambda args:True))
        self.advertised=base
