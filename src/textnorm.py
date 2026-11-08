"""Canonical text normalization shared by indexing and query parsing."""

import re
import unicodedata

_SUPERSCRIPT_DIGITS = str.maketrans(
    {
        "\u2070": "0",
        "\u00b9": "1",
        "\u00b2": "2",
        "\u00b3": "3",
        "\u2074": "4",
        "\u2075": "5",
        "\u2076": "6",
        "\u2077": "7",
        "\u2078": "8",
        "\u2079": "9",
    }
)

_ORDINAL_WORDS = {
    "primeiro": 1,
    "segundo": 2,
    "terceiro": 3,
    "quarto": 4,
    "quinto": 5,
    "sexto": 6,
    "setimo": 7,
    "oitavo": 8,
    "nono": 9,
    "decimo": 10,
}

_ROMAN_RE = re.compile(r"^[ivxlcdm]+$")
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}

_NUMERIC_RANGE_RE = re.compile(r"\b(artigo|paragrafo|inciso|item)\s+(\d+)\s*(e|ate|a|-)\s*(\d+)\b")
_LETTER_RANGE_RE = re.compile(r"\balinea\s+([a-z])\s*(e|ate|a|-)\s*([a-z])\b")

_MAX_RANGE_SPAN = 50


def strip_accents(text: str) -> str:
    """Remove diacritics using canonical decomposition."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _roman_to_int(token: str) -> int | None:
    if not _ROMAN_RE.fullmatch(token):
        return None
    total = 0
    previous = 0
    for char in reversed(token):
        value = _ROMAN_VALUES[char]
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    return total if total > 0 else None


def roman_to_int(token: str) -> int | None:
    """Convert a lowercase Roman numeral token to an integer, if valid."""
    return _roman_to_int(token)


def _base_normalize(text: str) -> str:
    text = text.lower()
    text = text.replace("\u00ba", "").replace("\u00b0", "").replace("\u00aa", "a")
    text = text.translate(_SUPERSCRIPT_DIGITS)
    text = strip_accents(text)
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"[,;:]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _canonicalize_keywords(text: str) -> str:
    text = text.replace("\u00a7\u00a7", " paragrafo ").replace("\u00a7", " paragrafo ")
    text = re.sub(r"\b(?:paragrafos|paragrafo|pars?)\b\.?", "paragrafo", text)
    text = re.sub(r"\b(?:artigos|artigo|arts?)\b\.?", "artigo", text)
    text = re.sub(r"\b(?:incisos|inciso|incs?)\b\.?", "inciso", text)
    text = re.sub(r"\b(?:alineas|alinea|als?)\b\.?", "alinea", text)
    text = re.sub(r"\bitens\b", "item", text)
    return re.sub(r"\s+", " ", text).strip()


def _convert_ordinal_words(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        word = match.group(1)
        value = _ORDINAL_WORDS.get(word)
        return f"paragrafo {value}" if value is not None else match.group(0)

    return re.sub(
        r"\bparagrafo\s+(" + "|".join(_ORDINAL_WORDS) + r")\b",
        replace,
        text,
    )


def _convert_inciso_romans(text: str) -> str:
    tokens = text.split()
    output: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        output.append(token)
        index += 1
        if token != "inciso":
            continue
        expecting_value = True
        while index < len(tokens):
            current = tokens[index]
            if expecting_value:
                number = _roman_to_int(current)
                if number is not None:
                    output.append(str(number))
                    expecting_value = False
                    index += 1
                    continue
                if current.isdigit():
                    output.append(current)
                    expecting_value = False
                    index += 1
                    continue
                break
            if current in {"e", "a", "ate", "-"}:
                output.append(current)
                expecting_value = True
                index += 1
                continue
            break
    return " ".join(output)


def _expand_numeric_ranges(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        keyword, start_raw, connector, end_raw = match.groups()
        start, end = int(start_raw), int(end_raw)
        if connector == "e":
            return f"{keyword} {start} {keyword} {end}"
        if end < start or end - start > _MAX_RANGE_SPAN:
            return match.group(0)
        return " ".join(f"{keyword} {value}" for value in range(start, end + 1))

    return _NUMERIC_RANGE_RE.sub(replace, text)


def _expand_letter_ranges(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        start_raw, connector, end_raw = match.groups()
        start, end = ord(start_raw), ord(end_raw)
        if connector == "e":
            return f"alinea {start_raw} alinea {end_raw}"
        if end < start or end - start > _MAX_RANGE_SPAN:
            return match.group(0)
        return " ".join(f"alinea {chr(value)}" for value in range(start, end + 1))

    return _LETTER_RANGE_RE.sub(replace, text)


def _apply_synonyms(text: str) -> str:
    text = re.sub(r"\bmedida de protecao\b", "medida protetiva", text)
    text = re.sub(r"\bbo\b", "boletim de ocorrencia", text)
    return text


def _normalize(text: str) -> str:
    text = _base_normalize(text)
    text = _canonicalize_keywords(text)
    text = _convert_ordinal_words(text)
    text = _convert_inciso_romans(text)
    text = _expand_numeric_ranges(text)
    text = _expand_letter_ranges(text)
    text = _apply_synonyms(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_citation_forms(text: str) -> str:
    """Normalize citation spellings (``art. 7º`` -> ``artigo 7``)."""
    return _normalize(text)


def normalize_search_text(text: str) -> str:
    """Normalize text for BM25/FTS indexing and querying."""
    return _normalize(text)


#: Function words plus structural citation markers.
#:
#: Structural markers (artigo, paragrafo, ...) appear in every chunk's
#: context, so keeping them in a disjunctive lexical query would add a term
#: that matches nearly the whole corpus and dilutes ts_rank_cd cover density.
_FTS_STOPWORDS = frozenset(
    """
    a ao aos aquela aquelas aquele aqueles aquilo as ate com como da das de dela
    delas dele deles depois do dos e ela elas ele eles em entre era eram essa
    essas esse esses esta estas este estes eu foi foram ha isso isto ja lhe
    lhes mais mas me mesmo meu meus minha minhas muito na nao nas nem no nos
    nossa nossas nosso nossos num numa o os ou para pela pelas pelo pelos por
    qual quando que quem se sem seu seus so sou sua suas tambem tem tenho ter
    teu tua tuas um uma umas uns voce voces
    """.split()
)

_FTS_STRUCTURAL = frozenset(
    {"artigo", "artigos", "paragrafo", "inciso", "alinea", "item", "itens", "caput"}
)

#: Upper bound on disjunctive terms; keeps the tsquery small and predictable.
MAX_FTS_TERMS = 32


def build_fts_query(text: str) -> str:
    """Build a disjunctive websearch_to_tsquery input from natural language.

    websearch_to_tsquery joins bare terms with AND, so a full question becomes
    a conjunction that matches nothing. The lexical leg needs recall, not
    conjunctive precision: this keeps the content words, de-duplicates them and
    joins them with 'or'.

    Text is normalized with normalize_search_text, the same function used to
    build the indexed search_text. The index strips accents, so the query must
    be unaccented too or every accented term silently misses.

    Returns an empty string when the text has no usable term.
    """

    return " or ".join(build_fts_terms(text))


def build_fts_terms(text: str) -> list[str]:
    """Return the content terms used by the lexical search, in order.

    The lexical scorer weighs each term by how rare it is, so it needs the
    terms themselves; this function is the single place that tokenizes.
    """

    if not text or not text.strip():
        return []

    # websearch_to_tsquery treats double quotes as a phrase and a leading hyphen
    # as negation.  Both would survive into the disjunctive query and change its
    # meaning (a quoted question becomes a phrase that matches nothing), so the
    # query is flattened to bare terms first.
    flattened = text.replace('"', " ")

    tokens: list[str] = []
    for token in normalize_search_text(flattened).split():
        if token.startswith("-"):
            token = token.lstrip("-")
        if not token or not any(char.isalnum() for char in token):
            continue
        if token in _FTS_STOPWORDS or token in _FTS_STRUCTURAL:
            continue
        if not token.isdigit() and len(token) < 2:
            continue
        if token in tokens:
            continue
        tokens.append(token)
        if len(tokens) >= MAX_FTS_TERMS:
            break
    return tokens
