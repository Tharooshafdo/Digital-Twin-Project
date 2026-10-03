"""Argon2 credentials and expiring hashed opaque sessions; server-side roles."""
import hashlib
import secrets
from datetime import timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import select
from . import db

hasher = PasswordHasher()
ROLES = {"viewer": 0, "engineer": 1, "administrator": 2}

def create_user(conn, username, role, project_ids, password=None):
    if role not in ROLES or not username or len(username) > 80:
        raise ValueError("Invalid username or role")
    password = password or secrets.token_urlsafe(20)
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    user_id = db.uid("user")
    conn.execute(db.users.insert().values(id=user_id, username=username,
        role=role, password_hash=hasher.hash(password), created_at=db.now()))
    for project_id in project_ids:
        conn.execute(db.memberships.insert().values(user_id=user_id, project_id=project_id))
    return {"id": user_id, "username": username, "role": role, "password": password}

def login(conn, username, password):
    user = conn.execute(select(db.users).where(db.users.c.username == username)).mappings().first()
    # Run an Argon2 check for unknown accounts too; generic error response.
    hashed = user["password_hash"] if user else hasher.hash(secrets.token_urlsafe(20))
    try:
        hasher.verify(hashed, password)
    except VerificationError:
        raise ValueError("Invalid credentials")
    if not user:
        raise ValueError("Invalid credentials")
    token = secrets.token_urlsafe(32)
    conn.execute(db.sessions.insert().values(token_hash=hashlib.sha256(token.encode()).hexdigest(),
        user_id=user["id"], expires_at=db.now()+timedelta(hours=8)))
    return token, {k: user[k] for k in ("id", "username", "role")}

def current_user(conn, token):
    if not token:
        return None
    q = select(db.users).join(db.sessions, db.sessions.c.user_id == db.users.c.id).where(
        db.sessions.c.token_hash == hashlib.sha256(token.encode()).hexdigest(), db.sessions.c.expires_at > db.now())
    result = conn.execute(q).mappings().first()
    return dict(result) if result else None

def allowed(conn, user, project_id, role="viewer"):
    if ROLES[user["role"]] < ROLES[role]:
        return False
    return conn.scalar(select(db.memberships.c.user_id).where(db.memberships.c.user_id == user["id"],
        db.memberships.c.project_id == project_id)) is not None
