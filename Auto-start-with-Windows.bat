@echo off
rem Makes the app start by itself whenever you log in to Windows.
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
> "%STARTUP%\TpClone.bat" echo @echo off
>> "%STARTUP%\TpClone.bat" echo start "" /min "%~dp0Start-Windows.bat"
echo Done. The app will now start automatically when you log in to Windows.
echo (To undo: delete TpClone.bat from the folder that opens next.)
explorer "%STARTUP%"
pause
