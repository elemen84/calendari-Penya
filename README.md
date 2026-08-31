# Penya Calendar Sync

Sistema pequeño y mantenible que obtiene los partidos oficiales del primer equipo masculino del Joventut de Badalona y genera un feed ICS público.

Incluye únicamente:

- Liga Endesa / ACB.
- Basketball Champions League / BCL.

No usa servidor permanente, Railway, base de datos ni frontend. GitHub Actions ejecuta el script una vez al día; el script solo genera una nueva versión si han transcurrido al menos 24 horas desde la última sincronización correcta.

## Fuentes oficiales

Los adapters están en `src/providers/` y el resto del proyecto solo consume el modelo normalizado `Game`.

### ACB

Se inspeccionó la página oficial [Calendario Liga Endesa](https://www.acb.com/es/liga/calendario). Es una aplicación Next.js que usa una API estructurada pública desde el navegador. El adapter usa:

- Página humana: `https://www.acb.com/es/liga/calendario`.
- Calendario: `https://api2.acb.com/api/seasondata/Calendar/season-calendar`.
- Clasificación: `https://api2.acb.com/api/seasondata/Competition/standings`.
- Parámetros: `competitionId=1`, `editionId` de la temporada y, para un snapshot histórico, `roundId`.

La respuesta de calendario proporciona IDs estables de partido, temporada, jornada, equipos, fecha/hora y estado. La API actual no proporciona un pabellón fiable en ese payload; por eso el adapter deja `venue` vacío en ACB en vez de inventar una dirección o recinto.

### BCL

La URL histórica indicada por el proyecto redirige a la web oficial actual: [Champions League Basketball - Games](https://www.championsleague.basketball/en/games). La página expone el ID de competición en `data-event-id`; después el adapter consume la API estructurada que utiliza esa página:

- Página humana: `https://www.championsleague.basketball/en/games`.
- API: `https://digital-api.fiba.basketball/hapi/getgdapgamesbycompetitionid`.
- Parámetro: `gdapCompetitionId`.

El adapter filtra competición BCL masculina senior y el primer equipo de la Penya. Usa los IDs de partido, fase, grupo, fecha/hora, estado y `venueName` entregados por la fuente. Las descripciones BCL nunca contienen clasificación.

Las claves públicas que requieren los frontends oficiales se mantienen como defaults en los adapters. Se pueden sustituir con `ACB_API_KEY` y `BCL_APIM_SUBSCRIPTION_KEY` si las webs cambian sus claves.

## Arquitectura

```text
ACB + BCL -> GitHub Action -> public/penya.ics -> GitHub Pages -> suscripciones
```

```text
scripts/sync_calendar.py
        |
        +-- providers/acb.py  -> ACBData + Game
        +-- providers/bcl.py  -> BCLData + Game
        +-- standings/snapshots.py
        +-- calendar/ics.py -> public/penya.ics
        +-- data/sync-state.json
```

`Game` contiene competición, temporada, jornada, fase, equipos, fecha/hora, zona horaria `Europe/Madrid`, recinto, estado, URL e ID de fuente. Los aliases de Joventut/Penya se normalizan antes de filtrar.

La identidad es determinista: `competition + season + source_game_id`, con fallback a jornada y equipos normalizados. El UID del feed usa `<source-key>@penya-calendar`; cambiar hora, fecha, rival o pabellón no duplica el partido.

No se eliminan partidos del feed por una respuesta vacía o incompleta: la ejecución falla de forma segura antes de sobrescribir archivos generados. Los cambios de estado se reflejan en el título del evento.

## Clasificación ACB y snapshots congelados

Los partidos ACB incluyen la clasificación disponible. Cuando una jornada está completa según los estados oficiales, se consulta su clasificación específica y se guarda una sola vez en:

```text
data/standings/2026-27/round-01.json
data/standings/2026-27/round-02.json
```

`save_if_absent` no sobrescribe snapshots existentes. Por ello un partido de una jornada terminada conserva el contexto de esa jornada, mientras que un partido futuro o una jornada en curso usa la clasificación más reciente disponible. Si todavía no hay clasificación, la descripción dice `Clasificación todavía no disponible`.

## Configuración local

Se requiere Python 3.12.

```bash
VENV_DIR=/tmp/penya-calendar-venv
python3.12 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
```

Se puede usar `.venv` en un checkout cuyo path no contenga `:`. En macOS, Python puede rechazar un entorno virtual dentro de este proyecto porque el nombre de la carpeta contiene ese separador; por eso el ejemplo usa `/tmp`.

El script obtiene los datos reales al ejecutarse. Para consultar las fuentes y generar `public/penya.ics`:

```bash
python scripts/sync_calendar.py --dry-run --force
```

`--force` ignora el límite de 24 horas. Sin `--force`, una ejecución posterior a la última correcta dentro de 24 horas termina limpiamente. `--dry-run` consulta las fuentes y genera el ICS sin guardar el estado ni snapshots.

También se puede establecer `PENYA_SEASON_START_YEAR=2026` para fijar explícitamente la temporada. Si no se establece, ACB selecciona la temporada actual publicada.

## GitHub Actions

La ejecución normal no necesita secrets. Las variables `PENYA_SEASON_START_YEAR`, `ACB_API_KEY` y `BCL_APIM_SUBSCRIPTION_KEY` son opcionales; los adapters tienen valores públicos por defecto.

El workflow `.github/workflows/sync-calendar.yml` ejecuta el proceso diariamente a las `04:15 UTC`. Eso corresponde a las `06:15` en horario de verano de Madrid y a las `05:15` en horario de invierno. GitHub Actions cron funciona en UTC y no sigue automáticamente el cambio de hora; la ejecución diaria y el control interno de 24 horas evitan depender de una expresión cron incorrecta alrededor del cambio de mes.

El workflow tiene `workflow_dispatch`; marca `force` para forzar una sincronización manual. Tras una sincronización completa, solo se hace commit si han cambiado `data/sync-state.json`, snapshots o `public/penya.ics`.

Para que el workflow pueda hacer commit y publicar, la configuración del repositorio debe permitir que `GITHUB_TOKEN` escriba contenido (**Settings → Actions → General → Workflow permissions → Read and write permissions**).

## Landing pública y GitHub Pages

La landing está en `public/index.html`, con sus estilos y comportamiento en `public/styles.css` y `public/app.js`. El mismo directorio contiene `penya.ics`, por lo que GitHub Pages publica la landing y el feed desde el mismo artefacto. La interfaz pública solo ofrece suscripción: Google Calendar mediante la URL HTTPS del feed (guía manual en el modal) y Apple Calendar mediante una URL `webcal://`. No se usa ninguna API de calendario.

El feed de Penya se regenera aproximadamente cada 24 horas. Google Calendar y Apple Calendar deciden por su cuenta cuándo refrescan un calendario suscrito; la landing no promete una actualización visible exacta cada 24 horas en el dispositivo del usuario.

El escut de la landing es opcional: si se añade `public/assets/penya-shield.png`, se muestra automáticamente; si no está presente, la interfaz utiliza un fallback discreto.

Puesta en producción:

1. Tener el repositorio en GitHub.
2. En **Settings → Pages**, seleccionar **GitHub Actions** como fuente.
3. En **Settings → Actions → General**, habilitar permisos de escritura para el workflow.
4. Ejecutar `Sync Penya calendar` desde **Actions → Run workflow**; marcar `force` para regenerar inmediatamente.

Con usuario y repositorio reales, las URLs esperadas son:

```text
Landing:  https://<usuario>.github.io/<repo>/
Calendari: https://<usuario>.github.io/<repo>/penya.ics
WebCal:   webcal://<usuario>.github.io/<repo>/penya.ics
Google:   https://calendar.google.com/calendar/r?cid=<URL_ENCODED_DE_LA_URL_HTTPS>
```

La landing calcula automáticamente estas URLs a partir del dominio y la ruta donde GitHub Pages la sirve; no hay que editar el HTML al cambiar el nombre del repositorio.

## ICS

Cada ejecución que pasa el control de 24 horas genera `public/penya.ics`, incluso en dry-run. Los UID tienen la forma `<source-key>@penya-calendar` y no cambian cuando cambia la hora del partido. GitHub Pages sirve ese archivo como feed público para las suscripciones.

## Tests, lint y diagnóstico

```bash
pytest
ruff check .
mypy src scripts
git diff --check
```

Los tests usan fixtures locales y no necesitan credenciales. Para depurar un fallo, revisa el log de Actions y reproduce localmente con `--dry-run --force`. El script valida la forma de las respuestas, usa timeout y retries con backoff para HTTP y nunca interpreta cero partidos como una eliminación masiva.

## Cambiar de temporada

Normalmente basta con dejar que ACB seleccione la temporada actual. Para fijarla explícitamente:

```bash
PENYA_SEASON_START_YEAR=2027 python scripts/sync_calendar.py --dry-run --force
```

Antes de cambiar de temporada en producción, revisa el dry-run y conserva los snapshots de temporadas anteriores. La identidad incluye la temporada, por lo que una nueva temporada no colisiona con los eventos anteriores.
