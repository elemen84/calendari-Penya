# Penya Calendar Sync

Sistema pequeño y mantenible que obtiene los partidos oficiales del primer equipo masculino del Joventut de Badalona y los sincroniza con Google Calendar y un calendario ICS.

Incluye únicamente:

- Liga Endesa / ACB.
- Basketball Champions League / BCL.

No usa servidor permanente, Railway, base de datos ni frontend. GitHub Actions ejecuta el script una vez al día; el script solo sincroniza si han transcurrido al menos 48 horas desde la última sincronización correcta.

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

Las claves públicas que requieren los frontends oficiales se mantienen como defaults en los adapters; no son credenciales de Google. Se pueden sustituir con `ACB_API_KEY` y `BCL_APIM_SUBSCRIPTION_KEY` si las webs cambian sus claves.

## Arquitectura

```text
scripts/sync_calendar.py
        |
        +-- providers/acb.py  -> ACBData + Game
        +-- providers/bcl.py  -> BCLData + Game
        +-- standings/snapshots.py
        +-- calendar/google_calendar.py
        +-- calendar/ics.py -> public/penya.ics
        +-- data/sync-state.json
```

`Game` contiene competición, temporada, jornada, fase, equipos, fecha/hora, zona horaria `Europe/Madrid`, recinto, estado, URL e ID de fuente. Los aliases de Joventut/Penya se normalizan antes de filtrar.

La identidad es determinista: `competition + season + source_game_id`, con fallback a jornada y equipos normalizados. Se guarda en `extendedProperties.private.penya_source_key`; cambiar hora, fecha, rival o pabellón actualiza el mismo evento.

No se borran eventos automáticamente. Una respuesta vacía o incompleta de una fuente hace fallar la ejecución de forma segura antes de tocar Google Calendar. Un aplazamiento conserva el evento existente y lo marca como `⚠️ APLAZADO`; una cancelación se marca como `❌ CANCELADO`.

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

El script obtiene los datos reales al ejecutarse. Para consultar fuentes y generar `public/penya.ics` sin modificar Google Calendar:

```bash
python scripts/sync_calendar.py --dry-run --force
```

`--force` ignora el límite de 48 horas. Sin `--force`, una ejecución posterior a la última correcta dentro de 48 horas termina limpiamente. En dry-run no hacen falta credenciales de Google; reportará las acciones de calendario como no disponibles.

Para una sincronización real local se necesitan las dos variables siguientes:

```bash
export GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
export GOOGLE_CALENDAR_ID='...'
python scripts/sync_calendar.py --force
```

También se puede establecer `PENYA_SEASON_START_YEAR=2026` para fijar explícitamente la temporada. Si no se establece, ACB selecciona la temporada actual publicada.

## Google Cloud y Google Calendar

1. En [Google Cloud Console](https://console.cloud.google.com/), crea un proyecto o selecciona uno existente.
2. En **APIs & Services → Library**, activa **Google Calendar API**.
3. En **IAM & Admin → Service Accounts**, crea una Service Account.
4. Abre esa cuenta, entra en **Keys → Add key → Create new key → JSON** y descarga el JSON. Guárdalo fuera del repositorio; no lo subas a Git.
5. En Google Calendar crea un calendario nuevo, por ejemplo `Penya - Joventut`.
6. En la configuración de ese calendario, en **Compartir con personas o grupos**, añade el email de la Service Account y dale permiso **Make changes to events**.
7. Copia el ID del calendario desde **Integrate calendar → Calendar ID**.

La Service Account no hereda tus calendarios personales: el paso 6 es obligatorio. El calendario quedará disponible para compartir después con las personas que quieras.

## GitHub Actions

En el repositorio, abre **Settings → Secrets and variables → Actions** y crea estos **Repository secrets**:

- `GOOGLE_SERVICE_ACCOUNT_JSON`: contenido completo del JSON descargado.
- `GOOGLE_CALENDAR_ID`: ID del calendario.

Opcionalmente, como **Repository variables**, se pueden definir `PENYA_SEASON_START_YEAR`, `ACB_API_KEY` y `BCL_APIM_SUBSCRIPTION_KEY`; normalmente no hace falta porque los adapters tienen los valores públicos usados por las webs oficiales.

El workflow `.github/workflows/sync-calendar.yml` ejecuta el proceso diariamente a las `04:15 UTC`. Eso corresponde a las `06:15` en horario de verano de Madrid y a las `05:15` en horario de invierno. GitHub Actions cron funciona en UTC y no sigue automáticamente el cambio de hora; la ejecución diaria y el control interno de 48 horas evitan depender de una expresión `*/2` incorrecta alrededor del cambio de mes.

El workflow tiene `workflow_dispatch`; marca `force` para forzar una sincronización manual. Tras una sincronización completa, solo se hace commit si han cambiado `data/sync-state.json`, snapshots o `public/penya.ics`.

Para que el workflow pueda hacer push, la configuración del repositorio debe permitir que `GITHUB_TOKEN` escriba contenido (**Settings → Actions → General → Workflow permissions → Read and write permissions**). En pull requests desde forks no se exponen estos secretos.

## Landing pública y GitHub Pages

La landing está en `public/index.html`, con sus estilos y comportamiento en `public/styles.css` y `public/app.js`. El mismo directorio contiene `penya.ics`, por lo que GitHub Pages publica la landing y el calendario desde el mismo artefacto. La interfaz pública solo ofrece suscripción: Google Calendar abre su URL `cid` y Apple/otros calendarios reciben una URL `webcal://`.

Para activarlo manualmente una sola vez:

1. En GitHub abre **Settings → Pages**.
2. En **Build and deployment → Source**, selecciona **GitHub Actions**.
3. Guarda la configuración y ejecuta el workflow `Sync Penya calendar` una vez desde **Actions → Run workflow**; marca `force` si quieres regenerar inmediatamente.

Con usuario y repositorio reales, las URLs esperadas son:

```text
Landing:  https://<usuario>.github.io/<repo>/
Calendari: https://<usuario>.github.io/<repo>/penya.ics
WebCal:   webcal://<usuario>.github.io/<repo>/penya.ics
Google:   https://calendar.google.com/calendar/r?cid=<URL_ENCODED_DE_LA_URL_HTTPS>
```

La landing calcula automáticamente estas URLs a partir del dominio y la ruta donde GitHub Pages la sirve; no hay que editar el HTML al cambiar el nombre del repositorio.

## ICS

Cada ejecución que pasa el control de 48 horas genera `public/penya.ics`, incluso en dry-run. Los UID tienen la forma `<source-key>@penya-calendar` y no cambian cuando cambia la hora del partido. Se puede publicar ese archivo desde GitHub Pages o servirlo desde cualquier hosting estático como fallback, pero la sincronización principal usa Google Calendar API.

## Tests, lint y diagnóstico

```bash
pytest
ruff check .
mypy src scripts
git diff --check
```

Los tests mockean Google Calendar y usan fixtures locales: no necesitan credenciales reales. Para depurar un fallo, revisa el log de Actions y reproduce localmente con `--dry-run --force`. El script valida la forma de las respuestas, usa timeout y retries con backoff para HTTP y nunca interpreta cero partidos como una eliminación masiva.

## Cambiar de temporada

Normalmente basta con dejar que ACB seleccione la temporada actual. Para fijarla explícitamente:

```bash
PENYA_SEASON_START_YEAR=2027 python scripts/sync_calendar.py --dry-run --force
```

Antes de cambiar de temporada en producción, revisa el dry-run y conserva los snapshots de temporadas anteriores. La identidad incluye la temporada, por lo que una nueva temporada no colisiona con los eventos anteriores.
