# AutoTube — canal de YouTube automatizado

Sistema que gestiona un canal de YouTube de principio a fin:

| Paso | Qué hace | Cómo |
|---|---|---|
| 1. Tendencias | Analiza lo más visto de tu nicho (últimas 2 semanas), las tendencias del país y lo que la gente busca | YouTube Data API + autocompletado de YouTube |
| 2. Tema | Propone 5 ideas, las puntúa y elige la mejor sin repetir temas anteriores y aprendiendo de tus métricas | Claude (salida JSON estructurada) |
| 3. Investigación | Busca en la web y crea un dossier con datos verificados y fuentes | Claude + búsqueda web |
| 4. Guion | Guion por escenas pensado para retención, título SEO, descripción, etiquetas, hashtags, texto de miniatura y comentario | Claude |
| 5. Voz | Narración en español con voz neuronal, con diccionario de pronunciación para palabras en inglés | Kokoro (gratis, local), edge-tts (gratis) o ElevenLabs |
| 6. Imágenes | Vídeo de stock para cada escena, o gráficos animados generados (titulares, cifras, listas que aparecen una a una, pasos) | Pexels (gratis) o generador propio |
| 7. Vídeo | Montaje, subtítulos quemados, música de fondo, normalización de volumen a -14 LUFS, capítulos automáticos | ffmpeg |
| 8. Miniatura | 1280×720, foto llamativa, texto grande con contorno y color de acento | Pillow |
| 9. Subida | Título, descripción, etiquetas, miniatura, playlist, programación, declaración de contenido sintético, comentario del canal | YouTube Data API |
| 10. Gestión | Sincroniza estadísticas y retención, responde comentarios, manda spam a revisión y genera un informe de aprendizajes que alimenta la elección del siguiente tema | YouTube Data + Analytics API + Claude |

Soporta vídeos largos (16:9) y **Shorts** (9:16) cambiando `video.format` en `config.yaml`.

---

## 1. Instalación

Necesitas Python 3.11+ y `ffmpeg`.

```bash
git clone <este repo> && cd javiport
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # y rellena las claves
```

## 2. Claves necesarias

| Clave | Dónde conseguirla | Coste |
|---|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com | De pago por uso (aprox. céntimos–pocos dólares por vídeo) |
| `YOUTUBE_API_KEY` | Google Cloud Console → habilita **YouTube Data API v3** → Credenciales → Clave de API | Gratis (cuota diaria) |
| `PEXELS_API_KEY` | https://www.pexels.com/api/ | Gratis |
| `client_secret.json` | Google Cloud Console → habilita también **YouTube Analytics API** → Pantalla de consentimiento OAuth (tipo *Externo*, añade tu email como usuario de prueba) → Credenciales → **ID de cliente OAuth → App de escritorio** → descargar JSON y guardarlo como `secrets/client_secret.json` | Gratis |

Luego conecta tu canal (abre el navegador una vez):

```bash
python -m autotube auth
```

> **Crea el canal en YouTube a mano** (con tu cuenta de Google) antes de este paso y verifica tu
> teléfono en https://www.youtube.com/verify para poder poner miniaturas personalizadas.

## 3. Configura tu canal

Edita `config.yaml`: nicho, audiencia, tono, palabras clave, país, voz, formato (long/short),
privacidad, programación, playlist... Mete música libre de derechos en `assets/music/`
(por ejemplo de la Biblioteca de audio de YouTube) y se usará de fondo.

## 4. Uso

```bash
python -m autotube trends                     # ¿qué tema elegiría hoy?
python -m autotube create --no-upload         # genera un vídeo completo sin subirlo (revísalo en output/)
python -m autotube create --topic "Por qué el cielo es azul"
python -m autotube render output/mi-video      # renderiza a partir de un script.json escrito/editado a mano
python -m autotube upload output/20261115-1500-mi-video
python -m autotube manage                     # estadísticas + responder comentarios
python -m autotube report                     # informe de qué funciona (se guarda en data/feedback.md)
python -m autotube autopilot                  # gestionar + crear + subir (para ejecutar a diario)
```

Cada vídeo queda en `output/<fecha>-<tema>/` con `research.md`, `script.json`, `metadata.json`,
`subs.ass`, `thumbnail.jpg` y `video.mp4`.

## 5. Piloto automático (GitHub Actions)

El workflow `.github/workflows/autopilot.yml` ejecuta `autopilot` una vez al día, guarda el vídeo como
artefacto y hace commit del historial (`data/`). Añade estos *secrets* en
GitHub → Settings → Secrets and variables → Actions:

- `ANTHROPIC_API_KEY`, `YOUTUBE_API_KEY`, `PEXELS_API_KEY` (y `ELEVENLABS_API_KEY` si la usas)
- `YT_CLIENT_SECRET_JSON`: contenido de `secrets/client_secret.json`
- `YT_TOKEN_JSON`: contenido de `secrets/token.json` (se genera tras `python -m autotube auth`)

También puedes lanzarlo a mano desde la pestaña *Actions* indicando un tema.
Alternativa local: `crontab -e` → `17 15 * * * cd /ruta/javiport && .venv/bin/python -m autotube autopilot`.

---

## ⚠️ Importante antes de publicar en automático

1. **Vídeos privados hasta la auditoría de Google.** Los proyectos de Google Cloud no verificados solo
   pueden subir vídeos en modo *privado* por API. Para publicar en público automáticamente debes pedir la
   auditoría (formulario "YouTube API Services – Audit and Quota Extension"). Mientras tanto, el sistema
   sube en privado y tú los publicas con un clic desde YouTube Studio.
2. **Token de OAuth caduca a los 7 días** si la app de OAuth está en modo *Testing*. Pásala a
   *In production* en la pantalla de consentimiento (no requiere verificación para uso propio).
3. **Cuota de la API**: 10.000 unidades/día por defecto. Una subida y las búsquedas de tendencias
   consumen buena parte; 1–2 vídeos al día es lo razonable sin ampliar cuota.
4. **Monetización**: YouTube no monetiza el contenido "repetitivo o producido en masa". Para entrar en
   el Programa de Partners, revisa los vídeos antes de publicarlos, aporta tu criterio (edita guiones,
   cambia miniaturas) y prioriza calidad sobre cantidad. Empieza con `privacy: private` y revisa.
5. **Contenido sintético**: el sistema marca `containsSyntheticMedia` en cada subida, como exige YouTube
   para voces e imágenes generadas que puedan parecer reales.
6. **Derechos**: el material de Pexels es libre para uso comercial; la música debe serlo también.

## Vídeos ya preparados

En `videos/` hay 3 guiones completos del canal **Tecnología Sin Humo** (nicho: IA y ciberseguridad
para el día a día), con título, descripción, etiquetas, fuentes y miniatura:

1. `01-como-funciona-chatgpt` — Cómo funciona ChatGPT por dentro (explicado sin fórmulas)
2. `02-estafas-con-ia` — Estafas con IA: voces clonadas y videollamadas falsas (y cómo protegerte)
3. `03-passkeys-adios-contrasenas` — Passkeys: por qué las contraseñas van a desaparecer

Para regenerarlos (por ejemplo, con otra voz o tras editar el guion):

```bash
mkdir -p output/01 && cp videos/01-como-funciona-chatgpt/script.json output/01/
python -m autotube render output/01
python -m autotube upload output/01
```

El audio se guarda en caché: si solo cambias los gráficos o una escena, el re-render es rápido.

## Estructura

```
autotube/
  trends.py      tendencias + elección de tema
  script.py      investigación web + guion y SEO
  tts.py         voz en off y tiempos de subtítulos
  media.py       vídeo/fotos de stock (Pexels) y fondos de respaldo
  cards.py       gráficos animados (motion graphics) generados
  video.py       montaje con ffmpeg, subtítulos, música, capítulos
  thumbnail.py   miniaturas
  uploader.py    subida a YouTube
  manager.py     estadísticas, comentarios, informe de aprendizajes
  pipeline.py    orquestación
  llm.py         cliente de Claude
  db.py          historial en SQLite (data/autotube.db)
config.yaml      configuración del canal
```
