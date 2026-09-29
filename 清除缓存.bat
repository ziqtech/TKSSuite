@echo off
title TKSSuite 缓存清理
setlocal enableextensions

rem ==================================================
rem  TKSSuite 缓存清理脚本
rem  1. 清除缓存: __pycache__ / .pyc / 运行时解压缓存 / 音效试听临时文件
rem  2. 清除注册表缓存: HKCU\Software\TKSSuite (QSettings)
rem     注意: 注册表项包含主题/窗口布局/最近目录等编辑器设置,
rem           清除后恢复默认, 下次启动自动重建
rem ==================================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

echo ==============================================
echo             TKSSuite 缓存清理工具
echo ==============================================
echo   建议先关闭所有 TKSSuite 编辑器窗口再清理
echo ==============================================
echo.

rem ---------- 1. 清除缓存 ----------

echo [1/4] 清除 Python 字节码缓存 (__pycache__) ...
for /d /r "%ROOT%" %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d" >nul 2>&1
)

echo [2/4] 清除 .pyc 编译文件 ...
del /s /q /f "%ROOT%\*.pyc" >nul 2>&1

set "RT_CACHE=%LOCALAPPDATA%\TKSEditors\runtime"
echo [3/4] 清除运行时解压缓存 ...
if exist "%RT_CACHE%" (
    rd /s /q "%RT_CACHE%" >nul 2>&1
    echo        已删除 %RT_CACHE%
) else (
    echo        未找到, 跳过
)

echo [4/4] 清除音效试听临时文件 ...
del /q /f "%TEMP%\tkact_sws_*.wav" >nul 2>&1

rem ---------- 2. 清除注册表缓存 ----------

echo.
echo --------------------------------------------------
echo  注册表缓存: HKCU\Software\TKSSuite
echo  (主题/窗口布局/最近目录/列宽等编辑器设置,
echo   清除后恢复默认, 下次启动自动重建)
echo --------------------------------------------------
set "CONFIRM="
set /p CONFIRM=确认清除注册表缓存? (Y/N):
if /i not "%CONFIRM%"=="Y" (
    echo 已跳过注册表清理。
    goto :done
)
reg delete "HKCU\Software\TKSSuite" /f >nul 2>&1
if %errorlevel%==0 (
    echo 已删除注册表项 HKCU\Software\TKSSuite
) else (
    echo 注册表项不存在或已清除。
)

:done
echo.
echo 清理完成!
pause
