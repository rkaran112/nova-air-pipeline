"""The two source systems the daily files can come from, and how to connect to them.

- MySQL is the reservation system. Its bookings table holds one row per booking record,
  as text exactly as it was delivered, plus the day it was delivered (file_date).
- MongoDB is the customer app. Its passengers collection holds one document per profile
  record, with email and phone nested under "contact".

Settings come from environment variables (see .env.example). The drivers, PyMySQL and
pymongo, are optional: they are imported only when a connection is opened, so the
file-based pipeline never needs them.
"""

import os

from dotenv import load_dotenv

from pipeline.settings import DEFAULT_ENV_FILE

BOOKINGS_TABLE = "bookings"
PASSENGERS_COLLECTION = "passengers"
# The two bookings columns that are not part of the delivered file.
BOOKING_EXTRA_COLUMNS = ("id", "file_date")
PASSENGER_COLUMNS = ("passenger_id", "full_name", "email", "phone", "date_of_birth",
                     "loyalty_tier", "updated_at")


class SourceUnavailableError(RuntimeError):
    """A source system, its driver or its password is missing, or it cannot be reached."""


def setting(name, default=None):
    load_dotenv(DEFAULT_ENV_FILE)
    return os.environ.get(name, default)


def mysql_connection(use_database=True):
    """Open a MySQL connection. The password has no default, as with the PII key."""
    try:
        import pymysql
    except ImportError as error:
        raise SourceUnavailableError(
            "PyMySQL is not installed: pip install -r requirements-sources.txt") from error
    password = setting("NOVA_MYSQL_PASSWORD")
    if not password:
        raise SourceUnavailableError("NOVA_MYSQL_PASSWORD is not set (see .env.example)")
    try:
        return pymysql.connect(
            host=setting("NOVA_MYSQL_HOST", "127.0.0.1"),
            port=int(setting("NOVA_MYSQL_PORT", "3306")),
            user=setting("NOVA_MYSQL_USER", "nova_etl"),
            password=password,
            database=setting("NOVA_MYSQL_DATABASE", "nova_source") if use_database else None,
            charset="utf8mb4", connect_timeout=5)
    except pymysql.MySQLError as error:
        raise SourceUnavailableError(f"cannot connect to MySQL: {error}") from error


def mongo_client():
    """Open a MongoDB client and check that the server answers."""
    try:
        import pymongo
    except ImportError as error:
        raise SourceUnavailableError(
            "pymongo is not installed: pip install -r requirements-sources.txt") from error
    client = pymongo.MongoClient(setting("NOVA_MONGO_URI", "mongodb://127.0.0.1:27017"),
                                 serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except pymongo.errors.PyMongoError as error:
        client.close()
        raise SourceUnavailableError(f"cannot connect to MongoDB: {error}") from error
    return client


def mongo_database_name():
    return setting("NOVA_MONGO_DATABASE", "nova_source")


def passenger_to_document(row, file_date, row_number):
    """One delivered passenger line as the customer app would store it."""
    return {"file_date": file_date.isoformat(), "row_number": row_number,
            "passenger_id": row.get("passenger_id"), "full_name": row.get("full_name"),
            "contact": {"email": row.get("email"), "phone": row.get("phone")},
            "date_of_birth": row.get("date_of_birth"), "loyalty_tier": row.get("loyalty_tier"),
            "updated_at": row.get("updated_at")}


def document_to_passenger(document):
    """The reverse: flatten the nested contact back to the file's flat columns."""
    contact = document["contact"]
    return {"passenger_id": document["passenger_id"], "full_name": document["full_name"],
            "email": contact["email"], "phone": contact["phone"],
            "date_of_birth": document["date_of_birth"],
            "loyalty_tier": document["loyalty_tier"], "updated_at": document["updated_at"]}
