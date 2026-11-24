# DobleCheck ✓✓ — noticias contrastadas en todos los medios españoles

Una web que muestra las noticias más relevantes del momento, agrupando lo que
publican ~30 medios españoles. Un **worker** lee sus RSS cada 5 minutos y un
**algoritmo propio (sin IA)** decide si cada artículo es una noticia nueva o
cobertura de una ya existente. **La IA solo se usa para redactar** el texto de
cada noticia a partir de las fuentes agrupadas.

Sin dependencias: solo Python 3.10+ (biblioteca estándar) y SQLite.

## Publicación gratuita en GitHub Pages (como está montado)

La web es estática (`docs/index.html` + `docs/data/*.json`). El workflow
`.github/workflows/publicar.yml` se ejecuta **cada 15 minutos** en GitHub Actions,
lanzado por un Worker de Cloudflare (`cloudflare/worker.js`) porque los horarios
de GitHub no son puntuales (GitHub solo hace de respaldo cada hora):
lee los medios, agrupa, redacta con IA lo que haga falta, regenera los JSON y
publica `docs/` en Pages. La base de datos se conserva entre ejecuciones en la
caché de Actions (si se pierde, se reconstruye sola con las últimas 48 h).

Puesta en marcha (una sola vez):
1. El repositorio debe ser **público** (Pages y minutos de Actions gratis).
2. *Settings → Pages → Build and deployment → Source*: **GitHub Actions**.
3. *Settings → Secrets and variables → Actions → New repository secret*:
   `ANTHROPIC_API_KEY` (opcional; sin él se muestra el titular original).
4. *Actions → Actualizar noticias → Run workflow* para la primera pasada.
5. Cloudflare → Workers → crear un Worker con `cloudflare/worker.js`, secreto
   `GITHUB_TOKEN` (token fine-grained con *Actions: Read and write* en este
   repositorio) y Cron Trigger `*/15 * * * *`.

La web queda en `https://<usuario>.github.io/noticias-espana/`.

## Arrancar en local

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # opcional; sin ella se muestra el titular original
python run.py                            # web + worker en un proceso → http://localhost:8000
```

O por separado (recomendado en producción):

```bash
python worker.py            # bucle infinito
python server.py            # web
python worker.py --once -v  # un ciclo, mostrando cada decisión NUEVA / AÑADE
python worker.py --check-feeds   # qué medios responden
```

## Cómo funciona

```
 RSS de ~30 medios ──► worker.py ──► textproc.py ──► clustering.py ──► SQLite ──► server.py ──► web
   (cada 5 min,          descarga      rasgos del       ¿nueva o           noticias,     API JSON
    peticiones           en paralelo,  artículo         existente?         artículos,
    condicionales)       deduplica                                         fuentes
                                                            │
                                                            └─► writer.py (IA) solo cuando una noticia
                                                                tiene ≥2 medios o gana medios nuevos
```

### 1. Rasgos de cada artículo (`textproc.py`)
- Limpieza de HTML, minúsculas, sin tildes, stopwords en español.
- Stemming ligero (`gobiernos`/`gobierna` → `gobiern`).
- **Sinónimos de titular**: `baja / rebaja / recorta` → mismo rasgo; `destituye / despide / cesa` → mismo rasgo.
- **Siglas**: `Banco Central Europeo` ≡ `BCE`, `Alianza Atlántica` ≡ `OTAN`, `Real Madrid`, etc.
- **Entidades**: nombres propios y siglas (`Pedro Sánchez`, `Courtois`, `Aemet`).
- Pesos: titular ×2,5, entradilla ×1, entidades +2, bigramas del titular +1,5.

### 2. ¿Noticia nueva o existente? (`clustering.py`)
Cada artículo se convierte en un vector TF-IDF (IDF calculado con lo publicado en las
últimas 72 h) y se compara con todas las noticias activas:

| señal | peso | para qué |
|---|---|---|
| coseno con el **centroide** de la noticia | 0,45 | de qué trata la noticia en conjunto |
| coseno **máximo** con cualquiera de sus artículos | 0,35 | enlaza con la versión más parecida aunque la noticia haya evolucionado |
| solape de **entidades recurrentes** | 0,20 | mismos protagonistas |

- Puntuación ≥ `NEWS_JOIN_THRESHOLD` (0,24) → se **añade** a la noticia y se actualizan sus fuentes.
- Si no → **noticia nueva**.
- Compartir solo un nombre propio no basta (dos noticias distintas sobre Sánchez o el Real Madrid no se mezclan).
- Tras cada ciclo, dos noticias cuyos centroides se parezcan ≥ 0,50 se **fusionan** (la URL antigua redirige a la nueva).
- Una noticia sin artículos nuevos en 72 h se cierra.

### 3. Relevancia
`(suma del peso de los medios distintos + 0,3 × medios que publicaron en las últimas 6 h) × decaimiento`
con vida media de 10 h. Una noticia que cubren muchos medios y sigue moviéndose sube; una vieja baja sola.

### 4. Redacción con IA (`writer.py`)
Solo cuando la noticia tiene ≥2 medios y ha ganado medios desde la última redacción (como mucho
una vez cada 10 min por noticia y 8 por ciclo). Recibe un artículo por medio (titular + extracto),
con instrucciones de no inventar datos y atribuir discrepancias. Devuelve titular, entradilla y cuerpo.

### 5. Cobertura internacional (`intl.py`, `countries.json`)
Sin IA. Si una noticia relevante (≥3 medios) trata de otro país —su nombre, gentilicio,
capital o dirigentes aparecen en al menos el 40% de los artículos— se buscan en la
edición de Google Noticias de ese país los nombres propios de la noticia que se escriben
igual en cualquier idioma (Trump, Merz, Volkswagen…), con las siglas traducidas
(OTAN→NATO, UE→EU…). Solo se aceptan titulares que contengan esos nombres, uno por medio.
Países incluidos: Estados Unidos, Reino Unido, Alemania, Francia, Italia, Portugal, México
y Argentina; se añaden más en `countries.json`. Esos titulares se muestran en la web y se
pasan a la IA para que contraste cómo lo cuenta la prensa de ese país.

### 6. Evolución de la noticia (pestaña desplegable)
Cada noticia tiene una línea de tiempo construida casi entera sin IA: primera publicación,
medios que se suman (agrupados por media hora, con su titular), información nueva de un
medio que ya la cubría y llegada de la prensa extranjera. Cada vez que la IA reescribe la
noticia, en esa misma llamada (sin coste extra) devuelve una frase con la novedad respecto
a la versión anterior; si no hay nada sustancial, no se añade al timeline. Las versiones
se guardan en la tabla `story_updates`.

### 7. Canal de Telegram (`telegram.py`)
Sin IA adicional: reutiliza lo que ya redacta la IA.
- Cuando una noticia alcanza 4 medios (`TELEGRAM_MIN_SOURCES`) se publica titular,
  entradilla, medios que la cubren, banderas de la prensa extranjera y enlace a la web.
- Cada novedad que la IA detecta se publica como **respuesta** al mensaje original
  (como mucho una por noticia cada 30 min).
- Límites: 3 noticias nuevas y 4 actualizaciones por pasada. Al activar el canal se
  publican solo las 3 principales; si se pierde la base de datos no se repite nada.

Configuración: crear un bot con @BotFather, añadirlo como administrador del canal y
guardar en GitHub los secretos `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` (`@nombre_del_canal`).

### 8. Última hora con un solo medio (`breaking.py`)
Sin IA. Una noticia es de última hora si un medio la titula "Última hora" o "Urgente"
(sin contar los directos recurrentes) o si 3 medios la publican en menos de 45 minutos.
Se muestra en la web y se publica en Telegram aunque solo la tenga un medio, con un
check ✓ "pendiente de confirmar" y el titular original citando al medio. Cuando otros
medios la confirman, la IA la redacta (tiene prioridad) y en Telegram se responde al
mensaje original con la versión confirmada ✓✓.

### 9. «Qué dicen los lectores» (`youtube.py`)
Para las noticias de 4 medios o más (y las de última hora) se busca su vídeo en YouTube
con la API oficial, aceptando solo canales de medios españoles cuyo título encaje con la
noticia, y se leen sus comentarios más valorados (solo el texto, sin autores). Cuando hay
al menos 15, la IA resume en 2-3 frases neutrales lo que opinan los lectores; el resumen
se rehace como mucho cada 2 horas y solo si llegan bastantes comentarios nuevos.
Se respeta el cupo gratuito de YouTube (100 búsquedas al día). Secreto: `YOUTUBE_API_KEY`.

## Configuración (variables de entorno)

| variable | por defecto | |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | sin ella, no se redacta (se muestra el titular original) |
| `NEWS_AI_MODEL` | `claude-haiku-5-5` | Haiku: ~0,05 céntimos por redacción |
| `NEWS_POLL_SECONDS` | 300 | frecuencia de lectura |
| `NEWS_JOIN_THRESHOLD` | 0.24 | más alto = más estricto (más noticias separadas) |
| `NEWS_MERGE_THRESHOLD` | 0.50 | fusión de noticias duplicadas |
| `NEWS_AI_MIN_SOURCES` | 2 | medios mínimos para redactar |
| `NEWS_DB` | `data/noticias.db` | |
| `NEWS_PORT` | 8000 | |

Los medios están en `feeds.json` (nombre, URL del RSS y peso para la relevancia). Las URL de
RSS cambian de vez en cuando: ejecuta `python worker.py --check-feeds` y corrige las que fallen.

## Tests

```bash
python -m unittest discover -s tests -t .
```
- `test_clustering`: 25 titulares inventados de 10 historias, con trampas (dos noticias del Real
  Madrid, dos de Sánchez, la DANA de Valencia frente al Valencia CF). Se prueban 20 órdenes de
  llegada aleatorios: ninguna noticia se mezcla ni se parte. Umbral válido observado: 0,20–0,28.
- `test_end_to_end`: feeds RSS locales, tres ciclos del worker (llegada de la primera pieza, llegada
  del resto que se añade a las existentes, ciclo sin cambios que no vuelve a llamar a la IA) y el servidor HTTP.

## API

- `GET /api/stories?min_sources=2&hours=48&q=texto&limit=40`
- `GET /api/stories/<id>`: noticia con todos sus artículos (marca los llegados después de la última redacción)
- `GET /api/status`: estado de cada medio

(En GitHub Pages no hay API: la web lee `data/stories.json` y filtra en el navegador.)

## Producción

Ejecuta `worker.py` y `server.py` como servicios (systemd, Docker…) detrás de un proxy
(nginx/Caddy) con HTTPS. SQLite en modo WAL aguanta sin problema un worker escribiendo y la web leyendo.
Respeta las condiciones de uso de cada medio: solo se guardan titular, extracto y enlace al original.
