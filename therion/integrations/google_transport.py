"""Transporte compatível com Google SDK, sem replay, redirects ou proxy herdado."""
from urllib.parse import urlsplit


class GoogleTransport:
    def __init__(self,*,client=None):
        import httpx
        self.timeout=30
        self.client=client or httpx.Client(trust_env=False,follow_redirects=False,timeout=30,
            transport=httpx.HTTPTransport(retries=0))

    def request(self,uri,method='GET',body=None,headers=None,**kwargs):
        import httplib2
        url=urlsplit(uri)
        if url.scheme!='https' or url.hostname not in {'gmail.googleapis.com','calendar.googleapis.com','www.googleapis.com','oauth2.googleapis.com','accounts.google.com'} or url.username or url.password:
            raise ValueError('Destino fora dos endpoints Google autorizados.')
        response=self.client.request(method,uri,content=body,headers=headers,timeout=self.timeout)
        values=dict(response.headers);values['status']=str(response.status_code);values['reason']=response.reason_phrase
        return httplib2.Response(values),response.content

    def close(self):self.client.close()
