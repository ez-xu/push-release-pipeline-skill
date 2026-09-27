@echo off
chcp 936 >nul
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
echo %NAME%  发布控制台
echo ============================================================
if /I "%HOOKSTATE%"=="INSTALLED" echo  推送钩子 : 已安装    git push 也会触发发布
if /I "%HOOKSTATE%"=="MISSING"   echo  推送钩子 : 未安装    仅手动发布（默认）
if /I "%HOOKSTATE%"=="FOREIGN"   echo  推送钩子 : 被占用    别的工具装的，保持原样
if /I "%HOOKSTATE%"=="UNKNOWN"   echo  推送钩子 : 未知      查询失败
echo.
echo   1) 预检 + 发布       先只读预检，确认后真实发布
echo   2) 仅预检            只读，不发布任何东西
echo   3) 干跑              构建 + 版本交叉校验，到发布前一步为止
echo   4) 打开推送钩子      每次 git push 到发布分支都会触发一次发布
echo   5) 关闭推送钩子      回到仅手动发布
echo   6) 复验某次发布      重新校验已发布的 Release
echo   Q) 退出
echo.
set "CHOICE="
set /p "CHOICE=请选择 [1]: "
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
echo [release] 无效选择: %CHOICE%
goto menu_pause

:menu_noinput
REM Empty input is not a choice: it must not fire the default action, and an
REM exhausted stdin must not spin the menu forever.
set /a EMPTY+=1
if %EMPTY% GEQ 3 goto menu_quit
echo.
echo [release] 没有输入选择 —— 请输入编号，或按 Q 退出。
goto menu_pause

:menu_check_release
echo.
echo [release] 就绪预检（只读，不发布任何东西）
set "LEGEND=1"
call :run check
echo.
echo [release] 真实发布
echo [release]   会打标签、推标签并创建 Release。
echo [release]   工作树不干净时流水线会拒绝 —— 请先提交。
echo.
set "ANSWER="
set /p "ANSWER=[release] 输入 YES 发布，其他任意输入返回菜单: "
if /I not "%ANSWER%"=="YES" goto menu_aborted
echo.
call :run release
goto done

:menu_aborted
echo.
echo [release] 已中止 —— 没有发布任何东西。
set "RC=0"
goto done

:menu_check
echo.
set "LEGEND=1"
call :run check
goto done

:menu_dryrun
echo.
echo [release] 干跑 —— 构建并做版本交叉校验，然后停下。
echo [release] 干跑不会走上上传、资产链接和读回，所以干跑通过
echo [release] 并不证明真实发布会成功。
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
echo [release] 推送触发发布已打开。
echo [release] 除非 config 的 hook.mode 设为 gate，否则失败不会阻断推送。
goto done

:menu_hook_off
echo.
call :hookstate
if /I "%HOOKSTATE%"=="FOREIGN" goto hook_foreign
if /I "%HOOKSTATE%"=="MISSING" goto hook_already_off
call :run uninstall-hook
if not "%RC%"=="0" goto done
echo [release] 推送触发发布已关闭（默认）。
goto done

:menu_verify
echo.
echo [release] 输入要复验的标签；留空表示当前版本。
set "VTAG="
set /p "VTAG=标签: "
set "LEGEND=1"
if not defined VTAG goto menu_verify_now
call :run verify --tag "%VTAG%"
goto done
:menu_verify_now
call :run verify
goto done

:menu_quit
echo.
echo [release] 再见。
set "RC=0"
set "RETURN="
goto done

:menu_pause
echo.
echo [release] —— 按任意键返回菜单 ——
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
echo [release] 未知的钩子动作: %HOOKCMD%
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
echo [release] 推送触发发布已打开。
echo [release] 除非 config 的 hook.mode 设为 gate，否则失败不会阻断推送。
goto done

:do_hook_off
call :hookstate
if /I "%HOOKSTATE%"=="FOREIGN" goto hook_foreign
if /I "%HOOKSTATE%"=="MISSING" goto hook_already_off
echo.
call :run uninstall-hook
if not "%RC%"=="0" goto done
echo [release] 推送触发发布已关闭（默认）。
echo [release] 手动发布: .ci\release.bat release
goto done

:hook_report
if /I "%HOOKSTATE%"=="INSTALLED" echo  推送钩子 : 已安装    git push 也会触发发布
if /I "%HOOKSTATE%"=="MISSING"   echo  推送钩子 : 未安装    仅手动发布（默认）
if /I "%HOOKSTATE%"=="FOREIGN"   echo  推送钩子 : 被占用    别的工具装的，保持原样
if /I "%HOOKSTATE%"=="UNKNOWN"   echo  推送钩子 : 未知      查询失败
if /I "%HOOKSTATE%"=="INSTALLED" echo [release] 关闭: .ci\release.bat hook off
if /I "%HOOKSTATE%"=="MISSING"   echo [release] 打开: .ci\release.bat hook on
set "RC=0"
goto done

:hook_foreign
echo.
echo [release] .git/hooks/pre-push 已存在，但不是本流水线的钩子。
echo [release] 拒绝替换或删除不是本工具安装的钩子。
echo [release] 请手工合并，或先把别人的钩子挪开。
set "RC=2"
goto done

:hook_already_on
echo.
echo [release] 推送钩子已经是打开的 —— 无需操作。
goto hook_report

:hook_already_off
echo.
echo [release] 推送钩子已经是关闭的 —— 无需操作。
goto hook_report

:hook_usage
echo.
echo   .ci\release.bat hook             查看当前状态
echo   .ci\release.bat hook on          安装 -^> 每次推送都跑流水线
echo   .ci\release.bat hook off         卸载 -^> 回到仅手动发布
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
echo [release] 干跑 —— 构建并做版本交叉校验，然后停下。
echo [release] 干跑不会走上上传、资产链接和读回，所以干跑通过
echo [release] 并不证明真实发布会成功。
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
echo [release] 真实发布
echo [release]   - 给当前提交打标签
echo [release]   - 推送标签并创建 Release
if defined ASSUME_YES goto release_now
echo.
set "ANSWER="
set /p "ANSWER=[release] 输入 YES 发布，其他任意输入中止: "
if /I not "%ANSWER%"=="YES" goto aborted
:release_now
echo.
set "LEGEND=1"
call :run release
goto done

:aborted
echo.
echo [release] 操作者已中止 —— 没有发布任何东西。
set "RC=0"
goto done

REM ===========================================================================
:run
"%PY%" "%ENTRY%" %* --repo "%REPO%"
set "RC=%ERRORLEVEL%"
echo.
echo [release] 退出码 %RC%
if not defined LEGEND goto :eof
if "%RC%"=="0" echo [release] 成功
if "%RC%"=="1" echo [release] 失败 —— 见上方信息
if "%RC%"=="2" echo [release] 被拒绝 —— 没有发布任何东西（信息里写明了要修什么）
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
echo   .ci\release.bat                  交互菜单（双击）
echo   .ci\release.bat check            只读预检（不发布任何东西）
echo   .ci\release.bat dry-run          跑到发布前一步为止
echo   .ci\release.bat release [-y]     真实发布；-y 跳过确认
echo   .ci\release.bat verify --tag T   复验已发布的 Release
echo   .ci\release.bat hook [on^|off]    查看 / 打开 / 关闭推送钩子
echo   .ci\release.bat help             显示本说明
echo.
echo   不带参数就是菜单，上面每一项都能在菜单里选，包括开关推送钩子。
echo   推送钩子默认关闭。
set "RC=0"
goto done

:badmode
echo.
echo [release] 未知模式: %~1
goto usage

:noentry
echo.
echo [release] 找不到流水线入口: %ENTRY%
echo [release] 这个克隆完整吗？.ci/lib/ 必须存在。
set "RC=2"
goto done

:nopython
echo.
echo [release] PATH 里找不到可用的 python 解释器。
echo [release] 请安装 Python，或用 PRP_PYTHON 指向完整路径后重试。
set "RC=2"
goto done

:done
if "%RETURN%"=="menu" goto menu_pause
if not defined BCMU_NOPAUSE pause
endlocal & exit /b %RC%
