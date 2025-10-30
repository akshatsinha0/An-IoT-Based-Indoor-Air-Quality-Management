@echo off
setlocal
:: Start FastAPI
uvicorn backend.main:app --host 0.0.0.0 --port 8000