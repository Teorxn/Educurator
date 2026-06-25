-- Create the langfuse database used by the langfuse service.
-- This script runs when Postgres is first initialized.
SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
