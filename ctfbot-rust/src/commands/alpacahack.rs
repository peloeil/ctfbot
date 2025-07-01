use serenity::builder::{CreateCommand, CreateCommandOption, CreateInteractionResponseMessage, CreateInteractionResponse};
use serenity::model::application::{CommandOptionType, CommandInteraction};
use serenity::prelude::*;
use crate::services::alpacahack_service::{insert_alpacahack_user, delete_alpacahack_user, get_all_alpacahack_users};

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
}
