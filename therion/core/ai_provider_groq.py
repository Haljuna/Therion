"""IA na Groq com o Ollama local de reserva: o modelo local só carrega quando a Groq falha."""
from therion.core import groq
from therion.core.ai_provider_ollama import OllamaProvider


class GroqProvider(OllamaProvider):
    online = True

    def warmup(self):
        pass  # aquecer carregaria o modelo local na memória sem necessidade

    def _send_request_serialized(self, payload, timeout):
        if payload.get('messages'):  # sem mensagens = aquecer/descarregar o local
            try:
                return groq.chat(payload, min(timeout, 30))
            except groq.GroqUnavailable as error:
                print(f'[Therion] Groq indisponível ({error}); usando o modelo local.')
        return super()._send_request_serialized(payload, timeout)
