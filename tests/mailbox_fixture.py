"""Caixa fictícia compartilhada por testes e prévias, sem cliente Google."""
import time


class FakeMailbox:
    def __init__(self,prefix='m'):
        self.prefix=prefix;self.calls=[];self.empty=False;self.fail=False;self.delay=0.;self.body_delay=0.
        self.subjects=['Revisão do projeto Therion','Reunião de planejamento','Relatório do projeto',
            'Atualização da equipe','Documentos para revisão','Agenda da semana','Confirmação da reunião',
            'Notas de pesquisa','Resumo das atividades','Próximas entregas','Solicitação de orçamento',
            'Inscrição confirmada','Planejamento de estudos','Revisão final do documento']
    def profile(self):
        self.calls.append(('profile',));return {'email':'marcus-'+self.prefix+'@example.test'}
    def search(self,query,page=None):
        self.calls.append(('search',query,page))
        if self.fail:raise OSError('Falha fictícia de conexão')
        if self.empty:return {'messages':[],'next_page':None}
        numbers=([3,4] if 'projeto' in query else [1,3,5] if 'is:unread' in query else list(range(11,15)) if page else list(range(1,11)))
        return {'messages':[{'id':self.prefix+str(i),'threadId':'t'+self.prefix+str(i)} for i in numbers],
                'next_page':'page-2' if len(numbers)==10 else None}
    def metadata(self,identifier):
        self.calls.append(('metadata',identifier));time.sleep(self.delay)
        index=int(identifier[len(self.prefix):]);title=self.subjects[index-1]
        return {'id':identifier,'threadId':'t'+identifier,'historyId':'h-'+identifier,
            'internalDate':str(1792843200000-index*3600000),'labelIds':['INBOX']+(['UNREAD'] if index%2 else []),
            'snippet':'Prévia fictícia: '+title,
            'payload':{'headers':[{'name':'Subject','value':title},{'name':'From','value':'Equipe <equipe@example.test>'},
                                   {'name':'To','value':'Marcus <marcus@example.test>'},{'name':'Date','value':'24 Oct 2026 09:00:00 -0300'}]}}
    def thread(self,identifier):
        self.calls.append(('thread',identifier));time.sleep(self.body_delay)
        message=identifier[1:];index=int(message[len(self.prefix):])
        return {'id':identifier,'version':'version-'+identifier,'url':'https://mail.google.com/#all/'+identifier,
            'messages':[{'id':message,'headers':{'subject':self.subjects[index-1],'from':'Equipe <equipe@example.test>',
                'to':'Marcus <marcus@example.test>','date':'24 Oct 2026 09:00:00 -0300'},
                'text':self.text(message),'partial':False,'labels':['INBOX'],'attachments':[]}]}
    def text(self,identifier):
        return ('CONTEÚDO EXCLUSIVO '+identifier+'\n\nOlá, Marcus.\n\nVamos revisar os próximos passos do projeto na reunião de amanhã. '
            '\nO documento de referência está pronto para a revisão.\n\nAtenciosamente,\nEquipe de demonstração')


class ReadingMailbox(FakeMailbox):
    """Exemplo de leitura com ações, tabela, rodapé e ruído promocional."""
    def __init__(self):
        super().__init__()
        self.subjects[:5]=['Revisão do projeto · retorno até terça-feira','Documento pronto para aprovação',
            'Ofertas selecionadas para esta semana','Novas sugestões de pessoas para seguir','Código de acesso da sua conta']

    def metadata(self,identifier):
        row=super().metadata(identifier);index=int(identifier[len(self.prefix):])
        if index==1:row['labelIds'].append('IMPORTANT')
        if index==3:row['labelIds'].append('CATEGORY_PROMOTIONS')
        if index==4:row['labelIds'].append('CATEGORY_SOCIAL')
        if index==5:row['labelIds'].append('CATEGORY_UPDATES')
        row['snippet']={1:'Confira a versão final e envie seus comentários até terça-feira.',
            2:'Reunião às 14h. Revise o documento e confirme a aprovação até 28/10.',
            3:'Conheça as novidades e os descontos desta semana.',4:'Veja novas pessoas e publicações sugeridas.',
            5:'Seu código de verificação. Não compartilhe com outras pessoas.'}.get(index,row['snippet'])
        return row

    def text(self,identifier):
        if identifier!='m2':return super().text(identifier)
        from therion.integrations.mail_text import html_mail_text
        return html_mail_text('''<html><head><style>body{color:black}</style></head><body>
        <div style="display:none">Um documento está aguardando a sua revisão.</div>
        <p>Ver no navegador <a href="https://example.test/view">Abrir</a></p>
        <h2>Olá, Marcus.</h2><p>A versão final do documento está pronta. Precisamos da sua aprovação para seguir com a próxima etapa do projeto.</p>
        <table><tr><td><b>Prazo para resposta</b></td><td>28/10/2026, até as 18h</td></tr>
        <tr><td><b>Próxima reunião</b></td><td>Terça-feira, às 14h</td></tr></table>
        <p>Antes de confirmar:</p><ul><li>Confira os valores na versão final.</li><li>Envie os ajustes por resposta a este e-mail.</li></ul>
        <p><a href="https://example.test/documento/42?utm_source=email&amp;utm_campaign=demo">Abrir documento de revisão</a></p>
        <p>Atenciosamente,<br>Equipe do projeto</p>
        <p>Você está recebendo este e-mail porque acompanha as novidades do projeto.</p>
        <p>Cancelar inscrição <a href="https://example.test/leave">Gerenciar</a></p>
        <p>Política de privacidade <a href="https://example.test/privacy">Conferir</a></p>
        </body></html>''')
