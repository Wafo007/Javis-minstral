"""Normalisation du texte destine a la VOIX (le texte affiche reste intact).

pour_la_voix(texte) -> texte lisible a haute voix : Markdown, emojis, URLs, tableaux,
balises, symboles retires ; unites, pourcentages, heures, dates, decimaux dits en toutes
lettres. Fonction pure, sans dependance, sans materiel.
"""
from __future__ import annotations

import re
import unicodedata

_MOIS = ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
         "aout", "septembre", "octobre", "novembre", "decembre"]
_MOIS_ACC = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
             "août", "septembre", "octobre", "novembre", "décembre"]

# (motif apres un nombre, texte dit). Ordre : le plus long d'abord.
_UNITES = [
    (r"km/h", "kilomètres par heure"), (r"m/s", "mètres par seconde"),
    (r"°\s?C", "degrés"), (r"°\s?F", "degrés Fahrenheit"), (r"°", "degrés"),
    (r"km", "kilomètres"), (r"kg", "kilogrammes"), (r"cm", "centimètres"),
    (r"mm", "millimètres"), (r"Mo|MB", "mégaoctets"), (r"Go|GB", "gigaoctets"),
    (r"Ko|KB", "kilooctets"), (r"To|TB", "téraoctets"), (r"Mbps|Mb/s", "mégabits par seconde"),
    (r"GHz", "gigahertz"), (r"MHz", "mégahertz"), (r"min", "minutes"),
    (r"€", "euros"), (r"\$", "dollars"), (r"%", "pour cent"),
]

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF"
    "\U0000FE00-\U0000FE0F\U0000200D\U000020E3\U0000E000-\U0000F8FF]+")


def _sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _email(m: re.Match) -> str:
    return f"{m.group(1)} arobase {m.group(2).replace('.', ' point ')}"


def _heure(m: re.Match) -> str:
    h, mn = int(m.group(1)), m.group(2)
    mots = f"{h} heure{'s' if h > 1 else ''}"
    return mots + (f" {int(mn)}" if mn and int(mn) else "")


def _date_fr(m: re.Match) -> str:
    j, mo, a = int(m.group(1)), int(m.group(2)), m.group(3)
    if not (1 <= j <= 31 and 1 <= mo <= 12):
        return m.group(0)
    return f"{'1er' if j == 1 else j} {_MOIS_ACC[mo - 1]} {a}"


def _date_iso(m: re.Match) -> str:
    a, mo, j = m.group(1), int(m.group(2)), int(m.group(3))
    if not (1 <= j <= 31 and 1 <= mo <= 12):
        return m.group(0)
    return f"{'1er' if j == 1 else j} {_MOIS_ACC[mo - 1]} {a}"


def pour_la_voix(texte: str, *, texte_code: str = "Le code est affiché à l'écran.",
                 texte_lien: str = "un lien") -> str:
    if not texte:
        return ""
    t = unicodedata.normalize("NFKC", str(texte)).replace("\r\n", "\n").replace("\r", "\n")

    t = _EMOJI.sub(" ", t)                                        # emojis d'abord (fins de ligne propres)

    # --- code, HTML, images, liens, e-mails, URLs ------------------------------
    avait_code = "```" in t
    t = re.sub(r"```.*?(```|\Z)", "\n@@CODE@@\n", t, flags=re.S)
    t = t.replace("@@CODE@@", texte_code if avait_code else "")
    t = re.sub(r"`([^`\n]*)`", r"\1", t)
    t = re.sub(r"<[^>\n]{1,200}>", " ", t)                       # balises HTML
    t = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", t)              # images
    t = re.sub(r"\[([^\]]+)\]\((?:mailto:)?([^)]*)\)", lambda m: m.group(1), t)
    t = re.sub(r"\[\d{1,3}\]", "", t)                             # references [1]
    t = re.sub(r"([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)", _email, t)
    t = re.sub(r"(?:https?://|www\.)\S+", texte_lien, t)

    # --- structure Markdown ----------------------------------------------------
    lignes_sortie = []
    for ligne in t.split("\n"):
        l = ligne.strip()
        if not l:
            lignes_sortie.append("")
            continue
        if re.fullmatch(r"[-=_*~#\s]{3,}", l) or re.fullmatch(r"\|?[\s:|-]{3,}\|?", l):
            continue                                               # separateurs, ligne --- de tableau
        l = re.sub(r"^>+\s*", "", l)                                # citations
        titre = re.match(r"^#{1,6}\s*(.+?)\s*#*$", l) or re.fullmatch(r"(?:\*\*|__)(.+?)(?:\*\*|__)", l)
        puce = re.match(r"^(?:[-*+•▪●◦‣]|\d{1,3}[.)])\s+(.*)$", l)
        if titre:
            l = titre.group(1)
            fin = True
        elif puce:
            l = puce.group(1)
            fin = True
        elif "|" in l and l.count("|") >= 2:                        # ligne de tableau
            cellules = [c.strip() for c in l.strip("|").split("|") if c.strip()]
            l = ", ".join(cellules)
            fin = True
        else:
            fin = False
        l = re.sub(r"(\*\*|__|~~)(.+?)\1", r"\2", l)
        l = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", l)
        l = re.sub(r"(?<![\w])_(?!\s)(.+?)(?<!\s)_(?![\w])", r"\1", l)
        l = l.replace("**", "").replace("__", "").replace("*", " ")
        l = l.strip()
        if l.endswith(":") and not fin:
            l = l[:-1] + "."
        elif fin and l and l[-1] not in ".!?…:;":
            l += "."
        elif fin and l.endswith(":"):
            l = l[:-1] + "."
        lignes_sortie.append(l)
    t = " ".join(x for x in lignes_sortie if x)

    # --- emojis et symboles ----------------------------------------------------
    t = _EMOJI.sub(" ", t)
    t = "".join(c for c in t if unicodedata.category(c) not in ("So", "Sk", "Cs", "Co", "Cf")
                or c in "°€")

    # --- dates, heures, nombres, unites -----------------------------------------
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", _date_fr, t)
    t = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", _date_iso, t)
    t = re.sub(r"\b([01]?\d|2[0-3])\s?[h:]\s?([0-5]\d)?\b(?!\d)", _heure, t)
    t = re.sub(r"(?<![\d.])(\d+)\.(\d+)(?![\d.])", r"\1 virgule \2", t)
    for motif, dit in _UNITES:
        t = re.sub(rf"(?<=\d)\s?(?:{motif})(?![\w/])", f" {dit}", t)
    t = re.sub(r"(?<=\w)\s?&\s?(?=\w)", " et ", t)
    t = re.sub(r"\s\+\s", " plus ", t)

    # --- ponctuation propre ----------------------------------------------------
    t = re.sub(r"[~^\\{}<>|#]+", " ", t)
    t = re.sub(r"([!?.,;:…])\1{1,}", r"\1", t)
    t = re.sub(r"\.{2,}", "…", t)
    t = re.sub(r"(?<!\w)[-–—_=]{2,}(?!\w)", " ", t)
    t = re.sub(r"\s+([,.;:!?…])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" \t-–—_")

    # --- phrases consecutives identiques --------------------------------------
    phrases = re.split(r"(?<=[.!?…])\s+", t)
    sans_doublon = []
    for p in phrases:
        if not sans_doublon or _sans_accents(p).lower() != _sans_accents(sans_doublon[-1]).lower():
            sans_doublon.append(p)
    return " ".join(sans_doublon).strip()
