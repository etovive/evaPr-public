; =============================================================================
;  evaPr (eduCAd) — Instalador para Windows (NSIS 3)
; =============================================================================
;  Genera: evaPr-Setup-<version>.exe
;
;  Requisitos: NSIS 3.x instalado y "makensis" en el PATH.
;  Uso típico:  build_installer.bat   (ejecuta PyInstaller y luego esto)
;  Uso manual:  makensis installer.nsi
;
;  Parámetros de compilación opcionales:
;    makensis -DSRC_DIR=dist -DAPP_VER=0.694 installer.nsi
;
;  IMPORTANTE
;  ----------
;  - "svgs\" y "config\" se instalan TAL CUAL junto al ejecutable, porque la
;    aplicación los lee desde la carpeta del propio .exe (utils.get_app_dir()).
;  - Se excluyen las cachés ".cache" (PNG regenerables que crea el renderizador).
;  - Instalación por usuario en %LOCALAPPDATA%\Programs\evaPr: no pide
;    permisos de administrador y la carpeta queda escribible, algo necesario
;    porque el renderizador de SVG escribe su caché dentro de "svgs\".
;  - Al desinstalar NO se borran los datos del usuario
;    (%APPDATA%\evaPr\config.json ni los proyectos guardados).
; =============================================================================

Unicode true
RequestExecutionLevel user

; ─── Parámetros de compilación ────────────────────────────────────────────────
; APP_VER lo sobrescriben build_installer.bat y build_installer_linux.sh con
; el valor de APP_VERSION en config/settings.py; el de aquí es solo un respaldo.
!ifndef APP_VER
  !define APP_VER "0.694"
!endif

!ifndef SRC_DIR
  !define SRC_DIR "dist"
!endif

!ifndef OUT_FILE
  !define OUT_FILE "evaPr-Setup-${APP_VER}.exe"
!endif

; Tamaño instalado en KB. Lo calculan build_installer.bat / build_installer_linux.sh
; (0 = desconocido, solo afecta a la columna de tamaño en "Agregar o quitar programas")
!ifndef APP_SIZE_KB
  !define APP_SIZE_KB 0
!endif

; ─── Identidad de la aplicación ──────────────────────────────────────────────
!define APP_NAME      "evaPr"
!define APP_NAME_FULL "evaPr (eduCAd)"
!define APP_PUBLISHER "eduCAd"
!define APP_EXE       "evaPr.exe"
!define APP_ICON      "logo-evaPr.ico"
!define APP_LOGO      "logo-evaPr.png"

!include "MUI2.nsh"
!include "LogicLib.nsh"

!define MUI_ICON   "${SRC_DIR}\${APP_ICON}"
!define MUI_UNICON "${SRC_DIR}\${APP_ICON}"

!define MUI_ABORTWARNING
; MUI_FINISHPAGE_RUN habilita la casilla del cuadro final; el valor se ignora
; porque el arranque real lo hace MUI_FINISHPAGE_RUN_FUNCTION.
!define MUI_FINISHPAGE_RUN           "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_FUNCTION "LaunchApp"
!define MUI_FINISHPAGE_RUN_TEXT    "Iniciar ${APP_NAME_FULL} ahora"

Name         "${APP_NAME_FULL}"
OutFile      "${OUT_FILE}"
InstallDir   "$LOCALAPPDATA\Programs\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_NAME}" "InstallDir"
BrandingText "${APP_NAME_FULL} ${APP_VER}"
ShowInstDetails show
ShowUninstDetails show

; ─── Información de versión (propiedades del .exe generado) ──────────────────
VIProductVersion "${APP_VER}.0.0"
VIAddVersionKey "ProductName"     "${APP_NAME_FULL}"
VIAddVersionKey "CompanyName"     "${APP_PUBLISHER}"
VIAddVersionKey "FileDescription" "Diagramador de circuitos eléctricos industriales"
VIAddVersionKey "FileVersion"     "${APP_VER}"
VIAddVersionKey "LegalCopyright"  "${APP_PUBLISHER}"
VIAddVersionKey "ProductVersion"  "${APP_VER}"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Spanish"
!insertmacro MUI_LANGUAGE "English"

; ─── Utilidades ──────────────────────────────────────────────────────────────
; Cierra una instancia en ejecución si la hay. taskkill devuelve 0 si cerró algo
; y 128 si no había ningún proceso, así que el resultado no depende del idioma.
; Se usa ExecWait (instrucción nativa) en lugar de plugins para que el script
; compile igual en Windows y en Linux.
Function CloseRunningInstance
  ExecWait '"$SYSDIR\taskkill.exe" /IM ${APP_EXE} /F' $0
  ${If} $0 == 0
    MessageBox MB_ICONINFORMATION|MB_OK \
      "${APP_NAME_FULL} estaba en ejecución y se cerró para instalar la versión ${APP_VER}."
  ${EndIf}
FunctionEnd

Function .onInit
  SetOverwrite on
  Call CloseRunningInstance
FunctionEnd

; ─── Secciones ───────────────────────────────────────────────────────────────
Section "${APP_NAME_FULL}" SecArchivos
  SectionIn RO
  SetOutPath "$INSTDIR"

  ; ── Ejecutable y recursos ──
  File "${SRC_DIR}\${APP_EXE}"
  File "${SRC_DIR}\${APP_ICON}"
  File "${SRC_DIR}\${APP_LOGO}"

  ; ── DLL opcionales depositadas a mano en la carpeta de compilación ──
  ;    (típicamente libcairo-2.dll, que necesita cairosvg y que PyInstaller
  ;     no empaqueta porque se carga de forma dinámica)
  File /nonfatal "${SRC_DIR}\*.dll"

  ; ── svgs\ : biblioteca de símbolos, tal cual (subcarpetas + archivos) ──
  ;    /x excluye la caché de PNG que el renderizador genera al usar el programa.
  SetOutPath "$INSTDIR\svgs"
  File /r /x ".cache" /x "*.pyc" /x "Thumbs.db" /x "desktop.ini" "${SRC_DIR}\svgs\*.*"

  ; ── config\ : medidas.json se lee en tiempo de ejecución; los .py viajan por
  ;    comodidad (la aplicación usa los que ya vienen dentro del ejecutable). ──
  SetOutPath "$INSTDIR\config"
  File "${SRC_DIR}\config\medidas.json"
  File /nonfatal "${SRC_DIR}\config\__init__.py"
  File /nonfatal "${SRC_DIR}\config\settings.py"

  ; ── Desinstalador ──
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; ── Registro: entrada en "Agregar o quitar programas" ──
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
                      "DisplayName"          "${APP_NAME_FULL} ${APP_VER}"
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
                      "DisplayVersion"       "${APP_VER}"
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
                      "Publisher"            "${APP_PUBLISHER}"
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
                      "DisplayIcon"          "$INSTDIR\${APP_ICON}"
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
                      "InstallLocation"      "$INSTDIR"
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
                      "UninstallString"      '"$INSTDIR\Uninstall.exe"'
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
                      "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
                      "NoModify"             "1"
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
                      "NoRepair"             "1"

  ; Tamaño estimado en KB que muestra Windows
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
                      "EstimatedSize"        ${APP_SIZE_KB}

  WriteRegStr HKCU "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
SectionEnd

Section /o "Acceso directo en el Escritorio" SecEscritorio
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" \
                 "$INSTDIR\${APP_ICON}" "" "" "" "$INSTDIR"
SectionEnd

Section /o "Acceso directo en el Menú de Inicio" SecInicio
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" \
                 "$INSTDIR\${APP_ICON}" "" "" "" "$INSTDIR"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\Desinstalar ${APP_NAME}.lnk" \
                 "$INSTDIR\Uninstall.exe" "" "$INSTDIR\${APP_ICON}"
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecArchivos}  "El ejecutable, la biblioteca de símbolos (svgs) y la configuración (config/medidas.json)."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecEscritorio} "Crea un acceso directo en el Escritorio."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecInicio}     "Crea accesos directos en el Menú de Inicio, incluido el desinstalador."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ─── Ejecución tras instalar ─────────────────────────────────────────────────
Function LaunchApp
  SetOutPath "$INSTDIR"
  ExecShell "" "$INSTDIR\${APP_EXE}"
FunctionEnd

; ─── Desinstalación ──────────────────────────────────────────────────────────
Function un.${APP_NAME}
  DetailPrint "Cerrando ${APP_NAME_FULL} si está en ejecución..."
  ExecWait '"$SYSDIR\taskkill.exe" /IM ${APP_EXE} /F' $0
FunctionEnd

Function un.onInit
  IfFileExists "$INSTDIR\${APP_EXE}" 0 +2
  Call un.${APP_NAME}
FunctionEnd

Section "Uninstall"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Desinstalar ${APP_NAME}.lnk"
  RMDir   "$SMPROGRAMS\${APP_NAME}"
  RMDir   "$SMPROGRAMS"

  RMDir /r "$INSTDIR\svgs"
  RMDir /r "$INSTDIR\config"

  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\${APP_ICON}"
  Delete "$INSTDIR\${APP_LOGO}"
  Delete "$INSTDIR\*.log"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir   "$INSTDIR"

  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
  DeleteRegKey HKCU "Software\${APP_NAME}"
SectionEnd
