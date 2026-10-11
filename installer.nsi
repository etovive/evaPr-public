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
;    makensis -DSRC_DIR=dist -DAPP_VER=0.700.1.2 installer.nsi
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
  !define APP_VER "0.700.1.2"
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
; Debe coincidir con el AppUserModelID que fija evaPr.py en runtime.
!define APP_AUMI      "eduCAd.evaPr"

!include "MUI2.nsh"
!include "LogicLib.nsh"
; COM.nsh / Propkey.nsh (en Include\Win\, vienen con NSIS 3.x) permiten fijar el
; AppUserModelID en los accesos directos usando el plugin System (incluido en
; NSIS por defecto). Sin ese id Windows no puede anclar correctamente la app a
; la barra de tareas. El id debe coincidir con el que fija evaPr.py en tiempo
; de ejecución (_set_windows_app_user_model_id).
!include "Win\COM.nsh"
!include "Win\Propkey.nsh"

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
; VIProductVersion exige exactamente 4 campos numéricos (X.X.X.X). Por eso
; APP_VERSION en config/settings.py se escribe con 4 números (p. ej. 0.700.1.2).
VIProductVersion "${APP_VER}"
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
  ; AppUserModelID del propio instalador (evita que su botón en la barra de
  ; tareas se agrupe con otro proceso). El del desinstalador se fija en un.onInit.
  System::Call 'Shell32::SetCurrentProcessExplicitAppUserModelID(w "${APP_AUMI}.Setup")'
  Call CloseRunningInstance
FunctionEnd

; ─── AppUserModelID de los accesos directos ──────────────────────────────────
; Asocia el .lnk con el AppUserModelID de la aplicación (System.AppUserModel.ID)
; para que Windows 7+ permita anclar la app y agrupe todas sus ventanas bajo el
; mismo botón. Implementado con el plugin System (incluido en NSIS por defecto),
; sin depender de plugins externos. Se puede usar varias veces (sin labels).
!macro SetLnkAUMI _lnk _aumi
  System::Store S
  IntOp $0 0 - 1
  IntOp $1 0 + 0
  IntOp $2 0 + 0
  IntOp $3 0 + 0
  IntOp $4 0 + 0
  IntOp $5 0 + 0
  IntOp $6 0 + 0

  !insertmacro ComHlpr_CreateInProcInstance ${CLSID_ShellLink} ${IID_IShellLink} r1 ".r0"
  ${If} $0 = 0
    ${IUnknown::QueryInterface} $1 '("${IID_IPersistFile}",.r2)i.r0'
    ${If} $0 = 0
      ${IPersistFile::Load} $2 "('${_lnk}', ${STGM_READWRITE})i.r0"
      ${If} $0 = 0
        ${IUnknown::QueryInterface} $1 '("${IID_IPropertyStore}",.r3)i.r0'
        ${If} $0 = 0
          System::Call '*${SYSSTRUCT_PROPERTYKEY}(${PKEY_AppUserModel_ID})p.r4'
          StrLen $7 "${_aumi}"
          IntOp $7 $7 + 1
          IntOp $7 $7 * 2
          System::Call "ole32::CoTaskMemAlloc(i $7)p.r6"
          ${If} $6 P<> 0
            StrLen $7 "${_aumi}"
            IntOp $7 $7 + 1
            System::Call '*$6(&w$7 "${_aumi}")'
            System::Call '*${SYSSTRUCT_PROPVARIANT}(${VT_LPWSTR},,p r6)p.r5'
            ${IPropertyStore::SetValue} $3 '($4,$5)i.r0'
            ${IPropertyStore::Commit} $3 "i.r0"
            ${If} $0 = 0
              ${IPersistFile::Save} $2 '("${_lnk}",1)i.r0'
            ${EndIf}
            System::Call "ole32::CoTaskMemFree(p r6)"
            System::Free $5
          ${EndIf}
          System::Free $4
          ${IUnknown::Release} $3 ""
        ${EndIf}
        ${IUnknown::Release} $2 ""
      ${EndIf}
    ${EndIf}
    ${IUnknown::Release} $1 ""
  ${EndIf}
  System::Store L
!macroend

; ─── Secciones ───────────────────────────────────────────────────────────────
Section "${APP_NAME_FULL}" SecArchivos
  SectionIn RO
  SetOutPath "$INSTDIR"

  ; ── Limpieza de instalaciones antiguas (install.bat y versiones viejas) ──
  ; Aquellas instalaciones dejaban evaPr.pyw / evaPr.py y sus accesos directos
  ; apuntando a un ".pyw". El instalador actual usa exclusivamente evaPr.exe,
  ; asi que se eliminan esos restos tanto al instalar como al actualizar.
  Delete "$INSTDIR\evaPr.pyw"
  Delete "$INSTDIR\evaPr.py"
  Delete "$INSTDIR\Uninstall.bat"
  Delete "$INSTDIR\launcher\evaPr.cmd"
  RMDir  "$INSTDIR\launcher"

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

  ; ── Restos de instalaciones antiguas con install.bat ──
  ; La version mas antigua de install.bat creaba el acceso directo con destino
  ; "pythonw.exe" y argumento "evaPr.py" (un .py). Se borra siempre para que
  ; nadie conserve ese acceso; las secciones de abajo (Escritorio / Menu de
  ; Inicio) lo vuelven a crear apuntando a $INSTDIR\evaPr.exe.
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
SectionEnd

Section "Acceso directo en el Escritorio" SecEscritorio
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" \
                 "$INSTDIR\${APP_ICON}" "" "" "" "$INSTDIR"
  !insertmacro SetLnkAUMI "$DESKTOP\${APP_NAME}.lnk" "${APP_AUMI}"
SectionEnd

Section "Acceso directo en el Menú de Inicio" SecInicio
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" \
                 "$INSTDIR\${APP_ICON}" "" "" "" "$INSTDIR"
  !insertmacro SetLnkAUMI "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "${APP_AUMI}"
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
  ; Restos de instalaciones antiguas hechas con install.bat
  Delete "$INSTDIR\Uninstall.bat"
  Delete "$INSTDIR\evaPr.pyw"
  RMDir   "$INSTDIR"

  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
  DeleteRegKey HKCU "Software\${APP_NAME}"
SectionEnd
