use serenity::builder::CreateCommand;

use serenity::prelude::*;

pub mod general;
pub mod alpacahack;
pub mod ctftime;

use serenity::model::application::CommandInteraction;
pub async fn handle_command(command: &CommandInteraction, ctx: &Context) {
    match command.data.name.as_str() {
        "echo" => {
            general::echo_command(command, ctx).await;
        }
        "pin" | "unpin" => {
            general::pin_unpin_command(command, ctx).await;
        }
        "add_alpaca" => {
            alpacahack::add_alpaca_command(command, ctx).await;
        }
        "del_alpaca" => {
            alpacahack::del_alpaca_command(command, ctx).await;
        }
        "show_alpaca" => {
            alpacahack::show_alpaca_command(command, ctx).await;
        }
        "show_alpaca_score" => {
            alpacahack::show_alpaca_score_command(command, ctx).await;
        }
        "ctf" => {
            ctftime::ctf_command(command, ctx).await;
        }
        _ => {
            let data = serenity::builder::CreateInteractionResponseMessage::new()
                .content("not implemented");
            let builder = serenity::builder::CreateInteractionResponse::Message(data);
            if let Err(why) = command.create_response(&ctx.http, builder).await {
                println!("Cannot respond to slash command: {why}");
            }
        }
    };
}

pub fn register_all_commands() -> Vec<CreateCommand> {
    let mut commands = Vec::new();
    general::register_general_commands(&mut commands);
    alpacahack::register_alpacahack_commands(&mut commands);
    ctftime::register_ctftime_commands(&mut commands);
    commands
}
