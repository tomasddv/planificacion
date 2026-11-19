import re
import unicodedata


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", normalized).strip()


def classify_question(question: str) -> str | None:
    normalized = normalize_text(question)
    if not normalized:
        return None
    if re.search(r"\b(no compr|sin compr|faltan|restan|pendientes)\w*", normalized):
        return "non_buyers"
    if re.search(r"\b(activ|nuevos)\w*", normalized) and re.search(r"\b(hoy|ultimo dia|ayer)\b", normalized):
        return "last_activations"
    if re.search(r"\b(compr|venta|vend|activ)\w*", normalized):
        return "buyers"
    if re.search(r"\b(cuantos|cuantas|clientes|quienes|lista|tiene|tienen)\b", normalized):
        return "buyers"
    return None


def find_named_entity(question: str, names) -> str | None:
    normalized = normalize_text(question)
    matches = [name for name in names if normalize_text(name) and re.search(r"(?<!\w)" + re.escape(normalize_text(name)) + r"(?!\w)", normalized)]
    return max(matches, key=lambda name: len(normalize_text(name)), default=None)


def find_person(question: str, names) -> str | None:
    exact = find_named_entity(question, names)
    if exact:
        return exact
    normalized = normalize_text(question)
    token_to_names = {}
    for name in names:
        for token in set(normalize_text(name).split()):
            if len(token) >= 4:
                token_to_names.setdefault(token, set()).add(name)
    candidates = [next(iter(owners)) for token, owners in token_to_names.items()
                  if len(owners) == 1 and re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", normalized)]
    return candidates[0] if len(set(candidates)) == 1 else None


def find_focus(question: str) -> str | None:
    normalized = normalize_text(question)
    aliases = [
        (r"\b(value|1890)\b", "Value"),
        (r"\b(above core)\b", "Above Core"),
        (r"\b(core)\b", "Core"),
        (r"\b(premium)\b", "Premium"),
        (r"\b(latones? 710)\b", "Latones 710"),
        (r"\b(balanced choices?)\b", "Balanced Choices"),
        (r"\b(nabs)\b", "Nabs"),
        (r"\b(total cza|cervezas?)\b", "Total CZA"),
    ]
    return next((focus for pattern, focus in aliases if re.search(pattern, normalized)), None)


def is_route_question(question: str) -> bool:
    return bool(re.search(r"\b(que|cual|cuales)\s+rutas?\b", normalize_text(question)))


def find_sku(question: str, options) -> str | None:
    normalized = normalize_text(question)
    aliases = {
        "pure gold": "PURE GOLD TODOS",
        "pepsi black": "PEPSI BLACK TODOS",
        "black": "PEPSI BLACK TODOS",
        "gatorade": "GATORADE TODOS",
        "sin alcohol": "SIN ALCOHOL TODOS",
        "sin alchol": "SIN ALCOHOL TODOS",
        "latones 710": "LATONES 710",
    }
    for phrase, option in aliases.items():
        if re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", normalized) and option in options:
            return option
    candidates = [option for option in options if option != "Todos" and normalize_text(option)]
    direct = find_named_entity(question, candidates)
    if direct:
        return direct
    brands = [option for option in candidates if option.endswith(" TODOS")]
    for option in sorted(brands, key=len, reverse=True):
        brand = normalize_text(option[:-6])
        if re.search(r"(?<!\w)" + re.escape(brand) + r"(?!\w)", normalized):
            return option
    return None


def asks_for_unsupported_period(question: str, current_month: int) -> bool:
    months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    normalized = normalize_text(question)
    return any(re.search(r"(?<!\w)" + month + r"(?!\w)", normalized) for index, month in enumerate(months, 1) if index != current_month)
