"""Verify role column migration and CLI commands. Delete after running."""
from app import create_app
from app.models import User
from sqlalchemy import inspect, text

app = create_app()

with app.app_context():
    # Confirm role column now exists
    inspector = inspect(app.extensions['sqlalchemy'].engine)
    cols = [c['name'] for c in inspector.get_columns('users')]
    print(f"'role' column in users table : {'role' in cols}")
    print(f"All columns: {cols}\n")

    # Confirm existing users are untouched
    total  = User.query.count()
    admins = User.query.filter_by(is_admin=True).all()
    print(f"Total users : {total}")
    for a in admins:
        print(f"  Admin: {a.full_name} | {a.email} | role={a.role!r} | is_super_admin={a.is_super_admin}")

    varsha = User.query.filter_by(email='varsha.patil23@skillswap.com').first()
    print(f"\nVarsha account exists: {varsha is not None}")

# CLI commands registered?
cmds = list(app.cli.commands.keys())
print(f"\nCLI commands: {cmds}")
print(f"create-admin       : {'create-admin' in cmds}")
print(f"create-super-admin : {'create-super-admin' in cmds}")
