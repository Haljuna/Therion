"""Configuração opt-in; não modifica parâmetros pessoais existentes."""
DEFAULTS = {'enabled': False, 'history_enabled': False, 'protocol': 'json',
    'timeout_seconds': 180, 'gmail_enabled': False, 'browser_enabled': False,
    'desktop_enabled': False, 'documents_enabled': False, 'learning_enabled': False, 'web_enabled': False,'source_cache_enabled':False,
    'context_tokens':8192,'output_tokens':2048,'think':None,'mcp_enabled':False,'tasks_enabled':False,'browser_channel':'chromium'}


def validate_settings(value):
    result = dict(DEFAULTS)
    if isinstance(value, dict):
        result.update(value)
    for name, default in DEFAULTS.items():
        if type(default) is bool and type(result[name]) is not bool:
            result[name] = False
    if result['protocol'] not in {'json', 'native'}:
        result['protocol'] = 'json'
    if result['browser_channel'] not in ('chromium','msedge'):result['browser_channel']='chromium'
    if type(result['timeout_seconds']) is not int or not 10 <= result['timeout_seconds'] <= 1800:
        result['timeout_seconds'] = 180
    if type(result['context_tokens']) is not int or not 1024<=result['context_tokens']<=16384:result['context_tokens']=8192
    if type(result['output_tokens']) is not int or not 128<=result['output_tokens']<result['context_tokens']:result['output_tokens']=min(2048,result['context_tokens']//2)
    if result['think'] is not None and type(result['think']) is not bool:result['think']=None
    from therion.integrations.mcp import validate_registry
    try:result['mcp_servers']=validate_registry(result.get('mcp_servers',[]))
    except (ValueError,TypeError,KeyError):
        # Preservar o cadastro inválido para revisão; nunca executá-lo.
        result['mcp_enabled']=False
    for key in ('browser_domains','document_read_roots','document_write_roots'):
        rows=result.get(key,[])
        result[key]=list(dict.fromkeys(rows)) if isinstance(rows,list) and len(rows)<=50 and all(isinstance(item,str) and 0<len(item)<=1000 for item in rows) else []
    targets=result.get('desktop_targets',{})
    result['desktop_targets']={key:row for key,row in targets.items() if isinstance(key,str) and isinstance(row,dict)
        and type(row.get('pid')) is int and row['pid']>0 and type(row.get('handle')) is int and row['handle']>0
        and isinstance(row.get('path'),str) and isinstance(row.get('actions'),list) and set(row['actions'])<={'read','click','fill'}} if isinstance(targets,dict) else {}
    return result
