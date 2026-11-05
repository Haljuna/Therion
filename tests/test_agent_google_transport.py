import httpx
import pytest

from therion.integrations.google_transport import GoogleTransport


def test_google_sdk_does_not_replay_post_after_uncertain_response():
    from googleapiclient.http import HttpRequest
    from google_auth_httplib2 import AuthorizedHttp
    from google.oauth2.credentials import Credentials
    calls=[]
    def respond(request):
        calls.append(request)
        raise httpx.ReadError('Resposta interrompida',request=request)
    transport=GoogleTransport(client=httpx.Client(transport=httpx.MockTransport(respond),follow_redirects=False))
    authorized=AuthorizedHttp(Credentials(token='fictitious-test-token'),http=transport,max_refresh_attempts=0)
    request=HttpRequest(authorized,lambda response,body:body,'https://gmail.googleapis.com/gmail/v1/users/me/drafts/send',method='POST',body='{"id":"fixture"}')
    try:
        with pytest.raises(httpx.ReadError):request.execute()
        assert len(calls)==1 and calls[0].method=='POST'
    finally:transport.close()


def test_google_redirect_is_not_followed():
    calls=[]
    def respond(request):calls.append(request);return httpx.Response(307,headers={'location':'https://example.test/other'})
    transport=GoogleTransport(client=httpx.Client(transport=httpx.MockTransport(respond),follow_redirects=False))
    try:
        response,_=transport.request('https://gmail.googleapis.com/fixture','POST',body='fixture')
        assert response.status==307 and len(calls)==1
        with pytest.raises(ValueError,match='endpoints'):transport.request('https://gmail.googleapis.com.example.test/fixture')
        assert len(calls)==1
    finally:transport.close()


def test_google_unauthorized_post_is_not_refreshed_and_repeated():
    from googleapiclient.http import HttpRequest
    from googleapiclient.errors import HttpError
    from google_auth_httplib2 import AuthorizedHttp
    from google.oauth2.credentials import Credentials
    calls=[]
    def respond(request):calls.append(request);return httpx.Response(401,json={'error':{'message':'expired fixture'}})
    transport=GoogleTransport(client=httpx.Client(transport=httpx.MockTransport(respond)))
    authorized=AuthorizedHttp(Credentials(token='fictitious-test-token'),http=transport,max_refresh_attempts=0)
    request=HttpRequest(authorized,lambda response,body:body,'https://gmail.googleapis.com/gmail/v1/users/me/drafts/send',method='POST',body='{}')
    try:
        with pytest.raises(HttpError):request.execute()
        assert len(calls)==1
    finally:transport.close()
