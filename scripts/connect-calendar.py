"""OAuth iniciado somente pelo botão explícito Conectar do desktop."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from therion.calendar.auth import run_initial_auth

if __name__=='__main__':
    try:
        run_initial_auth()
    except Exception:
        # O desktop mostra uma mensagem controlada, sem URLs OAuth nem segredos.
        sys.exit(1)
