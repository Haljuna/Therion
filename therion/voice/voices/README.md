# Estilo Santa para o perfil C

`pm_santa.npy` contém somente o tensor float32 (510, 1, 256) convertido do arquivo oficial `pm_santa.pt` de hexgrad/Kokoro-82M, publicado sob Apache-2.0.

Origem: https://huggingface.co/hexgrad/Kokoro-82M/blob/main/voices/pm_santa.pt

SHA-256 do `.pt` original: `d42103169c5c872abbafb9129133af7e942bb9d272c3cc3b95c203e7d7198c29`.

SHA-256 do `.npy`: `036e409b2e99ca9ee391a98bc659b5c0e1a8097adc61ca779fe176dc54580a13`.

O perfil `alex_santa_c` combina Alex 80% + Santa 20% sem modificar os estilos originais. Velocidade nativa 1,0 e pitch nativo; equalização C3 em 280 Hz/−0,5 dB/Q 0,75, 1800 Hz/+0,6 dB/Q 0,8 e 4800 Hz/+0,7 dB/Q 0,8. Normalização RMS 0,08, pico limitado a 0,98, antes e depois do filtro. Sem PSOLA, respirações ou pausas artificiais.

Instalar `requirements-kokoro.txt` no ambiente de síntese indicado por `tts.python_path`. Selecionar `tts.voice = "alex_santa_c"`; `"pm_alex"` continua disponível como perfil anterior. O worker verifica o hash do estilo e falha se estiver ausente ou alterado, sem trocar silenciosamente de voz. Reiniciar o Therion após mudar o perfil para liberar qualquer worker já carregado.
