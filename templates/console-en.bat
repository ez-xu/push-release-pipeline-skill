@echo off
REM Console messages are ASCII; see CONSOLE_MESSAGES in prp_setup.py.
setlocal EnableExtensions EnableDelayedExpansion

REM ---- locate the pipeline relative to this file (no path is baked in) -----
set "CI=%~dp0"
if "%CI:~-1%"=="\" set "CI=%CI:~0,-1%"
for %%i in ("%CI%\..") do set "REPO=%%~fi"
set "ENTRY=%CI%\lib\run_pipeline.py"
for %%i in ("%REPO%") do set "NAME=%%~nxi"
if not exist "%ENTRY%" goto noentry

REM ---- never leave __pycache__ behind: an untracked file under .ci/ would
REM ---- dirty the work tree, and the pipeline refuses to run on a dirty tree.
set "PYTHONDONTWRITEBYTECODE=1"

REM ---- resolve a python interpreter at run time (no path is baked in) -----
set "PY="
call :trypy "%PRP_PYTHON%"
call :trypy python
call :trypy py
call :trypy python3
if not defined PY goto nopython

REM ---- first token: the mode ---------------------------------------------
set "RETURN="
set "MODE=interactive"
if /I "%~1"=="check"   set "MODE=check"
if /I "%~1"=="dry-run" set "MODE=dryrun"
if /I "%~1"=="dryrun"  set "MODE=dryrun"
if /I "%~1"=="release" set "MODE=release"
if /I "%~1"=="verify"  set "MODE=verify"
if /I "%~1"=="hook"    set "MODE=hook"
if /I "%~1"=="help"    set "MODE=help"
if /I "%~1"=="-h"      set "MODE=help"
if /I "%~1"=="--help"  set "MODE=help"
if "%MODE%"=="interactive" if not "%~1"=="" goto badmode
if not "%MODE%"=="interactive" shift

REM ---- second token: the hook action -------------------------------------
set "HOOKCMD=status"
if not "%MODE%"=="hook" goto argsdone
if "%~1"=="" goto argsdone
set "HOOKCMD=%~1"
shift
:argsdone

REM ---- collect the remaining arguments ----------------------------------
set "EXTRA="
set "ASSUME_YES="
set "LEGEND="
goto collect
:collect
if "%~1"=="" goto collected
if /I "%~1"=="-y" goto collect_yes
set "EXTRA=%EXTRA% %~1"
goto collect_next
:collect_yes
set "ASSUME_YES=1"
:collect_next
shift
goto collect
:collected

if "%MODE%"=="interactive" goto menu_init
if "%MODE%"=="help"    goto usage
if "%MODE%"=="hook"    goto do_hook
if "%MODE%"=="check"   goto do_check
if "%MODE%"=="dryrun"  goto do_dryrun
if "%MODE%"=="verify"  goto do_verify
if "%MODE%"=="release" goto do_release
goto usage

REM ===========================================================================
REM Interactive menu (double-click, or run with no arguments)
REM ===========================================================================
:menu_init
set "EMPTY=0"
goto menu

:menu
set "RETURN=menu"
call :hookstate
echo.
echo ============================================================
echo %NAME%  release console
echo ============================================================
if /I "%HOOKSTATE%"=="INSTALLED" echo  push hook : installed  releases also run on every git push
if /I "%HOOKSTATE%"=="MISSING"   echo  push hook : missing    releases are manual only (default)
if /I "%HOOKSTATE%"=="FOREIGN"   echo  push hook : FOREIGN    another tool owns it; left untouched
if /I "%HOOKSTATE%"=="UNKNOWN"   echo  push hook : unknown    could not query it
echo.
echo   1) Check + release     readiness report, then a confirmed real release
echo   2) Check only          read-only; publishes nothing
echo   3) Dry run             build + version cross-check, stop before publishing
echo   4) Install push hook   every git push to the release branch triggers a release
echo   5) Remove push hook    back to manual releases
echo   6) Verify a release    re-check an already published release
echo   Q) Quit
echo.
set "CHOICE="
set /p "CHOICE=Select [1]: "
if errorlevel 1 goto menu_noinput
if not defined CHOICE goto menu_noinput
set "EMPTY=0"
REM Keep only the first line: a redirected stdin can deliver several lines at once,
REM and a value with an embedded newline makes cmd report a bogus syntax error.
set "FIRST="
for /f "delims=" %%c in ("!CHOICE!") do if not defined FIRST set "FIRST=%%c"
set "CHOICE=%FIRST%"
if /I "%CHOICE%"=="1" goto menu_check_release
if /I "%CHOICE%"=="2" goto menu_check
if /I "%CHOICE%"=="3" goto menu_dryrun
if /I "%CHOICE%"=="4" goto menu_hook_on
if /I "%CHOICE%"=="5" goto menu_hook_off
if /I "%CHOICE%"=="6" goto menu_verify
if /I "%CHOICE%"=="Q" goto menu_quit
if /I "%CHOICE%"=="quit" goto menu_quit
echo.
echo [release] unknown choice: %CHOICE%
goto menu_pause

:menu_noinput
REM Empty input is not a choice: it must not fire the default action, and an
REM exhausted stdin must not spin the menu forever.
set /a EMPTY+=1
if %EMPTY% GEQ 3 goto menu_quit
echo.
echo [release] no choice entered - enter a number, or Q to quit.
goto menu_pause

:menu_check_release
echo.
echo [release] readiness check (read only, publishes nothing)
set "LEGEND=1"
call :run check
echo.
echo [release] REAL RELEASE
echo [release]   This TAGS the commit, PUSHES the tag and CREATES a release.
echo [release]   The pipeline refuses on a dirty work tree - commit first.
echo.
set "ANSWER="
set /p "ANSWER=[release] type YES to publish, anything else returns to the menu: "
if /I not "%ANSWER%"=="YES" goto menu_aborted
echo.
call :run release
goto done

:menu_aborted
echo.
echo [release] aborted - nothing was published.
set "RC=0"
goto done

:menu_check
echo.
set "LEGEND=1"
call :run check
goto done

:menu_dryrun
echo.
echo [release] DRY RUN - builds and cross-checks the version, then stops.
echo [release] A dry run never exercises the upload or the read-back, so passing
echo [release] one is not evidence that a real release will succeed.
echo.
set "LEGEND=1"
call :run release --dry-run
goto done

:menu_hook_on
echo.
call :hookstate
if /I "%HOOKSTATE%"=="FOREIGN" goto hook_foreign
if /I "%HOOKSTATE%"=="INSTALLED" goto hook_already_on
call :run install-hook
if not "%RC%"=="0" goto done
echo [release] push-triggered releases are now ON.
echo [release] a failed run does not block the push unless config hook.mode is gate.
goto done

:menu_hook_off
echo.
call :hookstate
if /I "%HOOKSTATE%"=="FOREIGN" goto hook_foreign
if /I "%HOOKSTATE%"=="MISSING" goto hook_already_off
call :run uninstall-hook
if not "%RC%"=="0" goto done
echo [release] push-triggered releases are now OFF (default).
goto done

:menu_verify
echo.
echo [release] Enter the tag to verify; leave it blank for the current version.
set "VTAG="
set /p "VTAG=tag: "
set "LEGEND=1"
if not defined VTAG goto menu_verify_now
call :run verify --tag "%VTAG%"
goto done
:menu_verify_now
call :run verify
goto done

:menu_quit
echo.
echo [release] bye.
set "RC=0"
set "RETURN="
goto done

:menu_pause
echo.
echo [release] -- press any key to return to the menu --
pause >nul
goto menu

REM ===========================================================================
REM hook on / off / status  -- the push pipeline is OFF by default
REM ===========================================================================
:do_hook
if /I "%HOOKCMD%"=="on"      goto do_hook_on
if /I "%HOOKCMD%"=="enable"  goto do_hook_on
if /I "%HOOKCMD%"=="off"     goto do_hook_off
if /I "%HOOKCMD%"=="disable" goto do_hook_off
if /I "%HOOKCMD%"=="status"  goto do_hook_status
echo [release] unknown hook action: %HOOKCMD%
goto hook_usage

:do_hook_status
call :hookstate
goto hook_report

:do_hook_on
call :hookstate
if /I "%HOOKSTATE%"=="FOREIGN" goto hook_foreign
if /I "%HOOKSTATE%"=="INSTALLED" goto hook_already_on
echo.
call :run install-hook
if not "%RC%"=="0" goto done
echo [release] push-triggered releases are now ON.
echo [release] a failed run does not block the push unless config hook.mode is gate.
goto done

:do_hook_off
call :hookstate
if /I "%HOOKSTATE%"=="FOREIGN" goto hook_foreign
if /I "%HOOKSTATE%"=="MISSING" goto hook_already_off
echo.
call :run uninstall-hook
if not "%RC%"=="0" goto done
echo [release] push-triggered releases are now OFF (default).
echo [release] publish by hand with: .ci\release.bat release
goto done

:hook_report
if /I "%HOOKSTATE%"=="INSTALLED" echo  push hook : installed  releases also run on every git push
if /I "%HOOKSTATE%"=="MISSING"   echo  push hook : missing    releases are manual only (default)
if /I "%HOOKSTATE%"=="FOREIGN"   echo  push hook : FOREIGN    another tool owns it; left untouched
if /I "%HOOKSTATE%"=="UNKNOWN"   echo  push hook : unknown    could not query it
if /I "%HOOKSTATE%"=="INSTALLED" echo [release] turn it off with: .ci\release.bat hook off
if /I "%HOOKSTATE%"=="MISSING"   echo [release] turn it on  with: .ci\release.bat hook on
set "RC=0"
goto done

:hook_foreign
echo.
echo [release] .git/hooks/pre-push exists but is NOT the release pipeline hook.
echo [release] refusing to replace or delete a hook this tool did not install.
echo [release] merge them by hand, or move the other hook aside first.
set "RC=2"
goto done

:hook_already_on
echo.
echo [release] pre-push hook is already ON - nothing to do.
goto hook_report

:hook_already_off
echo.
echo [release] pre-push hook is already OFF - nothing to do.
goto hook_report

:hook_usage
echo.
echo   .ci\release.bat hook             show the current state
echo   .ci\release.bat hook on          install it  -^> every push runs the pipeline
echo   .ci\release.bat hook off         remove it   -^> releases are manual only
echo.
set "RC=0"
goto done

:hookstate
REM Ask the pipeline, so "is this hook ours?" lives in exactly one place.
REM The answer travels through a temp file on purpose: capturing it with for /f
REM would put a quoted interpreter at the start of the inner command line, and cmd
REM then strips the first and last quote of that line - the capture silently comes
REM back empty. A temp file also survives an interpreter path with spaces in it.
set "HOOKSTATE=UNKNOWN"
set "HSFILE=%TEMP%\prp_hook_state.txt"
if not defined TEMP set "HSFILE=%CI%\out\hook_state.tmp"
"%PY%" "%ENTRY%" hook-status --repo "%REPO%" > "%HSFILE%" 2>nul
if not exist "%HSFILE%" goto :eof
set /p HOOKSTATE=<"%HSFILE%"
del "%HSFILE%" 2>nul 2>&1
if not defined HOOKSTATE set "HOOKSTATE=UNKNOWN"
goto :eof

REM ===========================================================================
REM Command-line actions (scriptable; identical to the menu choices)
REM ===========================================================================
:do_check
echo.
set "LEGEND=1"
call :run check
goto done

:do_dryrun
echo.
echo [release] DRY RUN - builds and cross-checks the version, then stops.
echo [release] A dry run never exercises the upload or the read-back, so passing
echo [release] one is not evidence that a real release will succeed.
echo.
set "LEGEND=1"
call :run release --dry-run
goto done

:do_verify
echo.
set "LEGEND=1"
call :run verify
goto done

:do_release
echo.
echo [release] REAL RELEASE
echo [release]   - tags the current commit
echo [release]   - pushes the tag and creates the release
if defined ASSUME_YES goto release_now
echo.
set "ANSWER="
set /p "ANSWER=[release] type YES to publish, anything else aborts: "
if /I not "%ANSWER%"=="YES" goto aborted
:release_now
echo.
set "LEGEND=1"
call :run release
goto done

:aborted
echo.
echo [release] aborted by the operator - nothing was published.
set "RC=0"
goto done

REM ===========================================================================
:run
"%PY%" "%ENTRY%" %* --repo "%REPO%"
set "RC=%ERRORLEVEL%"
echo.
echo [release] exit code %RC%
if not defined LEGEND goto :eof
if "%RC%"=="0" echo [release] OK
if "%RC%"=="1" echo [release] FAILED - see the message above
if "%RC%"=="2" echo [release] REFUSED - nothing was published (the message names the repair)
goto :eof

:trypy
if defined PY goto :eof
if "%~1"=="" goto :eof
"%~1" -c "import sys" >nul 2>&1
if errorlevel 1 goto :eof
set "PY=%~1"
goto :eof

REM ===========================================================================
:usage
echo.
echo   .ci\release.bat                  INTERACTIVE MENU (double-click)
echo   .ci\release.bat check            read-only readiness report (publishes nothing)
echo   .ci\release.bat dry-run          pipeline up to, but not including, publish
echo   .ci\release.bat release [-y]     real release; -y skips the confirmation prompt
echo   .ci\release.bat verify --tag T   re-check an already published release
echo   .ci\release.bat hook [on^|off]    show / install / remove the push hook
echo   .ci\release.bat help             this text
echo.
echo   With no arguments the menu offers all of the above, including turning
echo   the push hook on or off. The pre-push hook is OFF by default.
set "RC=0"
goto done

:badmode
echo.
echo [release] unknown mode: %~1
goto usage

:noentry
echo.
echo [release] pipeline entry not found: %ENTRY%
echo [release] is this a complete clone? .ci/lib/ must be present.
set "RC=2"
goto done

:nopython
echo.
echo [release] no working python interpreter found on PATH.
echo [release] install Python, or point PRP_PYTHON at its full path, then retry.
set "RC=2"
goto done

:done
if "%RETURN%"=="menu" goto menu_pause
if not defined BCMU_NOPAUSE pause
endlocal & exit /b %RC%
