"""Kanal kurma ajanı — mizah niyeti tespiti → vahsi_mizah persona."""


def test_mizah_niyeti_personaya_cevrilir():
    from short_bot.channel_agent import detect_persona
    assert detect_persona("komik bir karga kanalı") == "vahsi_mizah"
    assert detect_persona("mizahi hayvan belgeseli") == "vahsi_mizah"
    assert detect_persona("eğlenceli hayvan videoları") == "vahsi_mizah"


def test_mizah_olmayan_niyet_bos():
    from short_bot.channel_agent import detect_persona
    assert detect_persona("bilim tarihi kanalı") == ""
    assert detect_persona("almanca bahçe kanalı") == ""


def test_channelplan_persona_alani():
    from short_bot.channel_agent import ChannelPlan
    assert "persona" in ChannelPlan.model_fields
