"""
api/auth.py — Authentification SCRIBE v5
Comptes locaux (pas LDAP) : admin crée les directeurs via /admin
JWT simple, stocké en localStorage côté client
"""
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel
from jose import jwt, JWTError
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

from app.database import get_db
from app.models import User, Notification

router   = APIRouter()
security = HTTPBearer(auto_error=False)

# Secure password hashing with bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=False)

# Secret key - MUST be set via environment variable in production
SECRET_KEY = os.getenv("SCRIBE_SECRET", None)
if not SECRET_KEY:
    raise ValueError("SCRIBE_SECRET environment variable must be set in production")

ALGORITHM  = "HS256"
TOKEN_TTL  = 12  # heures

ADMIN_USER = "dircrise"
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "Scribe2026!")


# ── Helpers ──────────────────────────────────────────────

def _hash(pw: str) -> str:
    # Bcrypt has a 72-byte limit. Newer bcrypt library versions raise 
    # ValueError instead of truncating. We truncate manually to ensure compatibility.
    return pwd_context.hash(pw[:72])

def _verify(plain_pw: str, hashed_pw: str) -> bool:
    if not plain_pw or not hashed_pw:
        return False
    # We truncate the plain password to 72 chars to match the hashing logic
    # and avoid ValueErrors from the underlying bcrypt library.
    return pwd_context.verify(plain_pw[:72], hashed_pw)

def _make_token(user_id: int, username: str, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL)
    return jwt.encode({"sub": str(user_id), "username": username, "role": role, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)

def _decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> Optional[User]:
    if not creds:
        return None
    try:
        payload = _decode_token(creds.credentials)
        uid = int(payload["sub"])
        return db.query(User).filter(User.id == uid, User.active == True).first()
    except (JWTError, Exception):
        return None

def require_admin(user: Optional[User] = Depends(get_current_user)):
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Accès admin requis")
    return user


# ── Schémas ──────────────────────────────────────────────

class LoginIn(BaseModel):
    username: str
    password: str

class UserCreate(BaseModel):
    username:     str
    display_name: str
    password:     str
    role:         str = "directeur"
    perimetre:    Optional[str] = None

class UserOut(BaseModel):
    id: int; username: str; display_name: str; role: str
    perimetre: Optional[str]; active: bool
    class Config: from_attributes = True

class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    password:     Optional[str] = None
    role:         Optional[str] = None
    perimetre:    Optional[str] = None
    active:       Optional[bool] = None


# ── Initialisation compte admin ──────────────────────────

def ensure_admin(db: Session):
    """Crée ou synchronise le compte admin avec ADMIN_PASS."""
    existing = db.query(User).filter(User.username == ADMIN_USER).first()
    if not existing:
        admin = User(
            username=ADMIN_USER,
            display_name="Directeur de Crise",
            role="admin",
            hashed_password=_hash(ADMIN_PASS),
            active=True
        )
        db.add(admin)
        db.commit()
    else:
        # Resynchroniser le hash si le mot de passe a changé (vérification sécurisée)
        if not _verify(ADMIN_PASS, existing.hashed_password):
            existing.hashed_password = _hash(ADMIN_PASS)
            db.commit()


# ── Endpoints ────────────────────────────────────────────

@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    ensure_admin(db)
    user = db.query(User).filter(User.username == body.username, User.active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    # Verify password using bcrypt
    if not _verify(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    token = _make_token(user.id, user.username, user.role)
    return {"token": token, "user": {"id": user.id, "username": user.username,
            "display_name": user.display_name, "role": user.role, "perimetre": user.perimetre}}

@router.get("/me")
def me(user: Optional[User] = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    return {"id": user.id, "username": user.username, "display_name": user.display_name,
            "role": user.role, "perimetre": user.perimetre}

@router.get("/users", response_model=List[UserOut])
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(User).order_by(User.display_name).all()

@router.post("/users", response_model=UserOut)
def create_user(body: UserCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="Nom d'utilisateur déjà pris")
    u = User(username=body.username, display_name=body.display_name,
             role=body.role, hashed_password=_hash(body.password),
             perimetre=body.perimetre, active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u

@router.put("/users/{uid}", response_model=UserOut)
def update_user(uid: int, body: UserUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == uid).first()
    if not u: raise HTTPException(404, "Utilisateur non trouvé")
    if body.display_name is not None: u.display_name = body.display_name
    if body.password     is not None: u.hashed_password = _hash(body.password)
    if body.role         is not None: u.role = body.role
    if body.perimetre    is not None: u.perimetre = body.perimetre
    if body.active       is not None: u.active = body.active
    db.commit(); db.refresh(u); return u

@router.delete("/users/{uid}")
def delete_user(uid: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == uid).first()
    if not u: raise HTTPException(404, "Utilisateur non trouvé")
    db.delete(u); db.commit()
    return {"status": "deleted"}

# ── NOTIFICATIONS ────────────────────────────────────────

@router.get("/notifications")
def get_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user: raise HTTPException(401)
    notifs = db.query(Notification).filter(
        Notification.user_id == user.id
    ).order_by(Notification.timestamp.desc()).limit(50).all()
    return [{"id": n.id, "titre": n.titre, "message": n.message,
             "type_notif": n.type_notif, "incident_id": n.incident_id,
             "task_id": n.task_id, "lu": n.lu,
             "timestamp": n.timestamp.isoformat() if n.timestamp else None}
            for n in notifs]

@router.get("/notifications/unread-count")
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user: return {"count": 0}
    c = db.query(Notification).filter(Notification.user_id == user.id, Notification.lu == False).count()
    return {"count": c}

@router.put("/notifications/{nid}/read")
def mark_read(nid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user: raise HTTPException(401)
    n = db.query(Notification).filter(Notification.id == nid, Notification.user_id == user.id).first()
    if n: n.lu = True; db.commit()
    return {"status": "ok"}

@router.put("/notifications/read-all")
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user: raise HTTPException(401)
    db.query(Notification).filter(Notification.user_id == user.id, Notification.lu == False).update({"lu": True})
    db.commit()
    return {"status": "ok"}


# ── Helper global : notifier les directeurs concernés ────

def notify_incident(db: Session, incident, action: str = "INCIDENT"):
    """Envoie une notif inbox à tous les directeurs actifs."""
    users = db.query(User).filter(User.active == True, User.role != "observateur").all()
    for u in users:
        # Si l'utilisateur a un périmètre, ne notifier que si l'incident concerne ce périmètre
        if u.perimetre:
            haystack = f"{incident.fait} {incident.analyse or ''} {incident.unite_fonctionnelle or ''} {incident.site_id}".upper()
            if u.perimetre.upper() not in haystack:
                continue
        notif = Notification(
            user_id=u.id,
            titre=f"[{incident.type_crise}] U{incident.urgency} — {incident.site_id}",
            message=incident.fait[:200],
            type_notif=action,
            incident_id=incident.id
        )
        db.add(notif)
    db.commit()
