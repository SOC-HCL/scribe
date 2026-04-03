#!/usr/bin/env python3
"""
setup.py — Initialisation de SCRIBE à partir du fichier config.xml

Usage :
    python setup.py              # utilise config.xml dans le dossier courant
    python setup.py mon_ch.xml   # utilise un fichier XML personnalisé
"""

import sys
import os
import xml.etree.ElementTree as ET
import json
import datetime
import bcrypt
from passlib.context import CryptContext

# Monkeypatch bcrypt to truncate automatically, as passlib (unmaintained) 
# triggers ValueErrors with bcrypt 4.0+ during its internal checks (detect_wrap_bug).
_orig_hashpw = bcrypt.hashpw
def _patched_hashpw(password, salt):
    if isinstance(password, str):
        password = password.encode("utf-8")
    # Bcrypt has a 72-byte limit for the secret.
    if len(password) > 72:
        password = password[:72]
    return _orig_hashpw(password, salt)
bcrypt.hashpw = _patched_hashpw

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

CONFIG_FILE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE_DIR, "config.xml")

# Use bcrypt for password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=False)

def _hash(pw: str) -> str:
    # Truncate to 72 characters to avoid ValueError with bcrypt 4.0+
    return pwd_context.hash(pw[:72])

def _txt(el, tag, default=""):
    node = el.find(tag)
    return (node.text or "").strip() if node is not None else default


def banner(msg):
    print(f"\n  \033[96m{msg}\033[0m")


def ok(msg):
    print(f"  \033[92m✓\033[0m  {msg}")


def warn(msg):
    print(f"  \033[93m⚠\033[0m  {msg}")


def err(msg):
    print(f"  \033[91m✗\033[0m  {msg}")


# ── Lecture du XML ─────────────────────────────────────────────────────
def load_config(path):
    if not os.path.exists(path):
        err(f"Fichier introuvable : {path}")
        sys.exit(1)
    try:
        tree = ET.parse(path)
        return tree.getroot()
    except ET.ParseError as e:
        err(f"Erreur XML : {e}")
        err("Vérifiez que le fichier est bien encodé en UTF-8 et que le XML est valide.")
        sys.exit(1)


# ── Base de données ────────────────────────────────────────────────────
def init_db():
    from app.database import engine, Base, SessionLocal
    import app.models  # noqa — enregistre tous les modèles
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


# ── Sites ──────────────────────────────────────────────────────────────
def setup_sites(db, root):
    from app.models import Hospital
    sites_el = root.find("sites")
    if sites_el is None:
        warn("Section <sites> absente — aucun site créé.")
        return []

    created, updated = 0, 0
    site_names = []
    for s in sites_el.findall("site"):
        nom  = _txt(s, "nom")
        if not nom:
            continue
        lat  = float(_txt(s, "latitude", "48.8566"))
        lng  = float(_txt(s, "longitude", "2.3522"))
        adr  = _txt(s, "adresse")
        tel  = _txt(s, "telephone_garde") or None

        existing = db.query(Hospital).filter(Hospital.nom == nom).first()
        if existing:
            existing.latitude = lat; existing.longitude = lng
            existing.adresse  = adr; existing.telephone_garde = tel
            updated += 1
        else:
            db.add(Hospital(nom=nom, latitude=lat, longitude=lng,
                            adresse=adr, telephone_garde=tel))
            created += 1
        site_names.append(nom)

    db.commit()
    ok(f"Sites : {created} créé(s), {updated} mis à jour  →  {site_names}")
    return site_names


# ── Unités fonctionnelles ──────────────────────────────────────────────
def setup_ufs(db, root, site_names):
    from app.models import Hospital, UniteFonctionnelle
    ufs_el = root.find("unites_fonctionnelles")
    if ufs_el is None:
        warn("Section <unites_fonctionnelles> absente — UF ignorées.")
        warn("  → Utilisez 'python import_uf2.py' pour importer depuis un fichier FICOM.")
        return

    site_nom = ufs_el.get("site", site_names[0] if site_names else "")
    site = db.query(Hospital).filter(Hospital.nom == site_nom).first()
    if not site:
        warn(f"Site '{site_nom}' introuvable — UF ignorées pour ce site.")
        return

    created = 0
    for uf_el in ufs_el.findall("uf"):
        code    = uf_el.get("code", "").strip()
        pole    = uf_el.get("pole", "").strip()
        libelle = (uf_el.text or "").strip()
        if not code or not libelle:
            continue
        existing = db.query(UniteFonctionnelle).filter(
            UniteFonctionnelle.code_uf == code,
            UniteFonctionnelle.hospital_id == site.id
        ).first()
        if not existing:
            db.add(UniteFonctionnelle(
                code_uf=code, libelle=libelle,
                pole=pole, hospital_id=site.id
            ))
            created += 1

    db.commit()
    ok(f"UF : {created} unité(s) fonctionnelle(s) créée(s) pour «{site_nom}»")


# ── Compte admin ───────────────────────────────────────────────────────
def setup_admin(db, root):
    from app.models import User
    adm = root.find("admin")
    if adm is None:
        warn("Section <admin> absente — compte admin ignoré.")
        return None, None

    login    = _txt(adm, "login", "dircrise")
    password = _txt(adm, "password", "Scribe2026!")
    display  = _txt(adm, "nom_affiche", "Directeur de Crise")

    existing = db.query(User).filter(User.username == login).first()
    if existing:
        existing.hashed_password = _hash(password)
        existing.display_name    = display
        existing.role            = "admin"
        existing.active          = True
        db.commit()
        ok(f"Admin mis à jour : @{login}")
    else:
        db.add(User(
            username=login, display_name=display,
            role="admin", hashed_password=_hash(password), active=True
        ))
        db.commit()
        ok(f"Admin créé : @{login}")

    return login, password


# ── config.js pour le frontend ─────────────────────────────────────────
def _parse_federation(root):
    """Lit la section <federation> du config.xml."""
    fed_el = root.find("federation")
    if fed_el is None:
        return {"enabled": "false"}
    return {
        "enabled":             (fed_el.findtext("enabled")             or "false").strip(),
        "collecteur_url":      (fed_el.findtext("collecteur_url")      or "").strip(),
        "token":               (fed_el.findtext("token")               or "").strip(),
        "intervalle_secondes": (fed_el.findtext("intervalle_secondes") or "120").strip(),
        "share_details":       (fed_el.findtext("share_details")       or "true").strip(),
        "share_min_urgency":   (fed_el.findtext("share_min_urgency")   or "1").strip(),
    }



def generate_config_js(root, site_names):
    """
    Génère app/static/config.js avec :
      - SCRIBE_CONFIG.etablissement  (nom, sigle)
      - SCRIBE_CONFIG.directeurs     (liste)
      - SCRIBE_CONFIG.annuaire_normal
      - SCRIBE_CONFIG.annuaire_secours
    Ce fichier est chargé par index.html avant le JS principal.
    """
    etab_el = root.find("etablissement")
    nom_etab = _txt(etab_el, "nom", "Mon Établissement") if etab_el is not None else "Mon Établissement"
    sigle    = _txt(etab_el, "sigle", "CH") if etab_el is not None else "CH"

    # Directeurs
    dirs = []
    dirs_el = root.find("directeurs")
    for d in (list(dirs_el) if dirs_el is not None else []):
        nom  = _txt(d, "nom")
        fonc = _txt(d, "fonction")
        abr  = _txt(d, "abreviation")
        if nom:
            dirs.append({"nom": nom, "fonction": fonc, "abreviation": abr})

    # Annuaires
    def parse_annuaire(tag):
        result = []
        el = root.find(tag)
        if el is None:
            return result
        for c in el.findall("contact"):
            result.append({
                "service": c.get("service", ""),
                "local":   c.get("local", ""),
                "tel":     c.get("tel", ""),
                "note":    c.get("note", ""),
            })
        return result

    ann_normal  = parse_annuaire("annuaire_normal")
    ann_secours = parse_annuaire("annuaire_secours")

    # Section IA
    # Langue de l'interface
    langue = (root.findtext("langue") or "fr").strip().lower()[:5]

    ia_el = root.find("ia")
    ia_cfg = {}
    if ia_el is not None:
        ia_cfg = {
            "fournisseur": (ia_el.findtext("fournisseur") or "albert").strip(),
            "cle_api":     (ia_el.findtext("cle_api")     or "").strip(),
            "modele":      (ia_el.findtext("modele")      or "").strip(),
            "url_base":    (ia_el.findtext("url_base")    or "").strip(),
        }

    config = {
        "etablissement":  {"nom": nom_etab, "sigle": sigle},
        "directeurs":     dirs,
        "annuaire_normal":  ann_normal,
        "annuaire_secours": ann_secours,
        "langue":         langue,
        "ia":             ia_cfg,
        "federation":     _parse_federation(root),
    }

    out_dir = os.path.join(BASE_DIR, "app", "static")
    os.makedirs(out_dir, exist_ok=True)
    
    # We always write to the static folder so the web server can serve it
    out_path = os.path.join(out_dir, "config.js")
    
    # We also persist in /data/ for backup/persistence purposes if directory exists
    data_dir = os.environ.get("SCRIBE_DATA_DIR", "")
    persist_path = os.path.join(data_dir, "config.js") if data_dir and os.path.isdir(data_dir) else None

    def write_cfg(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("// Généré automatiquement par setup.py — ne pas éditer manuellement\n")
            f.write(f"// Établissement : {nom_etab} | Généré le : {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
            f.write("const SCRIBE_CONFIG = ")
            f.write(json.dumps(config, ensure_ascii=False, indent=2))
            f.write(";\n")

    write_cfg(out_path)
    if persist_path:
        write_cfg(persist_path)

    ok(f"config.js généré : {len(dirs)} directeur(s), {len(ann_normal)} contacts nominaux, "
       f"{len(ann_secours)} contacts secours")
    return config


def patch_auth(root):
    """Updates ADMIN_USER and ADMIN_PASS in auth.py via environment variable instead"""
    adm = root.find("admin")
    if adm is None:
        return
    password = _txt(adm, "password", "Scribe2026!")
    # Note: ADMIN_PASSWORD should be set via environment variable in production
    ok(f"Tip: Set ADMIN_PASSWORD environment variable for custom admin password (current: {password[:3]}***)")


# ── MAIN ───────────────────────────────────────────────────────────────
def main():
    print("\n" + "═" * 62)
    print("  🏥  SCRIBE — Initialisation de l'établissement")
    print("═" * 62)
    print(f"\n  Fichier de configuration : {CONFIG_FILE}\n")

    root = load_config(CONFIG_FILE)

    etab_el = root.find("etablissement")
    if etab_el is not None:
        banner(f"Établissement : {_txt(etab_el, 'nom')} ({_txt(etab_el, 'sigle')})")

    banner("1/5  Base de données…")
    db = init_db()

    banner("2/5  Sites géographiques…")
    site_names = setup_sites(db, root)

    banner("3/5  Unités fonctionnelles…")
    setup_ufs(db, root, site_names)

    banner("4/5  Compte administrateur…")
    login, password = setup_admin(db, root)
    patch_auth(root)

    banner("5/5  Génération config.js (interface web)…")
    cfg = generate_config_js(root, site_names)

    db.close()

    # ── Résumé final ──────────────────────────────────────────────────
    etab = cfg.get("etablissement", {})
    print("\n" + "═" * 62)
    print("  ✅  Initialisation terminée avec succès !")
    print("═" * 62)
    print(f"""
  Établissement  : {etab.get('nom')} ({etab.get('sigle')})
  Sites          : {len(site_names)}  →  {', '.join(site_names[:3])}{'…' if len(site_names)>3 else ''}
  Directeurs     : {len(cfg['directeurs'])}
  Contacts (nom) : {len(cfg['annuaire_normal'])}
  Contacts (sec) : {len(cfg['annuaire_secours'])}
  Fournisseur IA  : {cfg.get('ia',{}).get('fournisseur','albert')}

  ─── DÉMARRAGE ──────────────────────────────────────────
  $ python main.py
  Puis ouvrez : http://localhost:8000

  ─── CONNEXION INITIALE ─────────────────────────────────
  Login    : {login}
  Mot de passe : {password}

  ⚠️  CHANGEZ LE MOT DE PASSE après la première connexion !
     Icône utilisateur (haut à droite) → Panneau admin
""")
    print("═" * 62 + "\n")


if __name__ == "__main__":
    main()
