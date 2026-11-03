-- Full refresh: empty silver so every batch in bronze is processed again, in order.
-- Bronze is untouched: it is the permanent record of what arrived.

DROP TABLE IF EXISTS silver.flights;
DROP TABLE IF EXISTS silver.passengers;
DROP TABLE IF EXISTS silver.bookings;
DROP TABLE IF EXISTS silver.quarantine;
DELETE FROM meta.reconciliation
