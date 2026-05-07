!macro customInstall
  ; Detect previous installation marker
  IfFileExists "$LOCALAPPDATA\VurucuTim\.initialized" 0 +2
    DetailPrint "Mevcut kullanici verisi tespit edildi: %LOCALAPPDATA%\VurucuTim -- korunacak."
!macroend

!macro customUnInstall
  ; Ask user whether to remove user data
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "Kullanici verilerini de sil?$\n$\nBu islem geri alinamaz. Uretilen videolar, ayarlar, DB hepsi silinir." \
    /SD IDNO IDNO skip_userdata
    RMDir /r "$LOCALAPPDATA\VurucuTim"
  skip_userdata:
!macroend
