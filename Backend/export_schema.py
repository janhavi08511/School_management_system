
import mysql.connector

connection = mysql.connector.connect(
    host="localhost",
    port=3306,
    user="root",
    password="root123",
    database="school"
)

cursor = connection.cursor()

with open("school_actual_schema.txt", "w", encoding="utf-8") as file:
    cursor.execute("SHOW TABLES")
    tables = [row[0] for row in cursor.fetchall()]

    for table in tables:
        cursor.execute(f"SHOW CREATE TABLE `{table}`")
        result = cursor.fetchone()

        file.write("\n\n" + "=" * 80 + "\n")
        file.write(f"TABLE: {table}\n")
        file.write("=" * 80 + "\n")
        file.write(result[1] + ";\n")

print(f"Exported {len(tables)} tables successfully.")
cursor.close()
connection.close()
