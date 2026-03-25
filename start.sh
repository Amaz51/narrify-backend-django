#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Narrify Django Backend — Development Startup Script
# Run from: narrify-django-backend/
# ──────────────────────────────────────────────────────────────────────────────

set -e

VENV="$(dirname "$0")/venv/bin"
MANAGE="$(dirname "$0")/django_backend/manage.py"

echo "🔍 Checking PostgreSQL..."
if ! pg_isready -q; then
  echo "❌ PostgreSQL is not running. Please start it first:"
  echo "   brew services start postgresql@15"
  exit 1
fi

echo "🔍 Checking Redis..."
if ! redis-cli ping > /dev/null 2>&1; then
  echo "❌ Redis is not running. Please start it first:"
  echo "   brew services start redis"
  exit 1
fi

echo "📦 Running migrations..."
"$VENV/python" "$MANAGE" migrate

echo ""
echo "✅ All checks passed."
echo ""
echo "Start the following processes in separate terminals:"
echo ""
echo "  Terminal 1 — Django:"
echo "    cd django_backend"
echo "    source ../venv/bin/activate"
echo "    python manage.py runserver 8000"
echo ""
echo "  Terminal 2 — Celery worker:"
echo "    cd django_backend"
echo "    source ../venv/bin/activate"
echo "    celery -A narrify worker -l info --concurrency=4"
echo ""
echo "  Terminal 3 — FastAPI (existing backend):"
echo "    cd ../narrify-backend-complete"
echo "    source venv/bin/activate"
echo "    uvicorn app.main:app --reload --port 8001"
echo ""
echo "  Terminal 4 — Next.js frontend:"
echo "    cd ../frontend"  # or Frontend
echo "    npm run dev"
echo ""
