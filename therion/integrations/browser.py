"""Navegador com perfil próprio, domínios explícitos e ações por controles."""
import hashlib
import ipaddress
import json
import socket
import time
from .verification import expectation, matches,protected_action
from urllib.parse import urlsplit
from urllib.parse import quote_plus, parse_qs
from datetime import datetime, timezone

CONTROL_SELECTOR='button,a,input:not([type=password]):not([type=file]):not([type=hidden]),textarea,select'


def allowed_url(url, domains, *, fixture=False):
    parsed=urlsplit(url)
    if parsed.username or parsed.password or parsed.scheme not in ({'http','https'} if fixture else {'https'}):return False
    host=(parsed.hostname or '').lower()
    if '*' not in domains and host not in {domain.lower() for domain in domains}:return False
    if fixture:return True
    try:
        return all(ipaddress.ip_address(row[4][0]).is_global for row in socket.getaddrinfo(host,parsed.port or 443,type=socket.SOCK_STREAM))
    except (OSError,ValueError):return False


class BrowserSession:
    def __init__(self, config):
        from playwright.sync_api import sync_playwright
        self.config=config
        self.engine=sync_playwright().start()
        self.browser=None
        channel=config.get('channel','chromium')
        if channel not in ('chromium','msedge'):
            self.engine.stop();raise ValueError('Navegador fora dos canais registrados.')
        options={'channel':'msedge'} if channel=='msedge' else {}
        try:
            headless=config.get('fixture') is True and config.get('visible') is not True
            if config.get('research') is True:
                self.browser=self.engine.chromium.launch(headless=headless,**options)
                self.context=self.browser.new_context(accept_downloads=False)
            else:
                self.context=self.engine.chromium.launch_persistent_context(config['profile'],headless=headless,
                    accept_downloads=True,**options)
            self.sources={}
            self.page=self.context.pages[0] if self.context.pages else self.context.new_page()
            self.context.route('**/*',self._route)
        except BaseException as failure:
            for close in ([self.browser.close] if self.browser is not None else [])+[self.engine.stop]:
                try:close()
                except Exception as cleanup:failure.add_note('Falha adicional ao encerrar navegador: '+type(cleanup).__name__)
            raise

    def _route(self,route):
        if self.config.get('research') is True and route.request.method not in {'GET','HEAD'}:
            route.abort();return
        if allowed_url(route.request.url,self.config.get('domains',()),fixture=self.config.get('fixture') is True):route.continue_()
        else:route.abort()

    def snapshot(self,offset=0,limit=6000):
        if not allowed_url(self.page.url,self.config.get('domains',()),fixture=self.config.get('fixture') is True):
            raise ValueError('Página atual fora dos domínios autorizados.')
        full_text=self.page.locator('body').inner_text(timeout=5000)
        if len(full_text)>2_000_000:raise ValueError('Página acima do limite de extração; não a tratei como leitura completa.')
        if self.config.get('research') is True:
            from .excerpts import validate_interval
            validate_interval(offset,limit)
            title=self.page.title().strip().casefold()
            if title in {'just a moment...','just a moment','access denied','verify you are human','security verification','captcha'}:
                raise OSError('A fonte exige verificação humana ou bloqueou o acesso. Não extraí o bloqueio como conteúdo da pesquisa.')
            if offset>len(full_text):raise ValueError('Intervalo fora do texto da página.')
            end=min(len(full_text),offset+limit)
            return {'url':self.page.url,'text':full_text[offset:end],
                'version':hashlib.sha256(json.dumps([self.page.url,full_text]).encode()).hexdigest(),
                'offset':offset,'total_characters':len(full_text),'partial':offset>0 or end<len(full_text),
                'next_offset':end if end<len(full_text) else None,'controls':[],'forms':[]}
        text=full_text[:20000]
        controls=self.page.locator(CONTROL_SELECTOR)
        raw_forms=self.page.locator('form').evaluate_all(r'''(forms, selector) => {
            if(forms.length>20) throw Error('Formulário acima do limite de revisão');
            const known=Array.from(document.querySelectorAll(selector)).slice(0,80);let size=0;
            const sensitive=el=>['password','file'].includes(el.type)||/^(cc-|one-time-code|username|current-password|new-password)/i.test(el.autocomplete||'')||/^(card[_-]?number|cc[_-]?number|cvv|cvc|otp|totp|passcode)$/i.test(el.name||'');
            return forms.map(form=>{
                const elements=Array.from(form.elements);
                if(elements.length>500) throw Error('Formulário acima do limite de revisão');
                const fields=elements.map(el=>{
                    const value=sensitive(el)?'<protegido>':String(el.value||'');
                    size+=value.length;
                    if(size>50000) throw Error('Formulário acima do limite de revisão');
                    return [el.tagName,el.type,el.name,value,el.checked,el.disabled];
                });
                return {action:form.action,method:form.method,fields,
                    protected:elements.some(sensitive)||/\/(checkout|payment|billing|login|signin|auth|mfa|security|password)(\/|\?|$)/i.test(form.action),
                    review_complete:elements.every(el=>el.type==='hidden'||known.includes(el))};
            });
        }''',CONTROL_SELECTOR)
        forms=[]
        for form in raw_forms:
            digest=hashlib.sha256(json.dumps(form,sort_keys=True).encode()).hexdigest()
            forms.append({key:value for key,value in form.items() if key!='fields'}|{'version':digest})
        items=[]
        for index in range(min(controls.count(),80)):
            item=controls.nth(index)
            protected=item.evaluate("el=>['password','file'].includes(el.type)||/^(cc-|one-time-code|username|current-password|new-password)/i.test(el.autocomplete||'')||/^(card[_-]?number|cc[_-]?number|cvv|cvc|otp|totp|passcode)$/i.test(el.name||'')")
            items.append({'id':str(index),'text':(item.inner_text() or item.get_attribute('aria-label') or item.get_attribute('placeholder') or '')[:200],
                'tag':item.evaluate('(element)=>element.tagName.toLowerCase()'),
                'input_type':item.get_attribute('type') or '',
                'protected':protected,
                'value':'<protegido>' if protected else item.input_value()[:4000] if item.evaluate('(element)=>["INPUT","TEXTAREA","SELECT"].includes(element.tagName)') else '',
                'form_index':item.evaluate('(element)=>Array.from(document.forms).indexOf(element.form||element.closest("form"))')})
        version=hashlib.sha256(json.dumps([self.page.url,full_text,items,forms],sort_keys=True).encode()).hexdigest()
        return {'url':self.page.url,'text':text,'controls':items,'forms':forms,'version':version,
            'partial':len(full_text)>len(text),'total_characters':len(full_text),'controls_partial':controls.count()>80}

    def dispatch(self,operation,args):
        if self.config.get('research') is True and operation not in {'search','read_source','read','open'}:
            raise ValueError('Pesquisa pública é somente leitura, sem sessão pessoal.')
        if operation=='search':
            self.page.goto('https://duckduckgo.com/?q='+quote_plus(args['query']),wait_until='domcontentloaded',timeout=20000)
            self.sources.clear();rows=[]
            from playwright.sync_api import TimeoutError as BrowserTimeout
            try:
                self.page.wait_for_function('''() => document.querySelector('[data-testid="result-title-a"],a.result__a,[data-testid="no-results"],.no-results,.anomaly-modal') || /captcha|unusual traffic|verify you are human/i.test(document.body?.innerText || '')''',timeout=10000)
            except BrowserTimeout as error:
                raise OSError('Não confirmei o carregamento dos resultados da busca; não interpretei a falha como busca vazia.') from error
            text=self.page.locator('body').inner_text(timeout=5000).casefold()
            has_results=self.page.locator('[data-testid="result-title-a"],a.result__a').count()>0
            if (not has_results and any(marker in text for marker in ('captcha','unusual traffic','verify you are human','confirme que você é humano'))) or self.page.locator('.anomaly-modal').count():
                raise OSError('O mecanismo de busca exige verificação humana ou bloqueou o acesso. Não contornei a restrição.')
            for item in self.page.locator('[data-testid="result-title-a"],a.result__a').all()[:100]:
                url=item.get_attribute('href') or ''
                parsed=urlsplit(url)
                if parsed.hostname and parsed.hostname.endswith('duckduckgo.com'):
                    url=parse_qs(parsed.query).get('uddg',[''])[0]
                if not url or not allowed_url(url,('*',)) or url in self.sources.values():continue
                title=item.inner_text()[:200].strip()
                if not title:continue
                identifier='web:'+str(len(rows)+1);self.sources[identifier]=url
                rows.append({'id':identifier,'title':title,'url':url})
                if len(rows)==10:break
            if not rows and not self.page.locator('[data-testid="no-results"],.no-results').count():
                raise OSError('A página não forneceu resultados verificáveis nem confirmou ausência de resultados.')
            return {'query':args['query'],'results':rows,'accessed_at':datetime.now(timezone.utc).isoformat()}
        if operation=='read_source':
            url=self.sources.get(args['source_id'])
            if not url:raise ValueError('Fonte não retornada pela pesquisa desta sessão.')
            if self.page.url!=url:self.dispatch('open',{'url':url})
            result=self.snapshot(args.get('offset',0),args.get('limit',6000))
            result['id']=args['source_id'];result['accessed_at']=datetime.now(timezone.utc).isoformat()
            return result
        if operation=='open':
            if not allowed_url(args['url'],self.config.get('domains',()),fixture=self.config.get('fixture') is True):
                raise ValueError('URL fora do escopo ou destino de rede não permitido.')
            self.page.goto(args['url'],wait_until='domcontentloaded',timeout=20000)
            return self.snapshot()
        if operation=='read':return self.snapshot()
        if operation in {'fill','click','download'}:
            before=self.snapshot()
            if args['version']!=before['version']:raise ValueError('Página mudou desde a prévia.')
            controls=self.page.locator(CONTROL_SELECTOR)
            index=int(args['control_id'])
            if index<0 or index>=min(controls.count(),80):raise ValueError('Controle não selecionado.')
            control=controls.nth(index).element_handle()
            if control is None:raise ValueError('O controle original não está mais disponível.')
            if self.snapshot()['version']!=before['version']:raise ValueError('A página mudou durante a seleção do controle; leia novamente.')
            if before['controls'][index].get('protected'):raise ValueError('Credenciais e campos protegidos exigem interação manual.')
            form_index=before['controls'][index]['form_index']
            if form_index>=0:
                form=before['forms'][form_index]
                if form['protected'] or not form['review_complete']:
                    raise ValueError('Login, arquivos e formulários sem revisão completa exigem interação manual.')
            value=(control.get_attribute('value') or '') if control.get_attribute('type') in {'button','submit','reset'} else ''
            label=before['controls'][index]['text']+' '+(control.get_attribute('name') or '')+' '+value
            if protected_action(label):
                raise ValueError('Pagamento, compra, credenciais, exclusão permanente e alteração de segurança fora das capacidades desta entrega.')
            if operation=='download':
                from pathlib import Path
                from therion.memory.knowledge import safe_path
                import os
                import hashlib
                path=safe_path(args['path'],self.config.get('download_roots',()))
                if path.suffix.lower() not in {'.txt','.md','.pdf','.docx','.xlsx'}:raise ValueError('Formato de download não autorizado.')
                current=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
                if current!=args.get('expected_version'):raise ValueError('Destino mudou desde a prévia.')
                with self.page.expect_download(timeout=20000) as download_info:control.click(timeout=5000)
                download=download_info.value
                temporary=download.path()
                if Path(temporary).stat().st_size>20_000_000:download.cancel();raise ValueError('Download acima do limite.')
                if (hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None)!=current:
                    raise ValueError('Destino mudou antes da publicação.')
                import tempfile
                descriptor,name=tempfile.mkstemp(prefix='.therion-download-',suffix='.tmp',dir=path.parent)
                os.close(descriptor);temporary_target=Path(name)
                try:
                    download.save_as(str(temporary_target))
                    safe_path(path,self.config.get('download_roots',()))
                    if (hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None)!=current:raise ValueError('Destino mudou antes da publicação.')
                    os.replace(temporary_target,path)
                finally:
                    if temporary_target.exists():temporary_target.unlink()
                return {'path':str(path),'version':hashlib.sha256(path.read_bytes()).hexdigest(),'action_observed':True}
            expected=expectation(args,browser=True) if operation=='click' else None
            if expected and matches(before,expected):return dict(before,action_observed=False,already_satisfied=True)
            if operation=='fill':control.fill(args['text'],timeout=5000)
            else:control.click(timeout=5000)
            deadline=time.monotonic()+3
            while True:
                after=self.snapshot()
                after['action_observed']=matches(after,expected) if expected else control.input_value(timeout=1000)==args['text']
                if after['action_observed'] or time.monotonic()>=deadline:return after
                time.sleep(.05)
        raise ValueError('Operação de navegador não suportada.')

    def close(self):
        self.context.close()
        if self.browser:self.browser.close()
        self.engine.stop()
