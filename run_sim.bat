@echo off
setlocal
:: Simulate IAQ readings
python backend/simulator.py --api http://127.0.0.1:8000 --period 5