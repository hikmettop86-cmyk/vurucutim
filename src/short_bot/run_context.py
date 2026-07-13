"""Aktif koşunun log bağlamı — İŞ PARÇACIKLARI ARASINDA taşınabilir.

Eşzamanlı koşular (farklı kanallar paralel tetiklenince) birbirinin loglarını
kirletmesin diye run log handler'ına İŞ PARÇACIĞINA ÖZEL bir filtre konmuştu.
Doğru bir çözümdü — ama vision çağrılarını ThreadPoolExecutor'a taşıyınca worker
thread'lerde o bağlam OLMADIĞI için kapı logları run dosyasına HİÇ DÜŞMEDİ.

Sonuç bir ölçüm yanılsamasıydı: "12 klip için 1 vision yargısı" diye okunuyordu.
Yargılar yapılıyordu (bütçe doluyordu), yalnızca GÖRÜNMÜYORLARDI — ve teşhis
yanlış yere bakıyordu.

Bu modül bağlamı taşınabilir kılar: havuz başlatılırken ebeveynin yolu worker'a
kopyalanır.
"""
from __future__ import annotations

import threading

_active = threading.local()


def set_log_path(log_path: str | None) -> None:
    if log_path is None:
        clear_log_path()
        return
    _active.log_path = log_path


def get_log_path() -> str | None:
    return getattr(_active, "log_path", None)


def clear_log_path() -> None:
    if hasattr(_active, "log_path"):
        del _active.log_path


def pool_initializer(log_path: str | None) -> None:
    """ThreadPoolExecutor(initializer=...) için: worker ebeveynin koşusunu devralır."""
    set_log_path(log_path)
