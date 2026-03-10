@echo off
title Value + Momentum Composite Screener
echo ======================================================================
echo   VALUE + MOMENTUM COMPOSITE SCREENER
echo   Generating basket, Excel workbook, HTML dashboard, TV watchlist...
echo ======================================================================
echo.

cd /d "C:\Users\WoodyWiegmann\OneDrive - PFM\Desktop\Potomac\screener"
python value_momentum_screener.py %*

echo.
echo ======================================================================
echo   DONE. Opening dashboard...
echo ======================================================================

start "" "C:\Users\WoodyWiegmann\OneDrive - PFM\Desktop\Potomac\screener\value_momentum_dashboard.html"

pause
