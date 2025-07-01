use crate::services::ctftime_service::get_ctftime_events;
use serenity::builder::{
    CreateCommand, CreateEmbed, CreateEmbedFooter, CreateInteractionResponse,
    CreateInteractionResponseMessage, EditInteractionResponse,
};
use serenity::model::application::CommandInteraction;
use serenity::prelude::*;

pub async fn ctf_command(command: &CommandInteraction, ctx: &Context) {
    let data = CreateInteractionResponseMessage::new().content("🔄 CTF情報を取得中...");
    let builder = CreateInteractionResponse::Message(data);
    if let Err(why) = command.create_response(&ctx.http, builder).await {
        println!("Cannot respond to slash command: {why}");
        return;
    }

    let events = get_ctftime_events().await.unwrap();

    let mut embed = CreateEmbed::new()
        .title("📅 今後2週間のCTF予定")
        .description(format!("CTFtimeから取得した{}件のCTF情報", events.len()))
        .color(0x00FF00)
        .footer(CreateEmbedFooter::new("CTFtime API経由で取得"));

    if events.is_empty() {
        embed = embed.description("現在予定されているCTFはありません。");
    } else {
        for event in events.iter().take(25) {
            let start_time = &event.start;
            let end_time = &event.finish;

            let field_value = format!(
                "🕐 **開始**: {}\n🏁 **終了**: {}\n🔗 [CTFtime]({})",
                start_time, end_time, event.ctftime_url
            );

            embed = embed.field(&event.title, field_value, false);
        }
    }

    let _builder = CreateInteractionResponseMessage::new().embed(embed.clone());
    let builder = EditInteractionResponse::new().add_embed(embed);

    if let Err(why) = command.edit_response(&ctx.http, builder).await {
        println!("Error sending message: {:?}", why);
    }
}

pub fn register_ctftime_commands(commands: &mut Vec<CreateCommand>) {
    commands.push(CreateCommand::new("ctf").description("Show upcoming CTFs"));
}
