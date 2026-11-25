# Dota Coach

Asistente de Dota 2 para mejorar jugando: te dice qué comprar, cómo counterear a los enemigos y qué héroe elegir,
**teniendo en cuenta el parche actual**: lee las notas oficiales de Valve, detecta buffs y nerfs y los cruza con
las winrates reales y su tendencia.

> Proyecto hermano de [Dota Chat Translator](../dota-translator): reutiliza su integración GSI, la captura de la
> barra superior y el enfoque multi-proveedor de IA.

## Qué hace

- **Meta del parche** (`coach meta`): combina las notas oficiales del ciclo actual (p. ej. 7.42 + 7.42a), la winrate
  en tu rango y su tendencia reciente (OpenDota) para decir qué héroes y objetos están fuertes y cuáles han bajado.
  Con IA, relee las notas y escribe un resumen del meta con consejos para subir.
- **Notas de parche clasificadas** (`coach patch --hero pa`): cada línea marcada como BUFF, NERF o REWORK.
- **Draft** (`coach draft --enemies "pa, lion"`): candidatos puntuados por matchups y por el meta actual.
- **Objetos** (`coach items --hero jugg --enemies "pa, lion, riki"`): counters según los rasgos de los enemigos
  (evasión → MKB, invisibles → polvo/sentries, daño mágico → BKB/Glimmer…), lo que de verdad se compra con tu héroe y
  cómo le ha afectado el parche a cada objeto.
- **En directo** (`coach run`): el panel de partida (abajo) con consejos en los momentos que importan: al empezar,
  al detectar un enemigo nuevo, al morir, cuando ya te llega el oro para el siguiente objeto, y cada pocos minutos;
  avisos del mapa (enemigo desaparecido de tu línea, ganks, TPs), de runas y de puntos de habilidad sin gastar.
  Opcionalmente los lee en voz alta.
- **Selección de héroes**: en el draft, los mejores picks contra lo que ya han elegido los rivales.
- **Después de la partida** (`coach report`, `coach history`): informe con tus muertes (dónde y si te pillaron
  desde la niebla), últimos golpes al minuto 10, tiempos de objetos y percentiles frente a otros jugadores de tu
  héroe (OpenDota); con IA, sus 3 consejos principales. El historial muestra lo que se repite partida tras partida.

Sin IA funciona con reglas y estadísticas. Con IA (Claude, ChatGPT, Gemini, Groq, OpenRouter, DeepSeek o un modelo
local) los consejos se adaptan al estado concreto de la partida.

## Empezar

```powershell
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py              # ventana de ajustes: IA, rol, GSI, arranque con Dota y "Iniciar coach"
# o doble clic en "Dota Coach.pyw" (sin ventana de consola)
```

Todo se puede hacer también desde la línea de órdenes:

```powershell
.venv\Scripts\python run.py meta
.venv\Scripts\python run.py install      # integración GSI en Dota (reinicia Dota una vez)
.venv\Scripts\python run.py run          # modo en directo (Dota en "Ventana sin bordes")
```

IA opcional (la clave se guarda cifrada con tu usuario de Windows; también vale `ANTHROPIC_API_KEY`). Desde la
ventana de ajustes o con:

```powershell
.venv\Scripts\python run.py ai set claude --key sk-ant-...
.venv\Scripts\python run.py ai test
.venv\Scripts\python run.py meta --review --ai   # analiza las notas del parche (una vez por parche) y resume el meta
```

Los ajustes se guardan en `%APPDATA%\DotaCoach\config.json`: rango (`rank_bracket`: 1 Herald … 8 Immortal), rol
(`auto`/`carry`/`core`/`support`), voz (`tts`), avisos del mapa y de runas, frecuencia de consejos.

En los ajustes, "Abrir el coach automáticamente al lanzar Dota" añade `coach autostart` al arranque de Windows de tu
usuario: espera a que se abra Dota, abre el coach y lo cierra (con el informe de la partida) al salir de Dota.

Ejecutable: `build.bat` genera `dist\DotaCoach.exe` (PyInstaller, sin consola; sin argumentos abre los ajustes).

## Panel de partida

Al iniciar el coach se abre una ventana aparte, al estilo de Dota Plus, pensada para un segundo monitor (cabe sin
scroll en ~1400x880). Nada se dibuja encima del juego.

- **Cabecera**: tu héroe, estadísticas con tu percentil frente a otros jugadores de tu héroe, reloj y cuenta atrás
  de runas, stackeo y día/noche.
- **Selección de héroes**: tu equipo, rivales y baneos, y los mejores picks contra ellos.
- **En partida**: tu inventario; la siguiente compra con sus componentes (los que ya llevas ✓, el orden del resto y
  "compra ahora"); la build por fases; las líneas (quién va con quién, según las posiciones de GSI); los enemigos
  con sus counters; partidas parecidas de OpenDota; el minimapa; los últimos consejos y avisos; tu héroe en el parche.
- **Fuera de partida**: el informe de tu última partida y el resumen de tu historial.
- **Torres y bajas**: la vida de tus torres, quién mata a quién, las rachas y lo que compran tus aliados.
- **Notificaciones flotantes** (desactivables) para lo importante: ganks, enemigo desaparecido de tu línea, TPs,
  torres atacadas o perdidas y rachas enemigas. Salen encima del juego, centradas justo debajo de los retratos, sin
  capturar el ratón (Dota en "Ventana sin bordes").
- El panel se abre maximizado en la pantalla secundaria si la hay.
- El panel cambia de tono según sea de día (cálido) o de noche (azulado) en la partida.

La build tiene en cuenta lo que llevas: no sugiere componentes de lo que ya está fabricado ni otras botas si ya tienes unas mejoradas, sigue tu ruta (Maelstrom → Mjollnir) y descuenta del precio lo que ya llevas.

## De dónde salen los datos

| Dato | Fuente |
|---|---|
| Tu héroe, nivel, oro, objetos, muertes, reloj | Game State Integration (API oficial de Dota) |
| Héroes enemigos y posiciones | Minimapa de GSI (los enemigos solo cuando tu minimapa los muestra), barra superior (visión) o `--enemies` |
| Tu rendimiento frente a tu héroe | OpenDota `benchmarks` |
| Partidas parecidas | OpenDota `findMatches` + `matches/{id}` |
| Notas de parche | `dota2.com/datafeed/patchnotes` (JSON oficial de Valve) |
| Winrates por rango y tendencia | OpenDota `heroStats` |
| Enfrentamientos y sinergias | STRATZ (partidas públicas de tu rango, con clave gratuita) o, de respaldo, OpenDota `heroes/{id}/matchups` y `explorer` (partidas pro: muestra pequeña, se suaviza) |
| Objetos populares por héroe | OpenDota `heroes/{id}/itemPopularity` |

Todo se guarda en caché (`%APPDATA%\DotaCoach\cache`): sin red se usa la última copia.

### Cómo "entiende" el parche

1. Cada línea de las notas se clasifica con heurísticas: "Cooldown decreased" es buff, "Evasion decreased" nerf,
   "Mana Cost rescaled from 100/110 to 90/120" compara medias, "Cooldown Reduction increased" es buff…
2. Por héroe y objeto se suma el saldo del ciclo de parches actual.
3. Se cruza con la winrate y su tendencia: un buff que además sube en winrate es una señal fuerte; un nerf a un
   héroe que sigue ganando, también.
4. Con IA (`meta --review`), se relee cada bloque de notas para juzgar reworks y cambios de mecánica que las
   heurísticas no entienden, con un veredicto y una frase por héroe/objeto que luego usan los consejos.

## Visión: héroes de la barra superior (experimental)

En modo jugador, GSI solo envía tus datos. Para saber contra quién juegas, el coach compara los retratos de la barra
superior con los oficiales. **Las arcanas y personas cambian el retrato**, así que:

- cada héroe puede tener varias plantillas: la oficial y las aprendidas (`cache\hero_img_learned\<héroe>\`);
- **aprende solo por descarte**: si en un bando queda un hueco sin reconocer y un único héroe conocido sin asignar
  (visto en el minimapa, indicado con `--enemies` o tu propio héroe), ese retrato es de ese héroe y se guarda;
- ante la duda el hueco queda como desconocido (nunca adivina) y el recorte se guarda para etiquetarlo:
  `coach vision unknown` y `coach vision label <archivo> "Phantom Assassin"`;
- `coach vision strip` guarda los 10 recortes de la pantalla para comprobar la calibración, y
  `coach vision test <captura|carpeta> --expect "h1,...,h10"` analiza capturas guardadas (F12 de Steam) sin
  abrir Dota. Calibrado con capturas reales a 1920x1080; en otras resoluciones escala con la altura.

## Reglas de Valve

GSI es una API oficial y el coach no lee la memoria del juego, así que VAC no lo detecta. Aun así, Valve ha restringido
apps que dan en partida ventajas o información que el juego no muestra. El coach solo usa información que ya ves
(tu estado, la barra superior, el minimapa) más estadísticas públicas, pero los consejos en directo pueden caer en
una zona gris: el modo en directo es para uso personal y bajo tu responsabilidad. `meta`, `patch`, `draft` e `items`
fuera de partida no tienen ese problema.

## Desarrollo

```powershell
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

Los tests no usan la red, ni tu `%APPDATA%`, ni el cfg real de Dota (usan `COACH_HOME` temporal y una carpeta de
Dota falsa).

```
coach/
  data/      gamedata (héroes/objetos), patches (notas de Valve), opendota, meta, cache
  engine/    counters (+ hero_traits.json editable), draft, advisor (cuándo y qué aconsejar)
  ai/        claude (SDK oficial), openai_compat (resto), prompts
  vision/    topbar (reconocimiento de retratos con plantillas aprendidas)
  engine/    + mapwatch (líneas y avisos), skills, timers, benchmarks, matchlog (informe e historial),
             draftlive, similar
  ui/        settings (ajustes), panel + view (panel de partida), overlay, tts
  autostart.py (abrir con Dota), tools/build_exe.py (.exe)
  gsi.py, dota.py, live.py, cli.py
```

## Pendiente

- Probar la visión en otras resoluciones y formatos (21:9, 16:10).
- Comprobar con una grabación qué secciones extra de GSI (draft, neutrales, roshan) llegan a un jugador.
- Leer los objetos enemigos (scoreboard / panel al seleccionarlos).
