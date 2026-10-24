"""Pilotage de Chrome par le protocole CDP, SANS Playwright (donc sans greenlet ni Visual C++).

Pourquoi : sur certains PC Windows, `greenlet` (dependance obligatoire de Playwright) ne se charge pas
faute des bibliotheques Visual C++ et ne peut pas etre installe. Chrome expose pourtant le meme
protocole (le port de debug que Jarvis ouvre deja) : ce module en parle directement, en bibliotheque
standard uniquement (sockets + un client WebSocket minimal).

Il n'imite que la partie de l'API Playwright utilisee par tools/navigateur.py : browser.contexts,
context.pages / new_page, page.url / title / evaluate / inner_text / goto / click / fill /
query_selector / bring_to_front / close / screenshot, page.mouse.wheel, page.keyboard.press.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import threading
import time
import urllib.parse
import urllib.request

_TEMPS_MAX = 15.0


class ErreurCDP(RuntimeError):
    pass


# ---------------------------------------------------------------- client WebSocket minimal
class _WebSocket:
    def __init__(self, url: str, delai: float = _TEMPS_MAX):
        p = urllib.parse.urlparse(url)
        self._sock = socket.create_connection((p.hostname, p.port or 80), timeout=delai)
        cle = base64.b64encode(os.urandom(16)).decode()
        chemin = (p.path or "/") + (("?" + p.query) if p.query else "")
        requete = (f"GET {chemin} HTTP/1.1\r\nHost: {p.hostname}:{p.port}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {cle}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self._sock.sendall(requete.encode())
        reponse = b""
        while b"\r\n\r\n" not in reponse:
            morceau = self._sock.recv(4096)
            if not morceau:
                raise ErreurCDP("Chrome a ferme la connexion pendant l'echange initial.")
            reponse += morceau
        entete, _, self._reste = reponse.partition(b"\r\n\r\n")
        if b" 101 " not in entete.split(b"\r\n")[0]:
            raise ErreurCDP("Chrome a refuse la connexion WebSocket : " + entete.split(b"\r\n")[0].decode(errors="replace"))

    def _lire(self, n: int) -> bytes:
        while len(self._reste) < n:
            morceau = self._sock.recv(65536)
            if not morceau:
                raise ErreurCDP("connexion Chrome fermee")
            self._reste += morceau
        donnees, self._reste = self._reste[:n], self._reste[n:]
        return donnees

    def envoyer(self, texte: str):
        charge = texte.encode("utf-8")
        entete = bytearray([0x81])
        n = len(charge)
        if n < 126:
            entete.append(0x80 | n)
        elif n < 65536:
            entete.append(0x80 | 126)
            entete += struct.pack(">H", n)
        else:
            entete.append(0x80 | 127)
            entete += struct.pack(">Q", n)
        masque = os.urandom(4)
        entete += masque
        corps = bytes(b ^ masque[i % 4] for i, b in enumerate(charge))
        self._sock.sendall(bytes(entete) + corps)

    def recevoir(self) -> str:
        """Un message texte complet (fragments recomposes ; ping repondus ; binaire ignore)."""
        morceaux, texte = [], True
        while True:
            b1, b2 = self._lire(2)
            fin, opcode = bool(b1 & 0x80), b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._lire(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._lire(8))[0]
            if b2 & 0x80:                                     # un serveur n'est pas cense masquer
                masque = self._lire(4)
                charge = bytes(b ^ masque[i % 4] for i, b in enumerate(self._lire(n)))
            else:
                charge = self._lire(n)
            if opcode == 0x8:
                raise ErreurCDP("connexion Chrome fermee")
            if opcode == 0x9:                                 # ping -> pong
                self._sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x2):
                texte = opcode == 0x1
                morceaux = [charge]
            else:
                morceaux.append(charge)
            if fin:
                return b"".join(morceaux).decode("utf-8", "replace") if texte else ""

    def delai(self, secondes: float):
        self._sock.settimeout(secondes)

    def fermer(self):
        try:
            self._sock.close()
        except OSError:
            pass


class _Session:
    """Une session CDP (un onglet ou le navigateur) : requete/reponse synchrone."""

    def __init__(self, url_ws: str):
        self._ws = _WebSocket(url_ws)
        self._id = 0
        self._verrou = threading.Lock()

    def appeler(self, methode: str, params: dict | None = None, delai: float = _TEMPS_MAX):
        with self._verrou:
            self._id += 1
            mon_id = self._id
            self._ws.envoyer(json.dumps({"id": mon_id, "method": methode, "params": params or {}}))
            fin = time.monotonic() + delai
            while True:
                restant = fin - time.monotonic()
                if restant <= 0:
                    raise ErreurCDP(f"delai depasse pour {methode}")
                self._ws.delai(restant)
                try:
                    msg = json.loads(self._ws.recevoir())
                except socket.timeout:
                    raise ErreurCDP(f"delai depasse pour {methode}") from None
                if msg.get("id") == mon_id:
                    if "error" in msg:
                        raise ErreurCDP(f"{methode} : {msg['error'].get('message', msg['error'])}")
                    return msg.get("result", {})

    def fermer(self):
        self._ws.fermer()


def _http(port: int, chemin: str, methode: str = "GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{chemin}", method=methode)
    with urllib.request.urlopen(req, timeout=5) as r:
        brut = r.read().decode("utf-8", "replace")
    try:
        return json.loads(brut)
    except ValueError:
        return brut


# ---------------------------------------------------------------- API facon Playwright
def _est_fonction(expression: str) -> bool:
    """Vrai pour « () => ... », « (a) => ... » ou « function (...) {...} » (a appeler), faux pour une
    expression ou une fonction deja invoquee « (() => ...)() »."""
    import re
    return bool(re.match(r"\s*(?:async\s+)?(?:\([^()]*\)|\w+)\s*=>", expression)
                or re.match(r"\s*(?:async\s+)?function\b", expression))


class _Souris:
    def __init__(self, page):
        self._p = page

    def wheel(self, dx: float, dy: float):
        self._p._cmd("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 400, "y": 300,
                                                  "deltaX": dx, "deltaY": dy})


class _Clavier:
    _TOUCHES = {"Space": (" ", "Space", 32), "Enter": ("Enter", "Enter", 13), "Escape": ("Escape", "Escape", 27),
                "Tab": ("Tab", "Tab", 9), "ArrowDown": ("ArrowDown", "ArrowDown", 40),
                "ArrowUp": ("ArrowUp", "ArrowUp", 38), "Backspace": ("Backspace", "Backspace", 8)}

    def __init__(self, page):
        self._p = page

    def press(self, touche: str):
        cle, code, vk = self._TOUCHES.get(touche, (touche, "Key" + touche.upper(), ord(touche[0].upper()) if touche else 0))
        texte = cle if len(cle) == 1 else ("\r" if cle == "Enter" else "")
        base = {"key": cle, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
        self._p._cmd("Input.dispatchKeyEvent", {**base, "type": "keyDown", **({"text": texte} if texte else {})})
        self._p._cmd("Input.dispatchKeyEvent", {**base, "type": "keyUp"})


class _Element:
    def __init__(self, page, selecteur):
        self._p, self._s = page, selecteur

    def get_attribute(self, nom: str):
        return self._p.evaluate(f"document.querySelector({json.dumps(self._s)})?.getAttribute({json.dumps(nom)})")


class Page:
    def __init__(self, port: int, cible: dict):
        self._port, self._cible = port, cible
        self._session: _Session | None = None
        self.mouse, self.keyboard = _Souris(self), _Clavier(self)

    # -- bas niveau
    def _cmd(self, methode, params=None, delai=_TEMPS_MAX):
        if self._session is None:
            self._session = _Session(self._cible["webSocketDebuggerUrl"])
        return self._session.appeler(methode, params, delai)

    @property
    def id(self):
        return self._cible["id"]

    # -- lecture
    @property
    def url(self) -> str:
        try:
            return str(self.evaluate("location.href"))
        except ErreurCDP:
            return str(self._cible.get("url", ""))

    def title(self) -> str:
        return str(self.evaluate("document.title") or "")

    def evaluate(self, expression: str, arg=None):
        expr = f"({expression})()" if _est_fonction(expression) else expression
        res = self._cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in res:
            detail = res["exceptionDetails"]
            raise ErreurCDP("erreur JavaScript : " + str((detail.get("exception") or {}).get("description")
                                                          or detail.get("text")))
        return (res.get("result") or {}).get("value")

    def inner_text(self, selecteur: str) -> str:
        return str(self.evaluate(f"document.querySelector({json.dumps(selecteur)})?.innerText || ''") or "")

    def screenshot(self, type: str = "jpeg", quality: int = 70, **_):
        params = {"format": "jpeg" if type == "jpeg" else "png"}
        if type == "jpeg":
            params["quality"] = quality
        return base64.b64decode(self._cmd("Page.captureScreenshot", params)["data"])

    def query_selector(self, selecteur: str):
        return _Element(self, selecteur) if self.evaluate(
            f"!!document.querySelector({json.dumps(selecteur)})") else None

    # -- actions
    def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 15000):
        res = self._cmd("Page.navigate", {"url": url}, delai=timeout / 1000)
        if res.get("errorText"):
            raise ErreurCDP(f"navigation impossible : {res['errorText']}")
        fin = time.monotonic() + timeout / 1000
        while time.monotonic() < fin:
            try:
                if self.evaluate("document.readyState") in ("interactive", "complete") and \
                        str(self.evaluate("location.href")) != "about:blank":
                    return
            except ErreurCDP:
                pass
            time.sleep(0.15)

    def bring_to_front(self):
        self._cmd("Page.bringToFront")

    def close(self):
        try:
            _http(self._port, f"/json/close/{self.id}")
        finally:
            if self._session:
                self._session.fermer()
                self._session = None

    def _attendre(self, selecteur: str, timeout: int):
        fin = time.monotonic() + timeout / 1000
        while time.monotonic() < fin:
            if self.evaluate(f"!!document.querySelector({json.dumps(selecteur)})"):
                return
            time.sleep(0.2)
        raise ErreurCDP(f"element introuvable : {selecteur}")

    def click(self, selecteur: str, timeout: int = 8000):
        self._attendre(selecteur, timeout)
        s = json.dumps(selecteur)
        self.evaluate(f"document.querySelector({s}).scrollIntoView({{block:'center',inline:'center'}})")
        boite = self.evaluate(f"(() => {{ const r = document.querySelector({s}).getBoundingClientRect();"
                              f" return [r.x + r.width/2, r.y + r.height/2, r.width, r.height]; }})()")
        if not boite or boite[2] <= 0 or boite[3] <= 0:
            raise ErreurCDP(f"element invisible : {selecteur}")
        x, y = boite[0], boite[1]
        self._cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        self._cmd("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
        self._cmd("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})

    def fill(self, selecteur: str, texte: str, timeout: int = 8000):
        self._attendre(selecteur, timeout)
        s = json.dumps(selecteur)
        self.evaluate(f"(() => {{ const e = document.querySelector({s}); e.focus(); "
                      f"if (e.select) e.select(); }})()")
        self._cmd("Input.insertText", {"text": texte})

    def wait_for_timeout(self, ms: int):
        time.sleep(ms / 1000)


class Contexte:
    def __init__(self, navigateur):
        self._n = navigateur

    @property
    def pages(self):
        return self._n._pages()

    def new_page(self):
        cible = _http(self._n.port, "/json/new?about:blank", "PUT")
        if not isinstance(cible, dict) or "webSocketDebuggerUrl" not in cible:
            raise ErreurCDP("Chrome n'a pas cree d'onglet.")
        p = Page(self._n.port, cible)
        self._n._cache[cible["id"]] = p
        return p


class Navigateur:
    """Facon `browser` de Playwright, connecte au port de debug d'un Chrome deja lance."""

    def __init__(self, port: int):
        self.port = port
        self._cache: dict[str, Page] = {}
        _http(port, "/json/version")                       # leve si Chrome n'ecoute pas
        self._contexte = Contexte(self)

    @property
    def contexts(self):
        _http(self.port, "/json/version")                   # leve si Chrome a ete ferme (reconnexion)
        return [self._contexte]

    def new_context(self):
        return self._contexte

    def _pages(self):
        vivants = []
        for cible in _http(self.port, "/json/list"):
            if cible.get("type") != "page" or "webSocketDebuggerUrl" not in cible:
                continue
            p = self._cache.get(cible["id"])
            if p is None:
                p = self._cache[cible["id"]] = Page(self.port, cible)
            else:
                p._cible = cible
            vivants.append(p)
        return vivants


def connecter(port: int = 9222) -> Navigateur:
    return Navigateur(int(port))
