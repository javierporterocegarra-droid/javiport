"""Investigación del tema y escritura del guion + metadatos SEO."""

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "título SEO, máx. 70 caracteres, sin clickbait engañoso"},
        "description": {"type": "string", "description": "descripción de 150-300 palabras con palabras clave, sin enlaces inventados"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "hashtags": {"type": "array", "items": {"type": "string"}, "description": "3 hashtags con #"},
        "thumbnail_text": {"type": "string", "description": "2-4 palabras impactantes para la miniatura"},
        "thumbnail_query": {"type": "string", "description": "búsqueda EN INGLÉS de una foto llamativa para la miniatura"},
        "thumbnail_icon": {"type": "string", "description": "un emoji grande y expresivo para la miniatura"},
        "pinned_comment": {"type": "string", "description": "comentario del canal que invite a comentar"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string", "description": "nombre corto del capítulo al que pertenece"},
                    "narration": {"type": "string", "description": "texto que leerá la voz en off"},
                    "visual_query": {"type": "string", "description": "búsqueda EN INGLÉS de vídeo de stock para esta escena (2-4 palabras concretas)"},
                    "card": {
                        "type": "object",
                        "description": "gráfico animado de la escena (se usa si no hay vídeo de stock)",
                        "properties": {
                            "layout": {"type": "string", "enum": ["title", "bullets", "number", "quote", "steps"]},
                            "heading": {"type": "string", "description": "texto principal, máx. 8 palabras"},
                            "items": {"type": "array", "items": {"type": "string"},
                                      "description": "bullets/steps: 2-4 frases cortas; number: [la cifra]; title: [subtítulo] o vacío"},
                            "icon": {"type": "string", "description": "un emoji relacionado o cadena vacía"},
                        },
                        "required": ["layout", "heading", "items", "icon"],
                        "additionalProperties": False,
                    },
                },
                "required": ["section", "narration", "visual_query", "card"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "description", "tags", "hashtags", "thumbnail_text", "thumbnail_query", "thumbnail_icon", "pinned_comment", "scenes"],
    "additionalProperties": False,
}


def research_topic(cfg: dict, llm, topic: dict) -> str:
    questions = "\n".join(f"- {q}" for q in topic["research_questions"])
    prompt = f"""Investiga a fondo este tema para un vídeo de YouTube.
Tema: {topic['topic']}
Enfoque: {topic['angle']}
Preguntas a responder:
{questions}

Busca en la web fuentes fiables y recientes. Devuelve un dossier en '{cfg['channel']['language']}' con:
1. Datos clave y cifras verificadas (indica la fuente de cada uno)
2. Historias, ejemplos o anécdotas que enganchen
3. Conceptos erróneos comunes y la realidad
4. Lo más reciente (noticias o estudios)
5. Qué NO se sabe o está en debate
No inventes nada: si un dato no está confirmado, dilo."""
    return llm.research("Eres un investigador y verificador de datos meticuloso.", prompt)


def write_script(cfg: dict, llm, topic: dict, dossier: str) -> dict:
    ch, v = cfg["channel"], cfg["video"]
    if v["format"] == "short":
        length = ("un YouTube Short de 45-55 segundos (unas 120-140 palabras en total), 5-8 escenas cortas. "
                  "Gancho brutal en la primera frase, ritmo muy rápido, final que invite a ver otra vez.")
    else:
        words = int(v["target_minutes"] * 150)
        length = (f"un vídeo de unos {v['target_minutes']} minutos (~{words} palabras de narración), "
                  "entre 20 y 45 escenas de 1-3 frases. Estructura: gancho en los primeros 15 s, "
                  "promesa del vídeo, desarrollo en 4-6 capítulos con micro-ganchos de retención, "
                  "conclusión y llamada a la acción breve (suscribirse/comentar).")
    prompt = f"""Escribe el guion completo para {length}

Canal: {ch['name']} — {ch['niche']}
Audiencia: {ch['audience']}
Tono: {ch['tone']}
Idioma: {ch['language']}

Tema: {topic['topic']}
Enfoque: {topic['angle']}
Título provisional: {topic['working_title']}

DOSSIER DE INVESTIGACIÓN (usa solo hechos de aquí):
{dossier}

Reglas:
- La narración se leerá con voz sintética: frases naturales, sin acotaciones, emojis ni markdown.
- Escribe los números como se pronuncian si hay ambigüedad.
- Cada escena tiene una búsqueda visual concreta y filmable en inglés (p. ej. "astronaut floating space station").
- Cada escena tiene además una tarjeta gráfica que resume visualmente lo que se dice (cifras con "number",
  listas con "bullets", procesos con "steps", ideas clave con "quote", inicio de capítulo con "title").
  Varía los tipos para mantener el ritmo visual.
- Nada de afirmaciones falsas, médicas o financieras personalizadas.
- El título y la miniatura deben ser intrigantes pero cumplir lo que prometen.
- No incluyas capítulos ni timestamps en la descripción (se añaden automáticamente)."""
    return llm.json("Eres un guionista profesional de YouTube especializado en retención de audiencia.",
                    prompt, SCRIPT_SCHEMA)
