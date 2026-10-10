import getpass
from main import connect, get_password_hash, validate_password
from contextlib import closing

def create_super_admin():
    username = "etd-dev"
    password = getpass.getpass("Password: ")
    validate_password(password)
    role = "Admin"
    display_name = "ETD-Admin"

    with closing(connect()) as db:
        existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            print(f"User {username} already exists.")
            return

        hashed = get_password_hash(password)
        try:
            db.execute(
                "INSERT INTO users (username, display_name, role, password_hash) VALUES (?, ?, ?, ?)",
                (username, display_name, role, hashed)
            )
            db.commit()
            print(f"Successfully created super admin: {username}")
        except Exception as e:
            print(f"Failed to create super admin: {e}")

if __name__ == "__main__":
    create_super_admin()
