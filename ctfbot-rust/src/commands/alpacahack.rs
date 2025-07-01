use serenity::builder::{CreateCommand, CreateCommandOption, CreateInteractionResponseMessage, CreateInteractionResponse, EditInteractionResponse};
use serenity::model::application::{CommandOptionType, CommandInteraction};
use serenity::prelude::*;
use crate::services::alpacahack_service::{insert_alpacahack_user, delete_alpacahack_user, get_all_alpacahack_users, get_alpacahack_solves_scraped};
use tokio::time::{sleep, Duration};

pub async fn add_alpaca_command(command: &CommandInteraction, ctx: &Context) {
    let name_option = command
        .data
        .options
        .iter()
        .find(|opt| opt.name == "name")
        .expect("Expected name option");
    let name = name_option.value.as_str().expect("Expected string value for name option");
    let result = insert_alpacahack_user(&name).unwrap();
    let data = CreateInteractionResponseMessage::new().content(result);
    let builder = CreateInteractionResponse::Message(data);
    if let Err(why) = command.create_response(&ctx.http, builder).await {
        println!("Cannot respond to slash command: {why}");
    }
}

pub async fn del_alpaca_command(command: &CommandInteraction, ctx: &Context) {
    let name_option = command
        .data
        .options
        .iter()
        .find(|opt| opt.name == "name")
        .expect("Expected name option");
    let name = name_option.value.as_str().expect("Expected string value for name option");
    let result = delete_alpacahack_user(&name).unwrap();
    let data = CreateInteractionResponseMessage::new().content(result);
    let builder = CreateInteractionResponse::Message(data);
    if let Err(why) = command.create_response(&ctx.http, builder).await {
        println!("Cannot respond to slash command: {why}");
    }
}

pub async fn show_alpaca_command(command: &CommandInteraction, ctx: &Context) {
    let users = get_all_alpacahack_users().unwrap();
    let content = if users.is_empty() {
        "No users registered".to_string()
    } else {
        users.join("\n")
    };
    let data = CreateInteractionResponseMessage::new().content(content);
    let builder = CreateInteractionResponse::Message(data);
    if let Err(why) = command.create_response(&ctx.http, builder).await {
        println!("Cannot respond to slash command: {why}");
    }
}

pub async fn show_alpaca_score_command(command: &CommandInteraction, ctx: &Context) {
    let data = CreateInteractionResponseMessage::new().content("🔄 AlpacaHackスコアを取得中...");
    let builder = CreateInteractionResponse::Message(data);
    if let Err(why) = command.create_response(&ctx.http, builder).await {
        println!("Cannot respond to slash command: {why}");
        return;
    }

    let users = get_all_alpacahack_users().unwrap();
    if users.is_empty() {
        let _data = CreateInteractionResponseMessage::new().content("誰も登録されていません");
        let builder = EditInteractionResponse::new().content("誰も登録されていません");
        if let Err(why) = command.edit_response(&ctx.http, builder).await {
            println!("Error sending message: {:?}", why);
        }
        return;
    }

    for user in users {
        let info = get_alpacahack_solves_scraped(&user).await.unwrap();
        let content = format!("## {}\n```\n{}\n```", user, info);
        let _data = CreateInteractionResponseMessage::new().content(content.clone());
        let builder = EditInteractionResponse::new().content(content);
        if let Err(why) = command.edit_response(&ctx.http, builder).await {
            println!("Error sending message: {:?}", why);
        }
        sleep(Duration::from_secs(1)).await; // Rate limiting
    }
}

pub fn register_alpacahack_commands(commands: &mut Vec<CreateCommand>) {
    commands.push(
        CreateCommand::new("add_alpaca")
            .description("Add an AlpacaHack user")
            .add_option(
                CreateCommandOption::new(
                    CommandOptionType::String,
                    "name",
                    "The username to add",
                )
                .required(true),
            ),
    );
    commands.push(
        CreateCommand::new("del_alpaca")
            .description("Delete an AlpacaHack user")
            .add_option(
                CreateCommandOption::new(
                    CommandOptionType::String,
                    "name",
                    "The username to delete",
                )
                .required(true),
            ),
    );
    commands.push(
        CreateCommand::new("show_alpaca").description("Show all AlpacaHack users"),
    );
    commands.push(
        CreateCommand::new("show_alpaca_score").description("Show scores for all tracked AlpacaHack users"),
    );
}
