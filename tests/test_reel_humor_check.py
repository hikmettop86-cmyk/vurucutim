"""Mizah doğrulama kapısı — reel_factcheck.check_narration'ın kardeşi."""


def test_temiz_senaryo_bos_liste():
    from short_bot.reel_humor_check import check_humor

    def sahte(prompt, schema):
        return schema(issues=[])

    assert check_humor("karga", text="komik metin", language="tr", invoke=sahte) == []


def test_uydurma_referans_yakalanir():
    from short_bot.reel_humor_check import check_humor, HumorIssue

    def sahte(prompt, schema):
        return schema(issues=[HumorIssue(problem="'Gökkuşağı Sokağı' diye dizi yok",
                                         kind="reference")])

    r = check_humor("karga", text="...", language="tr", invoke=sahte)
    assert len(r) == 1 and r[0].kind == "reference"


def test_cokerse_bos_liste_uretim_durmaz():
    from short_bot.reel_humor_check import check_humor

    def patlayan(prompt, schema):
        raise RuntimeError("LLM patladı")

    assert check_humor("karga", text="...", language="tr", invoke=patlayan) == []


def test_bos_metin_bos_liste():
    from short_bot.reel_humor_check import check_humor
    assert check_humor("karga", text="  ", language="tr",
                       invoke=lambda p, s: 1 / 0) == []


def test_humor_feedback_metni():
    from short_bot.reel_humor_check import humor_feedback, HumorIssue
    fb = humor_feedback([HumorIssue(problem="zorlama şaka", kind="humor")])
    assert "zorlama şaka" in fb
