"""The one login of the app (email + password), kept in config.json. The password is stored hashed."""
import getpass
import json
import os
import re
import secrets
import sys

from werkzeug.security import check_password_hash, generate_password_hash

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(email):
    return bool(EMAIL_RE.match(email or ""))


def password_problem(password):
    return "8 caractères minimum." if len(password or "") < 8 else None


def read():
    if not os.path.exists(CONFIG):
        return {}
    with open(CONFIG, encoding="utf-8") as f:
        conf = json.load(f)
    if "email" not in conf and "username" in conf:  # older versions used a user name
        conf["email"] = conf["username"]
    return conf


def save(email=None, password=None):
    conf = read()
    if email:
        conf["email"] = email.strip().lower()
        conf.pop("username", None)
    if password:
        conf["password_hash"] = generate_password_hash(password)
    conf.setdefault("secret_key", secrets.token_hex(32))
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(conf, f, indent=1)
    os.replace(tmp, CONFIG)
    return conf


def check(email, password):
    conf = read()
    return (bool(conf.get("password_hash")) and (email or "").strip().lower() == conf.get("email", "").lower()
            and check_password_hash(conf["password_hash"], password or ""))


def ask_in_terminal(current_email=None):
    """Ask for the email and password in the terminal."""
    while True:
        prompt = f"Email [{current_email}]: " if current_email else "Email: "
        email = input(prompt).strip() or (current_email or "")
        if valid_email(email):
            break
        print("Email invalide, exemple: nom@gmail.com")
    while True:
        password = getpass.getpass("Mot de passe (8 caractères minimum): ")
        problem = password_problem(password)
        if problem:
            print(problem)
        elif password != getpass.getpass("Répétez le mot de passe: "):
            print("Les deux mots de passe sont différents.")
        else:
            return email, password


def ensure():
    """On the first start, create the login: asked in the terminal, or a random one if there is no terminal."""
    conf = read()
    if conf.get("password_hash") and conf.get("email"):
        return conf
    if sys.stdin and sys.stdin.isatty():
        print("\n  Premier démarrage : choisissez l'email et le mot de passe pour vous connecter.\n", flush=True)
        email, password = ask_in_terminal()
        conf = save(email, password)
        print("\n  OK. Connectez-vous avec cet email et ce mot de passe.\n", flush=True)
    else:
        password = secrets.token_urlsafe(9)
        conf = save("admin@factures.local", password)
        print(f"\n  Premier démarrage. Email: admin@factures.local   Mot de passe: {password}\n"
              "  Changez-les dans l'application (Mon compte) ou avec change_password.bat\n", flush=True)
    return conf
