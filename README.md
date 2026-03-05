# Google Forms Bot — Respuestas Mexicanas 🇲🇽

## Bot en Python que rellena formularios de Google Forms automáticamente con datos aleatorios y nombres mexicanos. Incluye seguridad avanzada y anti-detección.

---

## Instalación

```bash
pip install -r requirements.txt
```

> Requiere **Google Chrome** instalado. El driver se descarga automáticamente.

---

## Seguridad

| Característica | Descripción |
|---|---|
| **Validación de URL** | Solo acepta URLs válidas de Google Forms (`docs.google.com/forms/d/e/...`) |
| **Rate Limiting** | Intervalo mínimo entre envíos + límite máximo por sesión (500) |
| **Config Validation** | Verifica tipos, rangos y claves válidas en `config.json` |
| **Secure Logging** | Enmascara IDs de formulario en logs (muestra solo primeros 8 caracteres) |
| **Anti-Detección** | User-agent aleatorio, viewport aleatorio, idioma aleatorio, fingerprint CDP |
| **Proxy** | Soporte para HTTP/HTTPS/SOCKS4/SOCKS5 |
| **Graceful Shutdown** | Limpieza segura del driver con SIGINT/SIGTERM (Ctrl+C) |
| **Driver Retry** | 3 reintentos automáticos si falla la inicialización del driver |
| **Input Sanitization** | Elimina caracteres de control y limita longitud de texto inyectado |

---

## Uso

### Comando básico
```bash
python bot.py --url "https://docs.google.com/forms/d/e/FORM_ID/viewform" --count 10
```

### Con navegador visible (para depurar)
```bash
python bot.py --url "URL" --count 5 --no-headless
```

### Con proxy
```bash
python bot.py --url "URL" --count 10 --proxy "socks5://127.0.0.1:1080"
```

### Con archivo de configuración
```bash
python bot.py --config config.json
```

### Opciones disponibles
| Opción | Descripción | Default |
|---|---|---|
| `--url` | URL del formulario | requerido |
| `--count` | Número de respuestas (1-500) | 1 |
| `--delay` | Espera entre respuestas (seg, min: 1) | 3 |
| `--no-headless` | Muestra el navegador | oculto |
| `--config` | Archivo JSON de config | — |
| `--proxy` | Proxy HTTP/SOCKS5 | — |
| `--max-submissions` | Límite máximo por sesión | 500 |

---

## Tipos de pregunta soportados

| Tipo | Descripción |
|---|---|
| **Radio** | Opción múltiple — elige una opción aleatoria |
| **Radio + Otro** | Opción múltiple con "Otro" — 20% de probabilidad de escribir texto libre |
| **Checkbox** | Casillas — selecciona 1-3 opciones al azar |
| **Escala lineal** | 1-5, 1-10 — con peso hacia valores medios-altos |
| **Texto corto** | Detecta nombre/email/teléfono/edad/estado/fecha/empresa/ocupación/CP |
| **Párrafo** | Texto largo con frases naturales en español |
| **Dropdown** | Selecciona una opción del menú |
| **Grid (radio)** | Cuadrícula de opciones por fila (radio buttons) |
| **Grid (checkbox)** | Cuadrícula de opciones por fila (checkboxes, 1-2 por fila) |
| **Fecha** | Fecha aleatoria (últimos 5 años), soporta formato DD/MM/AAAA separado |
| **Hora** | Hora aleatoria (preferencia horario laboral), formato HH:MM |
| **Subida de archivo** | Detectada y omitida con advertencia (no se puede automatizar) |

---

## 🇲🇽 Datos generados

- **Nombres**: combinación de 40 nombres + 40 apellidos comunes mexicanos
- **Emails**: basados en el nombre + dominio `.com.mx`
- **Teléfonos**: con LADA de ciudades principales (55, 33, 81, etc.)
- **Estados**: 15 estados de la República Mexicana
- **Empresas**: UNAM, IPN, Telmex, PEMEX, Banorte, etc.
- **Ocupaciones**: Ingeniero, Médico, Abogado, Programador, etc.
- **Código postal**: 5 dígitos aleatorios
- **Fechas**: últimos 5 años
- **Horas**: preferencia por horario laboral (8:00-20:00)
- **Textos**: respuestas abiertas naturales en español

---

## Logs

Toda la actividad se guarda en `bot.log` y se muestra en consola. Los IDs de formulario se enmascaran automáticamente:

```
2024-01-15 10:23:01 [INFO] Bot iniciado | URL: https://docs.google.com/forms/d/e/1FAIpQLSe*********************/viewform
2024-01-15 10:23:01 [INFO] Respuestas a enviar: 10 | Headless: True
2024-01-15 10:23:01 [INFO] Seguridad: Rate limit=3.0s | Max envíos=500
──────────────────────────────────────────────────
2024-01-15 10:23:03 [INFO] Respuesta #1 | Nombre: Carlos Hernández García
  Página 1:
  Preguntas detectadas: 9
  Q1 [radio]: ¿Qué dispositivo utiliza...
  Q2 [grid]: Califique la importancia...
  Q3 [checkbox_grid]: Seleccione los horarios...
  Q4 [date]: Fecha de nacimiento
  Q5 [time]: Hora preferida
  Q6 [radio_other]: ¿Cuál es su ocupación?
  ✓ Formulario enviado
```

---

## config.json

```json
{
  "url": "https://docs.google.com/forms/d/e/FORM_ID/viewform",
  "count": 20,
  "delay_min": 3.0,
  "delay_max": 8.0,
  "headless": true,
  "timeout": 20,
  "proxy": null,
  "max_submissions": 500,
  "user_agents": [],
  "field_overrides": {}
}
```

| Campo | Descripción | Límites |
|---|---|---|
| `url` | URL del formulario | Solo `docs.google.com/forms` |
| `count` | Respuestas a enviar | 1–500 |
| `delay_min` | Delay mínimo entre envíos (seg) | ≥ 1.0 |
| `delay_max` | Delay máximo entre envíos (seg) | > delay_min |
| `timeout` | Timeout para carga de página (seg) | 5–120 |
| `proxy` | Proxy HTTP/SOCKS5 | `null` o `"protocol://host:port"` |
| `max_submissions` | Hard cap por sesión | ≤ 500 |
| `user_agents` | Lista custom de User-Agents | `[]` = 7 por defecto |

---

##  Notas

- Solo funciona con formularios **sin autenticación** de Google.
- El delay aleatorio entre respuestas simula comportamiento humano.
- Usa `--no-headless` para ver qué hace el bot en tiempo real.
- Si el formulario tiene múltiples páginas, el bot las navega automáticamente.
- Presiona **Ctrl+C** para detener el bot de forma segura (cierra el driver limpiamente).
- Las preguntas de **subida de archivo** se omiten automáticamente con advertencia.
- El bot usa **anti-detección**: viewport aleatorio, user-agent rotativo, y eliminación de fingerprints de automatización.
