import sqlite3
import random

DB_PATH = "jobportal.db"

def generate_contact():
    """Generate a random Indian mobile number."""
    prefix = random.choice(["98", "99", "97", "96", "95", "94", "93", "92", "90", "89", "88"])
    number = prefix + "".join([str(random.randint(0, 9)) for _ in range(8)])
    return number

def update_contacts():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # fetch users without contact OR empty contact
    cur.execute("""
        SELECT id, name FROM users
        WHERE contact IS NULL OR contact = ''
    """)
    users = cur.fetchall()

    print(f"Found {len(users)} users without contact numbers.\n")

    for user in users:
        uid, name = user
        contact = generate_contact()

        cur.execute("""
            UPDATE users SET contact = ? WHERE id = ?
        """, (contact, uid))

        print(f"Updated {name} (id={uid}) → {contact}")

    conn.commit()
    conn.close()
    print("\n✔ All missing contacts updated successfully!")

if __name__ == "__main__":
    update_contacts()
