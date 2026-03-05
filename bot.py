import argparse
import logging
import random
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from logging.handlers import RotatingFileHandler
from typing import Optional

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException, StaleElementReferenceException,
    TimeoutException, WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

import generators as gen
from config import BotConfig, MAX_RESPONSES, MIN_DELAY, ProxyRotator
from data import ACCEPT_LANGUAGES, VIEWPORT_SIZES


# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler("bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def _build_cdp_script(lang: str) -> str:
    """Genera el script CDP con el idioma que coincide con el User-Agent del driver."""
    lang_primary = lang.split("-")[0]   # "es-MX" → "es"
    return f"""
    Object.defineProperty(navigator, 'webdriver',  {{get: () => undefined}});
    Object.defineProperty(navigator, 'plugins',    {{get: () => [1,2,3,4,5]}});
    Object.defineProperty(navigator, 'languages',  {{get: () => ['{lang}','{lang_primary}','en']}});
    window.chrome = {{ runtime: {{}} }};
    const _orig = window.navigator.permissions.query;
    window.navigator.permissions.query = p =>
        p.name === 'notifications'
            ? Promise.resolve({{state: Notification.permission}})
            : _orig(p);
"""


# ── Bot ──────────────────────────────────────────────────────────
class GoogleFormsBot:

    # Selectores para encontrar las preguntas del formulario
    _Q_SELECTORS    = ['[data-params*="entry"]', '.freebirdFormviewerViewItemsItemItem', '.Qr7Oae']
    _HINT_SELECTOR  = '[role="heading"], .M7eMe'
    _SUBMIT_SELECTORS = [
        '[role="button"][jsname="M2UYVd"]',
        '.freebirdFormviewerViewNavigationSubmitButton',
        'div[role="button"]:last-of-type',
    ]
    _NEXT_SELECTORS = ['[jsname="OCpkoe"]', 'div[role="button"][data-id="next"]']
    _CONFIRM_SELECTOR = '.freebirdFormviewerViewResponseConfirmationMessage, .vHW8K'
    _LOAD_SELECTOR  = '.freebirdFormviewerViewItemList, .Qr7Oae, [data-params]'

    def __init__(self, config: BotConfig):
        self.config = config
        self.proxy_rotator = ProxyRotator(config.proxy_file) if config.proxy_file else None
        self._local = threading.local()
        self._active_drivers: list = []
        self._drivers_lock = threading.Lock()
        self._shutdown = False
        self._submissions = 0
        self._sub_lock = threading.Lock()
        self._handlers = self._build_handlers()   # callable map, sin getattr en runtime

        signal.signal(signal.SIGINT,  self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

    # ── Señales ──────────────────────────────────────────────────
    def _on_signal(self, signum, _frame):
        log.warning(f"Señal {signal.Signals(signum).name} recibida. Cerrando...")
        self._shutdown = True
        self._quit_all_drivers()
        import os
        os._exit(0)   # sys.exit() en un thread secundario solo lanza SystemExit en ese thread

    # ── Driver lifecycle ─────────────────────────────────────────
    def _init_driver(self, proxy: Optional[str] = None):
        if getattr(self._local, "driver", None):
            return

        ua     = random.choice(self.config.user_agents)
        lang   = random.choice(ACCEPT_LANGUAGES).split(",")[0]
        w, h   = random.choice(VIEWPORT_SIZES)

        opts = Options()
        if self.config.headless:
            opts.add_argument("--headless=new")
        for arg in ("--no-sandbox", "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled"):
            opts.add_argument(arg)
        opts.add_argument(f"--user-agent={ua}")
        opts.add_argument(f"--lang={lang}")
        opts.add_argument(f"--window-size={w},{h}")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        if proxy:
            opts.add_argument(f"--proxy-server={proxy}")

        for attempt in range(1, 4):
            try:
                driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
                driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
                                       {"source": _build_cdp_script(lang)})
                self._local.driver = driver
                self._local.wait   = WebDriverWait(driver, self.config.timeout)
                with self._drivers_lock:
                    self._active_drivers.append(driver)
                log.debug(f"Driver listo ({w}x{h})")
                return
            except WebDriverException as e:
                log.warning(f"Driver intento {attempt}/3 fallido: {e}")
                if attempt < 3:
                    time.sleep(2 * attempt)

        raise RuntimeError("No se pudo inicializar el driver después de 3 intentos")

    def _close_driver(self):
        driver = getattr(self._local, "driver", None)
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
            with self._drivers_lock:
                if driver in self._active_drivers:
                    self._active_drivers.remove(driver)
            self._local.driver = None
            self._local.wait = None

    def _quit_all_drivers(self):
        with self._drivers_lock:
            for d in self._active_drivers:
                try: d.quit()
                except Exception: pass
            self._active_drivers.clear()

    @property
    def _driver(self): return self._local.driver
    @property
    def _wait(self):   return self._local.wait

    # ── Helpers ──────────────────────────────────────────────────
    def _sleep(self, seconds: float):
        time.sleep(seconds * random.uniform(0.5, 1.3))

    def _scroll_click(self, element):
        self._driver.execute_script("arguments[0].scrollIntoView(true);", element)
        self._sleep(0.3)
        element.click()

    def _type(self, element, text: str):
        element.clear()
        for ch in text:
            element.send_keys(ch)
            time.sleep(random.uniform(0.03, 0.1))

    def _find(self, parent, css: str):
        return parent.find_elements(By.CSS_SELECTOR, css)

    # ── Detección de tipo de pregunta ────────────────────────────
    def _question_type(self, q) -> str:
        try:
            if self._find(q, '[data-file-upload], input[type="file"]'):
                return "file"
            if self._find(q, 'input[type="date"], [aria-label*="Día"], [aria-label*="Day"]'):
                return "date"
            if self._find(q, 'input[type="time"], [aria-label*="Hora"], [aria-label*="Hour"]'):
                return "time"
            # checkbox-grid: grupos que contienen checkboxes
            if any(
                self._find(g, '[role="checkbox"]')
                for g in self._find(q, '[role="group"]')
            ):
                return "checkbox_grid"

            radios = self._find(q, '[role="radio"]')
            if radios:
                vals = [r.get_attribute("data-value") for r in radios[:3]]
                if all(v and v.isdigit() for v in vals if v):
                    return "scale"
                if self._find(q, '[data-other-input], input[aria-label*="Otro"]'):
                    return "radio_other"
                return "radio"

            if self._find(q, '[role="checkbox"]'):   return "checkbox"
            if self._find(q, 'input[type="text"]'):  return "short_text"
            if self._find(q, 'textarea'):             return "paragraph"
            if self._find(q, '[role="radiogroup"]'): return "grid"
            if self._find(q, '[role="listbox"]'):    return "dropdown"
        except StaleElementReferenceException:
            pass
        return "unknown"

    # ── Handlers ─────────────────────────────────────────────────
    def _radio(self, q):
        opts = self._find(q, '[role="radio"]')
        if opts:
            self._scroll_click(random.choice(opts))

    def _radio_other(self, q):
        opts = self._find(q, '[role="radio"]')
        if not opts:
            return
        use_other = random.random() < 0.2
        if use_other:
            other = next(
                (o for o in opts if "otro" in (o.get_attribute("data-value") or o.text or "").lower()),
                opts[-1],
            )
            self._scroll_click(other)
            self._sleep(0.4)
            for inp in self._find(q, 'input[type="text"]'):
                if inp.is_displayed():
                    self._type(inp, gen.sanitize(gen.texto_otro()))
                    break
        else:
            normal = [o for o in opts if "otro" not in (o.get_attribute("data-value") or o.text or "").lower()]
            self._scroll_click(random.choice(normal or opts))

    def _checkbox(self, q):
        opts = self._find(q, '[role="checkbox"]')
        if not opts:
            return
        for chk in random.sample(opts, random.randint(1, min(3, len(opts)))):
            self._scroll_click(chk)

    def _short_text(self, q, hint: str):
        for inp in self._find(q, 'input[type="text"]'):
            self._type(inp, gen.sanitize(gen.texto_por_hint(hint)))

    def _paragraph(self, q, hint: str):
        for area in self._find(q, 'textarea'):
            self._type(area, gen.sanitize(gen.texto_por_hint(hint) or gen.texto()))

    def _dropdown(self, q):
        try:
            self._find(q, '[role="listbox"]')[0].click()
            self._sleep(0.4)
            valid = [o for o in self._find(q, '[role="option"]') if o.get_attribute("data-value")]
            if valid:
                random.choice(valid).click()
        except (IndexError, Exception) as e:
            log.debug(f"Dropdown error: {e}")

    def _scale(self, q):
        opts = self._find(q, '[role="radio"]')
        if opts:
            # Distribución ligeramente positiva
            weights = ([1, 2, 3, 5, 8, 8, 6, 4, 3, 2] + [1] * 10)[:len(opts)]
            self._scroll_click(random.choices(opts, weights=weights, k=1)[0])

    def _grid(self, q):
        for row in self._find(q, '[role="radiogroup"]'):
            opts = self._find(row, '[role="radio"]')
            if opts:
                self._scroll_click(random.choice(opts))

    def _checkbox_grid(self, q):
        for row in self._find(q, '[role="group"]'):
            chks = self._find(row, '[role="checkbox"]')
            if not chks:
                continue
            for chk in random.sample(chks, random.randint(1, min(2, len(chks)))):
                self._scroll_click(chk)

    def _date(self, q):
        date_str = gen.fecha()
        year, month, day = date_str.split("-")
        native = self._find(q, 'input[type="date"]')
        if native:
            try: native[0].send_keys(date_str); return
            except Exception: pass
        for label, value in [("Día|Day", day.lstrip("0")), ("Mes|Month", month.lstrip("0")), ("Año|Year", year)]:
            for lbl in label.split("|"):
                for inp in self._find(q, f'input[aria-label*="{lbl}"], input[placeholder*="{lbl}"]'):
                    try:
                        if inp.is_displayed():
                            inp.clear(); inp.send_keys(value); break
                    except Exception: pass

    def _time(self, q):
        h, m = gen.hora().split(":")
        native = self._find(q, 'input[type="time"]')
        if native:
            try: native[0].send_keys(f"{h}:{m}"); return
            except Exception: pass
        for label, value in [("Hora|Hour", h.lstrip("0") or "0"), ("Minuto|Minute", m)]:
            for lbl in label.split("|"):
                for inp in self._find(q, f'input[aria-label*="{lbl}"], input[placeholder*="{lbl}"]'):
                    try:
                        if inp.is_displayed():
                            inp.clear(); inp.send_keys(value); break
                    except Exception: pass

    def _build_handlers(self) -> dict:
        """Dict de handlers: construido una sola vez en __init__, sin getattr en runtime."""
        return {
            "radio":         self._radio,
            "radio_other":   self._radio_other,
            "checkbox":      self._checkbox,
            "scale":         self._scale,
            "grid":          self._grid,
            "checkbox_grid": self._checkbox_grid,
            "dropdown":      self._dropdown,
            "date":          self._date,
            "time":          self._time,
            "short_text":    self._short_text,
            "paragraph":     self._paragraph,
        }

    def _fill_question(self, q, idx: int):
        try:
            hint = ""
            try:
                hint = q.find_element(By.CSS_SELECTOR, self._HINT_SELECTOR).text
            except Exception:
                pass

            q_type = self._question_type(q)
            log.info(f"  Q{idx} [{q_type}]: {hint[:60]}")

            if q_type == "file":
                log.warning("  ⚠ Pregunta de archivo — omitida")
            elif q_type == "unknown":
                # Fallback genérico
                opts = self._find(q, '[role="radio"]')
                if opts:
                    self._scroll_click(random.choice(opts))
                else:
                    inps = self._find(q, 'input[type="text"], textarea')
                    if inps:
                        self._type(inps[0], gen.sanitize(gen.texto()))
            else:
                handler = self._handlers.get(q_type)
                if handler:
                    if q_type in ("short_text", "paragraph"):
                        handler(q, hint)
                    else:
                        handler(q)

            self._sleep(random.uniform(0.5, 1.2))

        except StaleElementReferenceException:
            log.warning(f"  Q{idx}: elemento stale, se omite")
        except Exception as e:
            log.warning(f"  Q{idx}: error inesperado — {e}")

    def _fill_page(self):
        questions = []
        for sel in self._Q_SELECTORS:
            questions = self._driver.find_elements(By.CSS_SELECTOR, sel)
            if questions:
                break
        log.info(f"  {len(questions)} pregunta(s) detectadas")
        for i, q in enumerate(questions, 1):
            if self._shutdown:
                break
            self._fill_question(q, i)

    # ── Navegación y envío ───────────────────────────────────────
    def _next_page(self) -> bool:
        for sel in self._NEXT_SELECTORS:
            try:
                btn = self._driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_displayed():
                    btn.click()
                    self._sleep(2)
                    return True
            except NoSuchElementException:
                continue
        return False

    def _submit(self) -> bool:
        for sel in self._SUBMIT_SELECTORS:
            try:
                btn = self._driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_displayed() and btn.is_enabled():
                    self._scroll_click(btn)
                    log.info("  ✓ Formulario enviado")
                    return True
            except NoSuchElementException:
                continue
        # Fallback por texto
        for btn in self._driver.find_elements(By.CSS_SELECTOR, '[role="button"]'):
            if any(w in btn.text.lower() for w in ("enviar", "submit")):
                btn.click()
                log.info("  ✓ Enviado (fallback texto)")
                return True
        log.error("  ✗ Botón de enviar no encontrado")
        return False

    # ── Ciclo de un envío ────────────────────────────────────────
    def _reserve_slot(self) -> bool:
        """Reserva atómicamente un slot de envío. Retorna False si se alcanzó el límite."""
        with self._sub_lock:
            if self._submissions >= self.config.max_responses:
                log.error("Límite de respuestas alcanzado")
                return False
            self._submissions += 1
            return True

    def _release_slot(self):
        """Libera un slot si el envío falló (descuenta del contador)."""
        with self._sub_lock:
            self._submissions = max(0, self._submissions - 1)

    def _submit_once(self, index: int) -> bool:
        if not self._reserve_slot():
            return False

        log.info(f"\n{'─'*50}")
        log.info(f"Respuesta #{index+1} | {gen.nombre()}")
        log.info(f"{'─'*50}")

        try:
            self._driver.get(self.config.url)
            self._sleep(2)
            self._wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, self._LOAD_SELECTOR)
            ))
        except TimeoutException:
            log.error("  ✗ Timeout cargando el formulario")
            self._release_slot()
            return False

        page = 1
        while not self._shutdown:
            log.info(f"  — Página {page} —")
            self._fill_page()
            self._sleep(1)
            if self._next_page():
                page += 1
                try:
                    self._wait.until(EC.presence_of_element_located(
                        (By.CSS_SELECTOR, '.Qr7Oae, [data-params]')
                    ))
                except TimeoutException:
                    break
            else:
                break

        ok = self._submit()
        if not ok:
            self._release_slot()
        else:
            try:
                self._wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, self._CONFIRM_SELECTOR)
                ))
                log.info("  ✓ Confirmación recibida")
            except TimeoutException:
                log.warning("  ⚠ Sin confirmación visual, pero el envío fue iniciado")
        return ok

    # ── Worker por hilo ──────────────────────────────────────────
    def _worker(self, index: int) -> bool:
        if self._shutdown:
            return False
        proxy = self.config.proxy
        if self.proxy_rotator:
            proxy = self.proxy_rotator.next() or proxy
        try:
            self._init_driver(proxy=proxy)
            return self._submit_once(index)
        except Exception as e:
            log.error(f"Worker #{index+1} error: {e}")
            return False
        finally:
            self._close_driver()

    # ── run() ────────────────────────────────────────────────────
    def run(self) -> tuple[int, int]:
        log.info(f"URL:       {self.config.url}")
        log.info(f"Respuestas:{self.config.count} | Hilos:{self.config.threads} | Headless:{self.config.headless}")

        success = failed = 0
        lock = threading.Lock()

        def record(ok: bool):
            nonlocal success, failed
            with lock:
                if ok: success += 1
                else:  failed  += 1

        try:
            if self.config.threads > 1:
                with ThreadPoolExecutor(max_workers=self.config.threads) as ex:
                    futures = {ex.submit(self._worker, i): i for i in range(self.config.count)}
                    for fut in as_completed(futures):
                        if self._shutdown:
                            break
                        try:
                            record(fut.result())
                        except Exception as e:
                            log.error(f"Worker error: {e}")
                            record(False)
                        time.sleep(random.uniform(self.config.delay_min, self.config.delay_max))
            else:
                for i in range(self.config.count):
                    if self._shutdown:
                        break
                    record(self._worker(i))
                    if i < self.config.count - 1:
                        delay = random.uniform(self.config.delay_min, self.config.delay_max)
                        log.info(f"  Esperando {delay:.1f}s...")
                        time.sleep(delay)

        except KeyboardInterrupt:
            log.warning("Interrupción manual")
        finally:
            self._quit_all_drivers()

        log.info(f"\n{'='*50}")
        log.info(f"✓ {success} exitosas  ✗ {failed} fallidas  (total: {self.config.count})")
        log.info(f"{'='*50}")
        return success, failed


# ── CLI ──────────────────────────────────────────────────────────
def _parse_args():
    p = argparse.ArgumentParser(description="Google Forms Bot — respuestas aleatorias mexicanas")
    p.add_argument("--url",          help="URL del formulario")
    p.add_argument("--count",        type=int,   default=1,           help="Número de respuestas (default: 1)")
    p.add_argument("--delay",        type=float, default=3.0,         help="Delay entre respuestas en segundos (default: 3)")
    p.add_argument("--threads",      type=int,   default=1,           help="Hilos concurrentes (default: 1)")
    p.add_argument("--proxy",        help="Proxy único (http:// o socks5://)")
    p.add_argument("--proxy-file",   dest="proxy_file", help="Archivo con proxies (uno por línea)")
    p.add_argument("--max-responses",dest="max_responses", type=int, default=MAX_RESPONSES)
    p.add_argument("--no-headless",  action="store_true", help="Muestra el navegador")
    p.add_argument("--config",       help="Archivo JSON de configuración")
    return p.parse_args()


def _banner():
    print("\033[2J\033[H", end="", flush=True)
    print("\033[91m" + r"""
    ██╗   ██╗ ██████╗ ██████╗ ████████╗███████╗██╗  ██╗
    ██║   ██║██╔═══██╗██╔══██╗╚══██╔══╝██╔════╝██║ ██╔╝
    ██║   ██║██║██╗██║██████╔╝   ██║   █████╗  █████╔╝ 
    ╚██╗ ██╔╝██║██║██║██╔══██╗   ██║   ██╔══╝  ██╔═██╗ 
     ╚████╔╝ ╚██████╔╝██║  ██║   ██║   ███████╗██║  ██╗
      ╚═══╝   ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝
                   [ O F F E N S I V E ]
                [ T E C H N O H A C K S ]
    """ + "\033[0m")
    for msg in ("[+] Inicializando arquitectura VØRTEK...", "[+] Cargando módulos de red..."):
        print(f"\033[90m{msg}\033[0m")
        time.sleep(0.5)
    print("\033[92m[✓] LOADING...\033[0m\n")


def main():
    _banner()
    args = _parse_args()
    try:
        if args.config:
            config = BotConfig.from_file(args.config)
        elif args.url:
            config = BotConfig.from_args(args)
        else:
            print("ERROR: usa --url URL o --config config.json")
            sys.exit(1)
    except (ValueError, FileNotFoundError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    GoogleFormsBot(config).run()


if __name__ == "__main__":
    main()
