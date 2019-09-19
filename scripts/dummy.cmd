@echo off
start "Server" cmd /c "py.exe server.py & echo. & echo. & pause & exit"
start "Client" cmd /c "py.exe client.py & echo. & echo. & pause & exit"
