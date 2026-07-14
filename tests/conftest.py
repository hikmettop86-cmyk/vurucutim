"""Testler arası küresel durum yalıtımı."""
import pytest


@pytest.fixture(autouse=True)
def _dil_paketi_yalitimi():
    """Her testten sonra dil paketi küresel durumunu sıfırla.

    `lang_pack._user_dir` bir modül-globali ve `load_pack` lru_cache'li. `create_app`
    onu kullanıcının config dizinine kuruyor; web testleri de create_app çağırıyor.
    Sıfırlanmazsa bir testin tmp_path'i bir sonrakine sızar ve sonuçlar test SIRASINA
    bağlı olur — özellikle "paket YOKSA RuntimeError" testleri sahte başarı verir.
    """
    yield
    from short_bot.lang_pack import set_user_dir
    set_user_dir(None)
