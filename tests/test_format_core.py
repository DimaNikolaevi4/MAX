# -*- coding: utf-8 -*-
"""FORMAT CORE v1: unit-tests for the single rule engine (AGENTS.md section 0).

Run:
    py -m unittest discover -s tests -p "test_*.py" -v

Console output is ASCII-only (cp1251-safe); human-readable reports are UTF-8 files.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared import format_core as fc  # noqa: E402
from shared import paths  # noqa: E402


def fm(status="approved", core=True, **extra):
    values = {"status": status}
    if core:
        values["format_core"] = 1
    values.update(extra)
    return values


def codes(result):
    return [issue.code for issue in result.errors]


def check(text, channel, front=None, **opts):
    params = dict(check_spellcheck=False, check_media=False, extras=False)
    params.update(opts)
    return fc.check_post(text=text, channel=channel, fm=front or {}, **params)


def with_headline(text, headline):
    lines = text.splitlines()
    lines[0] = "**" + headline + "**"
    return "\n".join(lines)


AINOW = (
    "**Neyroseti dlya raboty**\n"
    "\n"
    "Sobral podborku instrumentov. Razbor shagov — v "
    "[starom poste](https://max.ru/channel_ainow/123).\n"
    "\n"
    "> **Подписывайтесь на [AI](https://max.ru/channel_ainow)** — neyroseti i instrumenty\n"
    "\n"
    "Kakoy instrument poprobuyete pervym?\n"
)

CATDEN = (
    "**Porody koshhek**\n"
    "\n"
    "Obzor porod s foto v "
    "[proshlom poste](https://max.ru/channel_catden/77).\n"
    "\n"
    "> **Подписывайтесь на [Коты, кошки и котята](https://max.ru/channel_catden)** — koty i kotyata\n"
    "\n"
    "Kakaya poroda vam nravitsya?\n"
)

NA100 = (
    "**Podborka neyrosetey**\n"
    "\n"
    "Razbor instrumentov za sutki.\n"
    "\n"
    "> **Подписывайтесь на [{label}]({url})** — neyroseti i instrumenty\n"
    "\n"
    "Kakoy servis poprobuyete pervym?\n"
)

ZABAVA = (
    "Kot upal v vedro\n"
    "\n"
    "Esli rassmeyalis — postavte \U0001F525\n"
    "\n"
    "Подпишись на канал **[Забавное](https://max.ru/channel_zabava)** — "
    "horoshee nastroenie kazhdyy den \U0001F3AC\n"
)

LEGACY_NO_QUESTION = (
    "**Staraya podborka**\n"
    "\n"
    "Tekst bez zaklyuchitelnogo voprosa.\n"
    "\n"
    "> **Подписывайтесь на [AI](https://max.ru/channel_ainow)** — neyroseti\n"
)

ZABAVA_CTA_ONLY = (
    "Подпишись на **[Забавное](https://max.ru/channel_zabava)** — esli lyubite, kogda smeshno \U0001F3AC\n"
)

DIGEST_BODY = (
    "**Пять новостей за сутки: железо, ИИ и цифры рынка**\n"
    "\n"
    "1️⃣ **KDE представила терминал Kwi 0.1 с ускорением**\n"
    "Что случилось: релиз появился в ленте разработчиков.\n"
    "\n"
    "Почему важно: ускорение снимает нагрузку с процессора и ускоряет работу с логами.\n"
    "\n"
    "2️⃣ **Nvidia и Китай: спор о поставках чипов**\n"
    "Что случилось: власти запросили подробности о продажах процессоров.\n"
    "\n"
    "Почему важно: детали могут изменить условия доступа к железу.\n"
    "\n"
    "3️⃣ **Anthropic получила вложения до IPO**\n"
    "Что случилось: несколько фондов вошли в капитал компании.\n"
    "\n"
    "Почему важно: это сигнал о вере в выручку модельного бизнеса.\n"
    "\n"
    "4️⃣ **Цена наушников упала до 165 фунтов**\n"
    "Что случилось: ритейлер снизил цену до минимума.\n"
    "\n"
    "Почему важно: распродажи меняют ориентиры для покупателей.\n"
    "\n"
    "5️⃣ **Подписки от 99 центов на неделю**\n"
    "Что случилось: сервисы запустили акции на первый месяц.\n"
    "\n"
    "Почему важно: легко забыть об автопродлении и заплатить позже.\n"
    "\n"
    "Итог дня: железо и ИИ задают повестку, поэтому даже распродажи "
    "выглядят продолжением гонки за внимание.\n"
    "\n"
    "> **Подписывайтесь на [AI](https://max.ru/channel_ainow)** — нейросети и инструменты\n"
    "\n"
    "Какую новость разобрать подробнее?\n"
)

TELEGRAM_EMOJI = (
    "\U0001F3AC **Kanal multfilmov**\n"
    "\n"
    "Novyy vypusk v "
    "[poste](https://max.ru/channel_ainow/123).\n"
    "\n"
    "**Подписывайтесь на [AI v MAX](https://max.ru/channel_ainow)** — multstudiya\n"
)


class FormatCorePositiveTest(unittest.TestCase):
    def test_01_core_canonical_quote_pass(self):
        result = check(AINOW, "ainow", fm())
        self.assertTrue(result.ok, str(result.to_dict()))
        self.assertEqual(result.mode, "CORE")
        self.assertEqual(result.profile, "core")

    def test_15_front_matter_round_trip_keeps_unknown_fields(self):
        raw = (
            "---\nstatus: approved\nformat_core: 1\ncta_target: ainow\n"
            "approved_by_owner: true\nspell_ignore: test,word\n"
            "media_note: owner\n# comment\n---\n\nBody line.\n"
        )
        front, body = fc.split_post(raw)
        front.set("status", "published")
        rendered = fc.join_post(front, body)
        for needle in ("format_core: 1", "cta_target: ainow",
                       "approved_by_owner: true", "spell_ignore:",
                       "media_note: owner", "# comment", "status: published"):
            self.assertIn(needle, rendered, "lost field: " + needle)
        self.assertIn("Body line.", rendered)

    def test_18_text_only_catden_pass(self):
        result = check(CATDEN, "catden", fm(), for_publish=True,
                       check_media=True, resolve_media_path_fn=lambda name: None)
        self.assertTrue(result.ok, str(result.to_dict()))

    def test_19_legacy_without_question_pass(self):
        result = check(LEGACY_NO_QUESTION, "ainow",
                       fm(status="draft", core=False))
        self.assertEqual(result.mode, "LEGACY")
        self.assertTrue(result.ok, str(result.to_dict()))

    def test_22_zabava_reaction_block_pass(self):
        registry = {"min_gap": 2, "channels": {}}
        with mock.patch.object(fc, "load_reactions_registry", return_value=registry):
            result = check(ZABAVA, "zabava", fm(), extras=False)
        self.assertTrue(result.ok, str(result.to_dict()))

    def test_26_publish_window_is_catchup_window(self):
        self.assertEqual(fc.parse_publish_window([7, 10]), (7, 10))
        self.assertEqual(fc.parse_publish_window("12:00,21:30"), (12, 21))
        self.assertIsNone(fc.parse_publish_window(None))
        self.assertIsNone(fc.parse_publish_window("manual"))

    def test_27_deleted_channel_is_blocked(self):
        with self.assertRaises(SystemExit):
            paths.ensure_publish_allowed("ozon_group", "test")

    def test_28_legacy_zabava_empty_body_warn_only(self):
        result = check(ZABAVA_CTA_ONLY, "zabava", fm(core=False))
        self.assertEqual(result.mode, "LEGACY")
        self.assertTrue(result.ok, str(result.to_dict()))
        self.assertIn("BODY_EMPTY_LEGACY", [i.code for i in result.warnings])

    def test_29_telegram_headline_with_emoji_pass(self):
        result = check(TELEGRAM_EMOJI, "tg_neuro", fm(), extras=False)
        self.assertTrue(result.ok, str(result.to_dict()))

    def test_31_own_cover_needs_no_attribution(self):
        result = check(DIGEST_BODY, "na100",
                       fm(cta_target="ainow",
                          image_file="local/digest/cover-2026-11-23-test.png"),
                       extras=True)
        self.assertTrue(result.ok, str(result.to_dict()))
        self.assertNotIn("DIGEST_ATTRIBUTION", codes(result))

    def test_32_external_photo_requires_attribution(self):
        front = fm(cta_target="ainow",
                   image_file="local/digest/2026-11-23/foreign-photo.jpg")
        no_credit = check(DIGEST_BODY, "na100", front, extras=True)
        self.assertIn("DIGEST_ATTRIBUTION", codes(no_credit))
        credited = DIGEST_BODY.replace(
            "\n> **Подписывайтесь",
            "\nФото: сторонний источник\n\n> **Подписывайтесь")
        with_credit = check(credited, "na100", front, extras=True)
        self.assertNotIn("DIGEST_ATTRIBUTION", codes(with_credit))

    def test_33_question_without_proverili(self):
        text = DIGEST_BODY.replace(
            "Какую новость разобрать подробнее?",
            "Какую новость вы бы проверили первым делом?")
        result = check(text, "na100",
                       fm(cta_target="ainow",
                          image_file="local/digest/cover-2026-11-25-test.png"),
                       extras=True)
        self.assertTrue(result.ok, str(result.to_dict()))
        self.assertIn("QUESTION_WORDING", [i.code for i in result.warnings])

    def test_30_front_matter_set_no_duplication(self):
        raw = ("---\nchannel: ainow\nstatus: approved\n"
               "cta_target: self\n# comment\n---\n\nBody\n")
        front, _ = fc.split_post(raw)
        front.set("channel", "ainow")
        front.set("status", "published")
        front.set("cta_target", "ainow")
        rendered = front.render()
        self.assertIn("channel: ainow\n", rendered)
        self.assertIn("status: published\n", rendered)
        self.assertIn("cta_target: ainow\n", rendered)
        self.assertNotIn("ainowainow", rendered)
        self.assertNotIn("publishedapproved", rendered)
        self.assertIn("# comment", rendered)


class FormatCoreNegativeTest(unittest.TestCase):
    def test_02_no_final_question_fail(self):
        text = AINOW.rsplit("\n\n", 1)[0] + "\n"
        result = check(text, "ainow", fm())
        self.assertIn("QUESTION", codes(result))

    def test_03_question_not_last_fail(self):
        result = check(AINOW + "\nDopolnitelnyy tekst.\n", "ainow", fm())
        self.assertIn("QUESTION", codes(result))

    def test_04_headline_too_long_fail(self):
        result = check(with_headline(AINOW, "a" * 61), "ainow", fm())
        self.assertIn("HEADLINE_LEN", codes(result))

    def test_05_headline_ends_with_dot_fail(self):
        result = check(with_headline(AINOW, "Zagolovok."), "ainow", fm())
        self.assertIn("HEADLINE_DOT", codes(result))

    def test_06_blank_line_under_subheading_fail(self):
        text = (
            "**Zagolovok**\n\n**Podzagolovok**\n\nTekst.\n\n"
            "> **Подписывайтесь на [AI](https://max.ru/channel_ainow)** — fraza\n\n"
            "Vopros?\n"
        )
        result = check(text, "ainow", fm())
        self.assertIn("AIR_SUBHEAD", codes(result))

    def test_07_inline_bold_budget_fail(self):
        text = AINOW.replace(
            "Sobral podborku instrumentov. Razbor shagov",
            "**a** **b** **c** **d** **e** **f** **g** Razbor shagov")
        result = check(text, "ainow", fm())
        self.assertIn("BOLD_BUDGET", codes(result))

    def test_08_reaction_gap_configurable(self):
        # Политика 23.11.2026: призыв к реакциям обязателен в каждом посте,
        # поэтому по умолчанию (reactions_min_gap: 0) ограничения частоты нет.
        registry = {
            "min_gap": 0,
            "channels": {"ainow": {
                "last_reaction_post": "post-b.md",
                "history": [
                    {"post": "post-a.md", "reactions": True},
                    {"post": "post-b.md", "reactions": True},
                ],
            }},
        }
        allowed, reason = fc.can_use_reaction("ainow", registry=registry)
        self.assertTrue(allowed, reason)

        # Явно заданный gap продолжает работать: 2 поста между реакциями.
        allowed_strict, reason_strict = fc.can_use_reaction(
            "ainow", ch={"reactions_min_gap": 2}, registry=registry)
        self.assertFalse(allowed_strict, reason_strict)

    def test_09_cta_target_self_self_link_pass(self):
        text = NA100.format(label="Новости технологий ИИ, нейросетей и инноваций",
                            url="https://max.ru/channel_na100")
        result = check(text, "na100", fm(cta_target="self"))
        self.assertTrue(result.ok, str(result.to_dict()))

    def test_10_cta_target_ainow_ainow_link_pass(self):
        text = NA100.format(label="AI", url="https://max.ru/channel_ainow")
        result = check(text, "na100", fm(cta_target="ainow"))
        self.assertTrue(result.ok, str(result.to_dict()))

    def test_11_cta_target_mismatch_fail(self):
        text = NA100.format(label="AI", url="https://max.ru/channel_ainow")
        result = check(text, "na100", fm(cta_target="self"))
        self.assertTrue({"CTA_TARGET_URL", "CTA_LABEL"} & set(codes(result)),
                        str(result.to_dict()))

    def test_12_published_post_refused(self):
        result = check(AINOW, "ainow", fm(status="published"), for_publish=True)
        self.assertIn("STATUS", codes(result))

    def test_13_draft_post_refused(self):
        result = check(AINOW, "ainow", fm(status="draft"), for_publish=True)
        self.assertIn("STATUS", codes(result))

    def test_14_hold_post_refused(self):
        result = check(AINOW, "ainow", fm(status="hold"), for_publish=True)
        self.assertIn("STATUS", codes(result))

    def test_16_video_aspect_too_narrow_fail(self):
        with mock.patch.object(fc, "measure_media", return_value=(140, 100, 1.4)):
            result = check(
                AINOW, "ainow", fm(video_file="fake.mp4"),
                check_media=True,
                resolve_media_path_fn=lambda name: Path("fake.mp4"))
        self.assertIn("MEDIA_ASPECT", codes(result))

    def test_17_album_limit_fail(self):
        names = "|".join("img{0}.jpg".format(i) for i in range(13))
        result = check(AINOW, "ainow", fm(image_files=names), check_media=True)
        self.assertIn("ALBUM_LIMIT", codes(result))

    def test_20_core_without_question_fail(self):
        result = check(LEGACY_NO_QUESTION, "ainow", fm())
        self.assertIn("QUESTION", codes(result))

    def test_21_zabava_daily_cap_post_source(self):
        now = datetime(2026, 11, 22, 12, 0, tzinfo=fc.MSK)
        post = (
            "---\nstatus: published\npublished_at: 2026-11-22T19:30:00+03:00\n---\n\nBody\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "post-today.md").write_text(post, encoding="utf-8")
            with mock.patch.object(fc, "post_dir", return_value=target):
                today = fc.published_today("zabava", now=now)
            self.assertEqual(len(today), 1)
            (target / "post-today.md").write_text(
                post.replace("2026-11-22", "2026-11-21"), encoding="utf-8")
            with mock.patch.object(fc, "post_dir", return_value=target):
                other_day = fc.published_today("zabava", now=now)
            self.assertEqual(other_day, [])

    def test_23_telegram_caption_too_long_fail(self):
        text = "**Zagolovok**\n\n" + ("x" * 1100) + "\n"
        result = check(text, "tg_neuro", fm(), extras=False)
        self.assertIn("LENGTH", codes(result))

    def test_24_forbidden_org_fail(self):
        result = check(AINOW + "\nFacebook upomyanut.\n", "ainow", fm())
        self.assertIn("FORBIDDEN_ORG", codes(result))

    def test_25_cta_without_link_fail(self):
        text = AINOW.replace(
            "> **Подписывайтесь на [AI](https://max.ru/channel_ainow)** — neyroseti i instrumenty",
            "> **Подписывайтесь на AI** — neyroseti i instrumenty")
        result = check(text, "ainow", fm())
        self.assertIn("CTA_FORMAT", codes(result))

    def test_33_reaction_line_stuck_to_cta_fail(self):
        text = AINOW.replace(
            "— neyroseti i instrumenty\n\nKakoy",
            "— neyroseti i instrumenty\n🔥 Polezno — postavte reakciyu.\n\nKakoy")
        result = check(text, "ainow", fm())
        self.assertIn("CTA_STICKY", codes(result))

    def test_34_reaction_line_with_air_pass(self):
        text = AINOW.replace(
            "— neyroseti i instrumenty\n\nKakoy",
            "— neyroseti i instrumenty\n\n🔥 Polezno — postavte reakciyu.\n\nKakoy")
        registry = {"min_gap": 2, "channels": {}}
        with mock.patch.object(fc, "load_reactions_registry", return_value=registry):
            result = check(text, "ainow", fm())
        self.assertNotIn("CTA_STICKY", codes(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
