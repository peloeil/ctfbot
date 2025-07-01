use regex::Regex;
use serenity::builder::{CreateCommand, CreateCommandOption, CreateInteractionResponseMessage, CreateInteractionResponse};
use serenity::model::application::{CommandOptionType, CommandInteraction};
use serenity::prelude::*;

pub async fn echo_command(command: &CommandInteraction, ctx: &Context) {
    let message_option = command
        .data
        .options
        .iter()
        .find(|opt| opt.name == "message")
        .expect("Expected message option");
    let value = message_option.value.as_str().expect("Expected string value for message option");
    let data = CreateInteractionResponseMessage::new().content(value.to_string());
    let builder = CreateInteractionResponse::Message(data);
    if let Err(why) = command.create_response(&ctx.http, builder).await {
        println!("Cannot respond to slash command: {why}");
    }
}

pub async fn pin_unpin_command(command: &CommandInteraction, ctx: &Context) {
    let link_option = command
        .data
        .options
        .iter()
        .find(|opt| opt.name == "link")
        .expect("Expected link option");
    let link = link_option.value.as_str().expect("Expected string value for link option");
        let re = Regex::new(r"^https://discord.com/channels/(\d+)/(\d+)/(\d+)$").unwrap();
        let caps = re.captures(&link).unwrap();

        let channel_id = caps.get(2).unwrap().as_str().parse::<u64>().unwrap();
        let message_id = caps.get(3).unwrap().as_str().parse::<u64>().unwrap();

        let channel = serenity::model::id::ChannelId::new(channel_id);

        match command.data.name.as_str() {
            "pin" => {
                if let Err(why) = channel.pin(&ctx.http, message_id).await {
                    println!("Cannot pin message: {why}");
                }
            }
            "unpin" => {
                if let Err(why) = channel.unpin(&ctx.http, message_id).await {
                    println!("Cannot unpin message: {why}");
                }
            }
            _ => unreachable!(),
        }

        let data = CreateInteractionResponseMessage::new()
            .content(format!("{} message", command.data.name));
        let builder = CreateInteractionResponse::Message(data);
        if let Err(why) = command.create_response(&ctx.http, builder).await {
            println!("Cannot respond to slash command: {why}");
        }
    }
pub fn register_general_commands(commands: &mut Vec<CreateCommand>) {
    commands.push(
        CreateCommand::new("echo")
            .description("Echo back a message")
            .add_option(
                CreateCommandOption::new(
                    CommandOptionType::String,
                    "message",
                    "The message to echo back",
                )
                .required(true),
            ),
    );
    commands.push(
        CreateCommand::new("pin")
            .description("Pin a message")
            .add_option(
                CreateCommandOption::new(
                    CommandOptionType::String,
                    "link",
                    "The message link to pin",
                )
                .required(true),
            ),
    );
    commands.push(
        CreateCommand::new("unpin")
            .description("Unpin a message")
            .add_option(
                CreateCommandOption::new(
                    CommandOptionType::String,
                    "link",
                    "The message link to unpin",
                )
                .required(true),
            ),
    );
}
