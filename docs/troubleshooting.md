# Troubleshooting Guide

Solutions to common issues in the Legalassist-AI repository.

## Celery Worker Issues
If the Celery worker fails to start, verify your `REDIS_URL` environment variable is correctly set and reachable.

## Database Connection Limits
SQLite may throw database locked errors under heavy concurrent write operations. Ensure database connection pools are tuned properly.
