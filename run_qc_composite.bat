@echo off
cd /d "C:\Users\WoodyWiegmann\OneDrive - PFM\Desktop\Potomac"
python qc_intl_composite_deploy.py
if errorlevel 1 (
    py qc_intl_composite_deploy.py
)
pause
