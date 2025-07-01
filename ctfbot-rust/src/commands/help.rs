use serenity::builder::{CreateCommand, CreateInteractionResponseMessage, CreateInteractionResponse};
use serenity::model::application::CommandInteraction;
use serenity::prelude::*;

pub async fn help_command(command: &CommandInteraction, ctx: &Context) {
    let mut help_message = String::from("## 利用可能なコマンド一覧:\n\n");

    // ここで全てのコマンドの情報を集める
    // 実際にはregister_all_commandsから情報を取得するか、
    // コマンド情報を保持する構造体などから取得する必要があります。
    // 今回は手動で記述します。
    help_message.push_str("### General Commands\n");
    help_message.push_str("`/echo <message>`: 指定されたメッセージを返します。\n");
    help_message.push_str("`/pin <message_link>`: 指定されたメッセージをピン留めします。\n");
    help_message.push_str("`/unpin <message_link>`: 指定されたメッセージのピン留めを解除します。\n\n");

    help_message.push_str("### AlpacaHack Commands\n");
    help_message.push_str("`/add_alpaca <name>`: AlpacaHackユーザーを追跡リストに追加します。\n");
    help_message.push_str("`/del_alpaca <name>`: AlpacaHackユーザーを追跡リストから削除します。\n");
    help_message.push_str("`/show_alpaca`: 追跡中の全てのAlpacaHackユーザーを表示します。\n");
    help_message.push_str("`/show_alpaca_score`: 追跡中のAlpacaHackユーザーのスコアを表示します。\n\n");

    help_message.push_str("### CTFtime Commands\n");
    help_message.push_str("`/ctf`: 今後2週間のCTFtimeイベントを表示します。\n\n");

    help_message.push_str("### Other Commands\n");
    help_message.push_str("`/help`: このヘルプメッセージを表示します。\n");


    let data = CreateInteractionResponseMessage::new().content(help_message);
    let builder = CreateInteractionResponse::Message(data);
    if let Err(why) = command.create_response(&ctx.http, builder).await {
        println!("Cannot respond to slash command: {why}");
    }
}

pub fn register_help_command(commands: &mut Vec<CreateCommand>) {
    commands.push(
        CreateCommand::new("help")
            .description("Show all available commands"),
    );
}
