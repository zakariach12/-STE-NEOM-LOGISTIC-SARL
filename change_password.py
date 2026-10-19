"""Change the login email and password of the invoice app: python change_password.py"""
import accounts

conf = accounts.read()
email, password = accounts.ask_in_terminal(conf.get("email"))
accounts.save(email, password)
print("OK. Redémarrez l'application (start.bat ou python serve.py).")
