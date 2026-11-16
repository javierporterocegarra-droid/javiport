# Guía de contenido de TecnoHistoria (para las sesiones semanales de Claude)

Esta guía la sigue la sesión programada que cada domingo escribe los guiones de la semana siguiente.
La estrategia completa está en el documento «TecnoHistoria: sistema completo del canal».

## Identidad

- **Canal:** TecnoHistoria — «De dónde viene la tecnología, hacia dónde va y cómo sacarle partido».
- **Narradora:** Ximena (voz neuronal). Tono: narrativo y con suspense en las historias, claro y práctico
  en las guías. Riguroso, con datos y fuentes, sin exagerar ni prometer lo que el vídeo no cumple.
- **Pilares:** historia de empresas e inventos (40 %), nuevas tecnologías explicadas con datos (30 %),
  guías prácticas para aprovecharlas, sobre todo IA y apps (30 %).
- **Nunca:** datos sin fuente, consejos médicos, legales o de inversión, política partidista,
  clickbait que el vídeo no cumple, imitar a personas reales con IA.

## Calendario semanal (desde el 1 de diciembre de 2026, hora de Madrid)

| Día | Pieza | Hora | `format` | Duración | Palabras de narración |
| --- | --- | --- | --- | --- | --- |
| Martes | Documental (pilar historia) | 18:00 | `long` | 15–20 min | 2.200–2.800 |
| Sábado | Explicador con datos o guía práctica (alternar cada semana) | 18:00 | `long` | 10–12 min | 1.400–1.700 |
| Lunes, miércoles, jueves, viernes, domingo | Short (dato, truco o momento clave de los vídeos de la semana) | 13:00 | `short` | 40–55 s | 110–140 |

## Cómo se trabaja cada domingo

1. Lee `docs/ideas.md` y elige las siguientes ideas sin marcar (el documental del pilar historia; el
   vídeo del sábado alterna explicador y guía). Revisa `videos/` para no repetir temas.
2. Investiga cada tema con búsqueda web: 3–6 fuentes fiables; anota en `sources` las URL que abras.
   Comprueba fechas, cifras y nombres. Si un dato no se puede confirmar, no lo uses.
3. Escribe cada guion en `videos/NN-slug/script.json` (NN = siguiente número libre, dos o más cifras).
4. Marca la idea como hecha en `docs/ideas.md` (`[x]`) con el nombre de la carpeta.
5. Valida los JSON (`python3 -c "import json,sys; json.load(open(sys.argv[1]))" ruta`), haz commit y
   push a `main`. GitHub Actions renderiza y sube cada vídeo unos 3 días antes de su `publish_at`.

## Estructura de los guiones

- **Documental:** gancho (escena del clímax, 0–15 s) → pregunta → promesa → contexto → acto 1 (ascenso)
  → acto 2 (la decisión clave; dato sorpresa a mitad) → acto 3 (consecuencias) → la lección (opinión
  propia) → cierre que lleva a otro vídeo del canal. Pide la suscripción hacia el minuto 2.
- **Explicador:** dato que sorprende → qué es (con una analogía) → cómo funciona → qué hay de real y qué
  de humo (con cifras y fechas) → qué significa para el espectador → cierre.
- **Guía práctica:** enseña el resultado en los primeros 10 s → requisitos → pasos de menos a más
  difícil → errores comunes → resumen. Pon el año en el título.
- **Short:** dato o giro en la primera frase, 3–5 escenas rápidas, cierre «la historia completa, en el
  canal» cuando derive de un vídeo largo. Nada de saludos.
- Una escena = 1–3 frases. Cada escena lleva una tarjeta (`card`). En historias, 4–8 escenas con `photo`
  (búsqueda en inglés para Wikimedia Commons, o `File:Nombre_exacto.jpg`) y `photo_caption` en español.
- Varía los `layout` (title, bullets, number, quote, steps). `items` cortos (máx. ~30 caracteres).
- Sin emojis dentro del texto de `items` o `heading` (solo en `icon`).

## Formato de `script.json`

```json
{
  "topic": "tema en una frase",
  "title": "Título SEO, palabra clave al principio, < 70 caracteres",
  "description": "150–300 palabras, dos primeras líneas con la palabra clave; sin capítulos (se añaden solos)",
  "tags": ["10-15 etiquetas, palabras clave reales"],
  "hashtags": ["#Uno", "#Dos", "#Tres"],
  "thumbnail_text": "2-4 palabras que completen el título",
  "thumbnail_badge": "año o cifra corta",
  "thumbnail_icon": "un emoji (si no hay foto)",
  "thumbnail_photo": "búsqueda de Wikimedia para la foto de la miniatura, o vacío",
  "thumbnail_query": "",
  "pinned_comment": "pregunta para los comentarios",
  "sources": ["https://..."],
  "publish_at": "2026-12-01T18:00:00",
  "tz": "Europe/Madrid",
  "format": "long",
  "scenes": [
    {"section": "Capítulo", "narration": "Texto que lee la voz.", "visual_query": "english words",
     "card": {"layout": "title", "heading": "Texto grande", "items": ["subtítulo"], "icon": "💡"},
     "photo": "Nokia 3310", "photo_caption": "Nokia 3310 (2000)"}
  ]
}
```

`photo` y `photo_caption` son opcionales. Los Shorts usan `"format": "short"` y no necesitan
`thumbnail_*` (se pueden dejar vacíos, pero los campos deben existir).
