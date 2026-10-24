import sqlite3

connection = sqlite3.connect("instance/site.db")

cursor = connection.cursor()

print("\n========== TABLES ==========")

tables = cursor.execute(
    """
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
    AND name NOT LIKE 'sqlite_%'
    """
).fetchall()

for table in tables:
    print(table)


print("\n========== USERS ==========")

users = cursor.execute(
    """
    SELECT id, username, email
    FROM user
    """
).fetchall()

for user in users:
    print(user)


print("\n========== LISTINGS ==========")

listings = cursor.execute(
    """
    SELECT *
    FROM listing
    """
).fetchall()

for listing in listings:
    print(listing)


connection.close()