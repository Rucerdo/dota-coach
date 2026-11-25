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
- **En directo** (`coach run`): overlay sobre Dota con 1-2 consejos en los momentos que importan: al empezar,
  al detectar un enemigo nuevo, al morir, cuando ya te llega el oro para el siguiente objeto, y cada pocos minutos.
  Opcionalmente los lee en voz alta.

Sin IA funciona con reglas y estadísticas. Con IA (Claude, ChatGPT, Gemini, Groq, OpenRouter, DeepSeek o un modelo
local) los consejos se adaptan al estado concreto de la partida.

## Empezar

```powershell
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py meta
.venv\Scripts\python run.py install      # integración GSI en Dota (reinicia Dota una vez)
.venv\Scripts\python run.py run          # modo en directo (Dota en "Ventana sin bordes")
```

IA opcional (la clave se guarda cifrada con tu usuario de Windows; también vale `ANTHROPIC_API_KEY`):

```powershell
.venv\Scripts\python run.py ai set claude --key sk-ant-...
.venv\Scripts\python run.py ai test
.venv\Scripts\python run.py meta --review --ai   # analiza las notas del parche (una vez por parche) y resume el meta
```

Ajustes en `%APPDATA%\DotaCoach\config.json`: rango (`rank_bracket`: 1 Herald … 8 Immortal), rol
(`auto`/`core`/`support`), voz (`tts`), posición del overlay, frecuencia de consejos.

## De dónde salen los datos

| Dato | Fuente |
|---|---|
| Tu héroe, nivel, oro, objetos, muertes, reloj | Game State Integration (API oficial de Dota) |
| Héroes enemigos | Minimapa de GSI (si Dota lo envía), barra superior (visión) o `--enemies` |
| Notas de parche | `dota2.com/datafeed/patchnotes` (JSON oficial de Valve) |
| Winrates por rango y tendencia | OpenDota `heroStats` |
| Matchups | OpenDota `heroes/{id}/matchups` (muestra pro, pequeña: se suaviza) |
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
- `coach vision strip` guarda los 10 recortes para comprobar la calibración (usa las mismas claves `topbar` que el
  traductor).

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
  ui/        overlay, tts
  gsi.py, dota.py, live.py, cli.py
```

## Pendiente

- Probar y ajustar la visión con capturas reales (umbrales, calibración por resolución).
- Ventana de ajustes (customtkinter, como el traductor) y empaquetado `.exe`.
- Leer los objetos enemigos (scoreboard / panel al seleccionarlos).
- Análisis post-partida con la repetición / OpenDota.
