@echo off
title Serveur MCP Jarvis
rem Lance le serveur MCP de Jarvis en mode HTTP (serveur autonome : les clients
rem MCP distants s'y connectent). Pour Claude Desktop en local, pas besoin de ce
rem raccourci : Claude Desktop lance le serveur lui-meme (stdio). Voir docs/mcp.md.
cd /d "%~dp0"
git pull --ff-only 2>nul
set JARVIS_MCP_TRANSPORT=http
"%USERPROFILE%\.local\bin\uv.exe" run python -m jarvis.mcp_server
echo.
echo Le serveur MCP s'est arrete. Vous pouvez fermer cette fenetre.
pause
