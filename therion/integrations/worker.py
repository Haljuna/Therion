"""Entrada privada de worker próprio; sem shell ou código recebido do modelo."""
import json
import sys


def main():
    kind=sys.argv[1]
    instance=None;configuration=None
    try:
        for line in sys.stdin:
            if len(line)>1_000_000:break
            row={}
            try:
                row=json.loads(line)
                if instance is None:
                    if kind=='browser':
                        from .browser import BrowserSession as Session
                    elif kind=='desktop':
                        from .desktop import DesktopSession as Session
                    elif kind=='documents':
                        from .documents import DocumentSession as Session
                    elif kind=='gmail':
                        from .gmail import GmailSession as Session
                    elif kind=='mcp':
                        from .mcp import MCPSession as Session
                    elif kind=='calendar':
                        from .calendar import CalendarSession as Session
                    else:raise ValueError('Worker desconhecido.')
                    configuration=row['config'];instance=Session(configuration)
                if row['config']!=configuration:raise ValueError('Configuração do worker mudou; reinicie.')
                result=instance.dispatch(row['operation'],row['arguments'])
                response={'id':row['id'],'result':result}
            except Exception as error:
                response={'id':row.get('id'),'error':str(error)[:500]}
            print(json.dumps(response,ensure_ascii=False),flush=True)
    finally:
        if instance:instance.close()


if __name__=='__main__':main()
