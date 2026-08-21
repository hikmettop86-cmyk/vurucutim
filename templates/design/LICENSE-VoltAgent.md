# Tasarım dilleri — kaynak ve lisans

Bu klasördeki `*.md` dosyaları **VoltAgent/awesome-design-md** deposundan
alınmıştır ve **MIT** lisanslıdır.

    https://github.com/VoltAgent/awesome-design-md
    Alındığı tarih: 2026-08-21 (depo son güncelleme: 2026-07-31)

Dosyalar OLDUĞU GİBİ duruyor; hiçbiri elle düzenlenmedi. Bize uymayan bölümler
(buton/input/form stilleri, responsive breakpoint'ler — dosyaların ~%26'sı)
`short_bot/design_directions.py` tarafından prompt'a KONMADAN AYIKLANIYOR:
bizim tuvalimiz sabit 1080×1920 dikey kart, web sayfası değil.

Tipografi ölçüleri de web boyutunda yazılmış (ör. Wired hero manşeti 64px);
bizim manşetimiz 96-132px. Ayıklayıcı merdivenin ORANLARINI koruyup tuvalimize
oturtacak çapaları prompt'a ekliyor.

Yeni bir dil eklemek: depodan `design-md/<ad>/DESIGN.md` dosyasını buraya
`<ad>.md` olarak kopyala — kod otomatik görür.
