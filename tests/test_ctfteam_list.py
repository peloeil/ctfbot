from types import SimpleNamespace
from typing import Any, cast

from tests.ctfteam_support import CTFTeamTestCase


class ListCommandTest(CTFTeamTestCase):
    async def list(self, status: str | None = None, *, in_guild: bool = True) -> Any:
        guild: Any = SimpleNamespace(id=1) if in_guild else None
        interaction = self.make_interaction(guild=guild)
        args = () if status is None else (status,)
        await cast(Any, self.cog.list_campaigns).callback(self.cog, interaction, *args)
        return interaction

    def embed_of(self, interaction: Any) -> Any:
        interaction.response.send_message.assert_awaited_once()
        kwargs = interaction.response.send_message.call_args.kwargs
        self.assertIs(kwargs["ephemeral"], True)
        return kwargs["embed"]

    async def test_no_campaigns_reports_none_found(self) -> None:
        embed = self.embed_of(await self.list())

        self.assertEqual(embed.title, "CTF募集一覧 (募集中)")
        self.assertEqual(embed.description, "該当する募集はありません。")

    async def test_default_lists_only_active_campaigns(self) -> None:
        self.create_active("Running", message_id=3)
        self.create_closed("Finished", message_id=4)

        description = self.embed_of(await self.list()).description

        self.assertIn("**1. Running**", description)
        self.assertNotIn("Finished", description)

    async def test_closed_status_lists_only_closed_campaigns_with_archive_schedule(
        self,
    ) -> None:
        self.create_active("Running", message_id=3)
        self.create_closed("Finished", archive_at_unix=300, message_id=4)

        embed = self.embed_of(await self.list("closed"))

        self.assertEqual(embed.title, "CTF募集一覧 (終了)")
        self.assertIn("**1. Finished**", embed.description)
        self.assertIn("archive予定: <t:300:f>", embed.description)
        self.assertNotIn("Running", embed.description)

    async def test_all_status_lists_active_and_closed_campaigns(self) -> None:
        self.create_active("Running", message_id=3)
        self.create_closed("Finished", message_id=4)

        embed = self.embed_of(await self.list("all"))

        self.assertEqual(embed.title, "CTF募集一覧 (すべて)")
        self.assertIn("Running", embed.description)
        self.assertIn("Finished", embed.description)

    async def test_permanent_campaign_without_channels_shows_placeholders(
        self,
    ) -> None:
        self.db.create_campaign(
            channel_id=2,
            message_id=3,
            role_id=4,
            discussion_channel_id=None,
            voice_channel_id=None,
            ctf_name="Example",
            start_at_unix=100,
            end_at_unix=None,
            created_by=7,
            created_at_unix=90,
            max_active_per_creator=5,
        )

        description = self.embed_of(await self.list()).description

        self.assertIn("終了: 常設", description)
        self.assertIn("議論: -", description)
        self.assertIn("VC: -", description)

    async def test_campaign_block_links_to_message_and_mentions_resources(
        self,
    ) -> None:
        self.create_active()

        description = self.embed_of(await self.list()).description

        self.assertIn("https://discord.com/channels/1/9/3", description)
        self.assertIn("議論: <#5>", description)
        self.assertIn("VC: <#6>", description)
        self.assertIn("ロール: <@&4>", description)
        self.assertIn("作成者: <@7>", description)

    async def test_overlong_list_is_cut_to_fit_with_omission_count(self) -> None:
        for index in range(20):
            self.create_active(
                f"{index:02d}" + "x" * 998, created_by=index, message_id=index + 1
            )

        description = self.embed_of(await self.list()).description

        self.assertLessEqual(len(description), 4096)
        self.assertTrue(description.startswith("20件を表示しています。"))
        self.assertTrue(description.endswith("他 17 件は省略しています。"))
        self.assertIn("**3. ", description)
        self.assertNotIn("**4. ", description)

    async def test_command_outside_guild_asks_to_run_in_guild(self) -> None:
        interaction = await self.list(in_guild=False)

        self.assert_replied_ephemerally(interaction, "サーバー内で実行してください。")
