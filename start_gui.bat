@echo off
title Domain Rewrite Proxy
cd /d "%~dp0"
echo Starting domain proxy GUI...
venv\Scripts\python.exe proxy_gui.py