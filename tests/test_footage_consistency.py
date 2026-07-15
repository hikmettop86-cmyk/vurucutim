"""Render-öncesi footage tür-tutarlılık doğrulaması (find_footage_outliers)."""
from short_bot.footage_matcher import find_footage_outliers


def test_yaniltici_farkli_tur_yakalanir():
    # Konu great hornbill; 2 klip doğru, 1 klip turaco (farklı kuş) → sapan [2].
    desc = ["a great hornbill perched on a branch",
            "a hornbill at a tree nest hole",
            "a blue turaco bird with red eye"]
    def fake(prompt, schema):
        assert "great hornbill" in prompt   # konu prompt'a geçmeli
        assert "turaco" in prompt            # tarifler prompt'a geçmeli
        return schema(outlier_indices=[2])
    assert find_footage_outliers(desc, "great hornbill", invoke=fake) == [2]


def test_tutarli_klipler_sapan_yok():
    desc = ["a cheetah running", "a cheetah in tall grass"]
    assert find_footage_outliers(desc, "cheetah", invoke=lambda p, s: s(outlier_indices=[])) == []


def test_ortam_klibi_sapan_sayilmaz():
    # LLM ortam klibini (savana manzarası) sapan saymamalı — fonksiyon LLM'e güvenir.
    desc = ["a lion roaring", "an african savanna landscape at sunset"]
    assert find_footage_outliers(desc, "lion", invoke=lambda p, s: s(outlier_indices=[])) == []


def test_tek_klip_dogrulama_atlanir():
    assert find_footage_outliers(["a single clip"], "topic", invoke=lambda p, s: 1 / 0) == []


def test_bos_tarifler_atlanir():
    assert find_footage_outliers(["", "  "], "topic", invoke=lambda p, s: 1 / 0) == []


def test_gecersiz_index_elenir():
    # LLM sınır dışı index dönerse elenir (sağlamlık).
    desc = ["a", "b", "c"]
    assert find_footage_outliers(desc, "t", invoke=lambda p, s: s(outlier_indices=[1, 9, -1])) == [1]


def test_llm_cokerse_fail_open():
    # Doğrulama çökerse [] (render durmasın).
    def boom(prompt, schema):
        raise RuntimeError("vision down")
    assert find_footage_outliers(["a", "b"], "t", invoke=boom) == []
