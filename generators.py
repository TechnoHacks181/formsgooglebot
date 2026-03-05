"""
generators.py — Genera datos aleatorios con perfil mexicano.
"""

import random
import re
from datetime import datetime, timedelta

from data import (
    NOMBRES, APELLIDOS, DOMINIOS, ESTADOS_MX,
    EMPRESAS, OCUPACIONES,
    TEXTOS_POSITIVOS, TEXTOS_NEUTROS, TEXTOS_OTROS,
)

# Mapeo: palabras clave en la pregunta → función generadora
# Las lambdas capturan funciones del módulo, no closures sobre variables externas
_HINT_MAP: list[tuple[tuple[str, ...], callable]] = [
    (("nombre", "name"),                     lambda: nombre()),
    (("correo", "email", "mail"),            lambda: email(nombre())),
    (("teléfono", "telefono", "celular"),    lambda: telefono()),
    (("edad", "age", "años"),                lambda: str(random.randint(18, 65))),
    (("estado", "ciudad", "city"),           lambda: random.choice(ESTADOS_MX)),
    (("fecha", "date", "nacimiento"),        lambda: fecha()),
    (("hora", "time", "horario"),            lambda: hora()),
    (("código postal", "zip", "cp"),         lambda: str(random.randint(10000, 99999))),
    (("empresa", "company", "organización"), lambda: random.choice(EMPRESAS)),
    (("ocupación", "profesión", "trabajo"),  lambda: random.choice(OCUPACIONES)),
]


def nombre() -> str:
    return f"{random.choice(NOMBRES)} {random.choice(APELLIDOS)} {random.choice(APELLIDOS)}"


def email(full_name: str) -> str:
    _ACCENT = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")
    base = full_name.lower().translate(_ACCENT).replace(" ", ".")
    return f"{base}{random.randint(10, 999)}@{random.choice(DOMINIOS)}"


def telefono() -> str:
    lada = random.choice(["55", "33", "81", "222", "477", "667", "999"])
    return f"{lada}{random.randint(1_000_000, 9_999_999)}"


def fecha() -> str:
    """Fecha aleatoria en los últimos 5 años (YYYY-MM-DD)."""
    delta = random.randint(0, 5 * 365)
    return (datetime.now() - timedelta(days=delta)).strftime("%Y-%m-%d")


def hora() -> str:
    """Hora aleatoria con preferencia a horario laboral (HH:MM)."""
    h = random.randint(8, 20) if random.random() < 0.7 else random.randint(0, 23)
    m = random.choice([0, 15, 30, 45]) if random.random() < 0.6 else random.randint(0, 59)
    return f"{h:02d}:{m:02d}"


def texto(positivo: bool = True) -> str:
    pool = TEXTOS_POSITIVOS if positivo else (TEXTOS_POSITIVOS + TEXTOS_NEUTROS)
    return random.choice(pool)


def texto_otro() -> str:
    return random.choice(TEXTOS_OTROS)


def texto_por_hint(hint: str) -> str:
    """Devuelve un valor apropiado según el texto de la pregunta."""
    hint_lower = hint.lower()
    for keywords, generator in _HINT_MAP:
        if any(k in hint_lower for k in keywords):
            return generator()
    return texto()


def sanitize(text: str, max_len: int = 500) -> str:
    """Elimina caracteres de control y trunca."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)[:max_len]
