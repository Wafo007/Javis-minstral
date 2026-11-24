"""NETWORK SECURITY AGENT : scan TCP « connect » natif (lent et borne), prise de banniere, TLS. Hote UNIQUE enregistre, jamais de plage.
Si nmap est disponible, le moteur de decision le prefere (voir outils.py) ; ce module est la solution de repli reelle."""
from __future__ import annotations

import socket
import ssl
from concurrent.futures import ThreadPoolExecutor

from modes.ghost_protocol.security.modele import Gravite, Preuve, Resultat

PORTS_COURANTS = [21, 22, 23, 25, 53, 80, 110, 111, 135, 139, 143, 389, 443, 445, 465, 587, 993, 995, 1433, 1521, 2049, 2375, 2376,
                  3000, 3306, 3389, 4000, 4443, 5000, 5432, 5601, 5900, 5985, 6379, 7001, 8000, 8008, 8080, 8081, 8443, 8888, 9000,
                  9090, 9200, 11211, 27017]
RISQUES = {  # port -> (service, gravite, impact)
    21: ("FTP", Gravite.MOYENNE, "Protocole en clair ; connexion anonyme possible selon configuration."),
    23: ("Telnet", Gravite.ELEVEE, "Administration en clair."),
    445: ("SMB", Gravite.MOYENNE, "Partage de fichiers exposé."), 135: ("RPC", Gravite.FAIBLE, "Service Windows exposé."),
    139: ("NetBIOS", Gravite.FAIBLE, "Service Windows exposé."), 3389: ("RDP", Gravite.MOYENNE, "Bureau à distance exposé."),
    1433: ("MSSQL", Gravite.MOYENNE, "Base de données exposée."), 3306: ("MySQL", Gravite.MOYENNE, "Base de données exposée."),
    5432: ("PostgreSQL", Gravite.MOYENNE, "Base de données exposée."), 1521: ("Oracle", Gravite.MOYENNE, "Base de données exposée."),
    6379: ("Redis", Gravite.ELEVEE, "Redis sans authentification par défaut."), 27017: ("MongoDB", Gravite.ELEVEE, "MongoDB exposé."),
    11211: ("Memcached", Gravite.MOYENNE, "Cache exposé."), 9200: ("Elasticsearch", Gravite.ELEVEE, "Index lisibles si non protégé."),
    2375: ("Docker API (non chiffrée)", Gravite.CRITIQUE, "Contrôle total de l'hôte si accessible."), 5900: ("VNC", Gravite.MOYENNE, "Bureau à distance exposé."),
    5985: ("WinRM", Gravite.MOYENNE, "Administration à distance exposée."),
}


def _sonder(garde, hote, port, delai):
    garde.autoriser("tcp_connect", hote, None, "", f"connexion TCP {port}", "reseau", rps=40)
    try:
        with socket.create_connection((hote, port), timeout=delai) as s:
            s.settimeout(delai)
            banniere = ""
            try:
                if port in (80, 3000, 4000, 5000, 8000, 8008, 8080, 8081, 8888, 9000, 9090):
                    s.sendall(b"HEAD / HTTP/1.0\r\nUser-Agent: JarvisSecurityAudit/1.0\r\n\r\n")
                banniere = s.recv(160).decode("latin-1", "replace").strip().replace("\r", " ").replace("\n", " ")
            except OSError:
                pass
            return port, True, banniere
    except OSError:
        return port, False, ""


def analyser(ctx, ports=None, delai: float = 1.0):
    cible = ctx.cible
    if cible.type == "code_local":
        return
    hote = cible.hote
    liste = sorted(set(ports or PORTS_COURANTS) | set(cible.ports))[:200]
    ouverts = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(_sonder, ctx.garde, hote, p, delai) for p in liste]
        for f in futs:
            try:
                p, ok, ban = f.result()
            except Exception as e:                       # RefusPerimetre (arret d'urgence, budget...) : on arrete proprement
                for g in futs:
                    g.cancel()
                from modes.ghost_protocol.security.perimetre import RefusPerimetre
                if isinstance(e, RefusPerimetre):
                    ctx.limiter(f"scan réseau interrompu : {e}")
                    break
                continue
            if ok:
                ouverts[p] = ban
    ctx.faits["ports_ouverts"] = sorted(ouverts)
    ctx.faits["scan_reseau"] = "natif (TCP connect, %d ports sondés)" % len(liste)
    ctx.observer(f"Ports TCP ouverts ({len(liste)} sondés) : {', '.join(map(str, sorted(ouverts))) or 'aucun'}")
    for p, ban in sorted(ouverts.items()):
        if p in RISQUES and p not in cible.ports:
            nom, grav, impact = RISQUES[p]
            ctx.ajouter(Resultat(agent="RESEAU", categorie="service-expose", titre=f"Service {nom} accessible (port {p})",
                                 description=f"Le port {p}/tcp de {hote} accepte les connexions.", gravite=grav, composant=f"{nom} :{p}",
                                 ressource=f"{hote}:{p}", methode="scan TCP connect natif", confiance=0.8, impact=impact,
                                 recommandation="Restreindre l'accès par pare-feu ou lier le service à localhost.", references=["CWE-668"],
                                 cle_validation="port_ouvert", donnees={"hote": hote, "port": p},
                                 preuves=[Preuve(f"TCP connect {p}", None, ban[:120] or "connexion acceptée")]))
    if cible.schema == "https" or any(p in ouverts for p in (443, 8443)):
        _tls(ctx, hote, cible.ports[0] if cible.schema == "https" else (443 if 443 in ouverts else 8443))


def _tls(ctx, hote, port):
    from modes.ghost_protocol.security.perimetre import RefusPerimetre
    try:
        ctx.garde.autoriser("tls_handshake", hote, port, "", f"TLS {port}", "reseau")
    except RefusPerimetre:
        return
    ctx2 = ssl.create_default_context()
    ctx2.check_hostname, ctx2.verify_mode = False, ssl.CERT_NONE
    try:
        with socket.create_connection((hote, port), timeout=3) as s, ctx2.wrap_socket(s, server_hostname=hote) as t:
            version, cert = t.version(), t.getpeercert(binary_form=False) or {}
            ctx.observer(f"TLS {hote}:{port} : protocole négocié {version}")
            ctx.faits["tls"] = version
    except (OSError, ssl.SSLError) as e:
        ctx.limiter(f"TLS non analysable sur {port} : {type(e).__name__}")
        return
    for nom, v in (("TLSv1", ssl.TLSVersion.TLSv1), ("TLSv1.1", ssl.TLSVersion.TLSv1_1)):
        try:
            c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            c.check_hostname, c.verify_mode = False, ssl.CERT_NONE
            c.minimum_version = c.maximum_version = v
            c.set_ciphers("ALL:@SECLEVEL=0")
            ctx.garde.autoriser("tls_handshake", hote, port, "", f"TLS {nom}", "reseau")
            with socket.create_connection((hote, port), timeout=3) as s, c.wrap_socket(s, server_hostname=hote):
                ctx.ajouter(Resultat(agent="RESEAU", categorie="tls", titre=f"Protocole obsolète {nom} accepté", description=f"{hote}:{port} accepte {nom}.",
                                     gravite=Gravite.MOYENNE, composant=f"TLS :{port}", ressource=f"{hote}:{port}", methode="poignée de main TLS forcée",
                                     confiance=0.9, impact="Chiffrement affaibli (attaques de rétrogradation).",
                                     recommandation="Désactiver TLS 1.0/1.1 ; n'autoriser que TLS 1.2+.", references=["CWE-326"],
                                     cle_validation="tls_ancien", donnees={"hote": hote, "port": port, "version": nom},
                                     preuves=[Preuve(f"handshake {nom}", None, "poignée de main réussie")]))
        except (OSError, ssl.SSLError, ValueError):
            pass
