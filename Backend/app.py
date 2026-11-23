import os
from collections.abc import Generator

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mysql.connector import Error as MySQLError
from mysql.connector import MySQLConnection, connect

from Admin import create_admin_router
from AdminModules import create_admin_modules_router
from Auth import create_auth_router, create_user_router
from Student import create_student_router
from Teacher import create_teacher_router

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db_connection() -> Generator[MySQLConnection, None, None]:
    required_settings = ("MYSQL_USER", "MYSQL_PASSWORD")
    missing_settings = [
        setting for setting in required_settings if os.getenv(setting) is None
    ]
    if missing_settings:
        raise HTTPException(
            status_code=503,
            detail=f"Missing database settings: {', '.join(missing_settings)}",
        )

    try:
        port = int(os.getenv("MYSQL_PORT", "3306"))
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail="MYSQL_PORT must be an integer.",
        ) from exc

    try:
        connection = connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=port,
            database=os.getenv("MYSQL_DATABASE", "school"),
            user=os.environ["MYSQL_USER"],
            password=os.environ["MYSQL_PASSWORD"],
            connection_timeout=5,
        )
    except MySQLError as exc:
        raise HTTPException(
            status_code=503,
            detail="Unable to connect to the configured MySQL database.",
        ) from exc

    try:
        yield connection
    finally:
        connection.close()


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "School management API"}


@app.get("/health/db")
def database_health(
    connection: MySQLConnection = Depends(get_db_connection),
) -> dict[str, str]:
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    except MySQLError as exc:
        raise HTTPException(
            status_code=503,
            detail="MySQL database health check failed.",
        ) from exc
    finally:
        cursor.close()

    return {"status": "ok", "database": "connected"}


app.include_router(create_auth_router(get_db_connection))
app.include_router(create_user_router(get_db_connection))
app.include_router(create_admin_router(get_db_connection))
app.include_router(create_admin_modules_router(get_db_connection))
app.include_router(create_student_router(get_db_connection))
app.include_router(create_teacher_router(get_db_connection))
