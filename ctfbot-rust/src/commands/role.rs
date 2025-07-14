use serenity::builder::{CreateCommand, CreateCommandOption, CreateInteractionResponseMessage, CreateInteractionResponse, EditRole};
use serenity::model::application::{CommandInteraction, CommandOptionType, CommandDataOptionValue};
use serenity::model::prelude::{ReactionType, RoleId, MessageId};
use serenity::prelude::*;

use crate::database;
use crate::models::DatabaseConnection;

pub fn register_role_commands(commands: &mut Vec<CreateCommand>) {
    commands.push(
        CreateCommand::new("role")
            .description("Manage roles")
            .add_option(
                CreateCommandOption::new(CommandOptionType::SubCommand, "create", "Create a new role")
                    .add_sub_option(CreateCommandOption::new(CommandOptionType::String, "name", "The name of the role").required(true))
            )
            .add_option(
                CreateCommandOption::new(CommandOptionType::SubCommand, "purge", "Remove a role from all members")
                    .add_sub_option(CreateCommandOption::new(CommandOptionType::Role, "role", "The role to remove").required(true))
            )
            .add_option(
                CreateCommandOption::new(CommandOptionType::SubCommand, "event", "Create a reaction role event")
                    .add_sub_option(CreateCommandOption::new(CommandOptionType::Role, "role", "The role to assign").required(true))
                    .add_sub_option(CreateCommandOption::new(CommandOptionType::String, "emoji", "The emoji to react with").required(true))
                    .add_sub_option(CreateCommandOption::new(CommandOptionType::String, "message", "The message to post").required(true))
            )
            .add_option(
                CreateCommandOption::new(CommandOptionType::SubCommand, "event_delete", "Delete a reaction role event")
                    .add_sub_option(CreateCommandOption::new(CommandOptionType::String, "message_id", "The message ID of the event").required(true))
                    .add_sub_option(CreateCommandOption::new(CommandOptionType::String, "emoji", "The emoji of the event").required(true))
            )
    );
}

pub async fn handle_role_command(command: &CommandInteraction, ctx: &Context) {
    let sub_command = command.data.options.first().unwrap();
    if let CommandDataOptionValue::SubCommand(options) = &sub_command.value {
        match sub_command.name.as_str() {
            "create" => create_role(command, ctx, options).await,
            "purge" => purge_role(command, ctx, options).await,
            "event" => create_event(command, ctx, options).await,
            "event_delete" => delete_event(command, ctx, options).await,
            _ => println!("Unknown subcommand"),
        }
    }
}

async fn create_role(command: &CommandInteraction, ctx: &Context, options: &Vec<serenity::model::application::CommandDataOption>) {
    let guild = command.guild_id.unwrap();
    let name = options.iter().find(|opt| opt.name == "name").and_then(|opt| opt.value.as_str()).unwrap_or_default();

    let builder = EditRole::new().name(name);
    match guild.create_role(&ctx.http, builder).await {
        Ok(role) => {
            let data = CreateInteractionResponseMessage::new().content(format!("Created role {}", role.name));
            let builder = CreateInteractionResponse::Message(data);
            command.create_response(&ctx.http, builder).await.unwrap();
        }
        Err(why) => {
            println!("Failed to create role: {:?}", why);
            let content = format!("Failed to create role. Make sure the bot has the 'Manage Roles' permission.\nError: {}", why);
            let data = CreateInteractionResponseMessage::new().content(content);
            let builder = CreateInteractionResponse::Message(data);
            command.create_response(&ctx.http, builder).await.unwrap();
        }
    }
}

async fn purge_role(command: &CommandInteraction, ctx: &Context, options: &Vec<serenity::model::application::CommandDataOption>) {
    let guild_id = command.guild_id.unwrap();
    let role_id = options.iter().find(|opt| opt.name == "role").and_then(|opt| opt.value.as_role_id()).unwrap();

    let members = guild_id.members(&ctx.http, None, None).await.unwrap();
    for member in members {
        if member.roles.contains(&role_id) {
            if let Err(why) = member.remove_role(&ctx.http, role_id).await {
                println!("Failed to remove role from member {}: {:?}", member.user.id, why);
            }
        }
    }

    let data = CreateInteractionResponseMessage::new().content(format!("Purged role <@&{}>", role_id));
    let builder = CreateInteractionResponse::Message(data);
    command.create_response(&ctx.http, builder).await.unwrap();
}

async fn create_event(command: &CommandInteraction, ctx: &Context, options: &Vec<serenity::model::application::CommandDataOption>) {
    let role_id = options.iter().find(|opt| opt.name == "role").and_then(|opt| opt.value.as_role_id()).unwrap();
    let emoji_str = options.iter().find(|opt| opt.name == "emoji").and_then(|opt| opt.value.as_str()).unwrap_or_default();
    let message_content = options.iter().find(|opt| opt.name == "message").and_then(|opt| opt.value.as_str()).unwrap_or_default();

    let message = command.channel_id.say(&ctx.http, message_content).await.unwrap();
    let emoji: ReactionType = emoji_str.parse().unwrap();
    message.react(&ctx.http, emoji).await.unwrap();

    let data = ctx.data.read().await;
    let db_conn = data.get::<DatabaseConnection>().unwrap();
    let conn = db_conn.lock().await;

    database::add_reaction_role(&conn, message.id, role_id, emoji_str).unwrap();

    let data = CreateInteractionResponseMessage::new().content("Created reaction role event.");
    let builder = CreateInteractionResponse::Message(data);
    command.create_response(&ctx.http, builder).await.unwrap();
}

async fn delete_event(command: &CommandInteraction, ctx: &Context, options: &Vec<serenity::model::application::CommandDataOption>) {
    let message_id_str = options.iter().find(|opt| opt.name == "message_id").and_then(|opt| opt.value.as_str()).unwrap_or_default();
    let emoji_str = options.iter().find(|opt| opt.name == "emoji").and_then(|opt| opt.value.as_str()).unwrap_or_default();
    
    let message_id = match message_id_str.parse::<u64>() {
        Ok(id) => MessageId::new(id),
        Err(_) => {
            let data = CreateInteractionResponseMessage::new().content("Invalid message ID.");
            let builder = CreateInteractionResponse::Message(data);
            command.create_response(&ctx.http, builder).await.unwrap();
            return;
        }
    };

    let data = ctx.data.read().await;
    let db_conn = data.get::<DatabaseConnection>().unwrap();
    let conn = db_conn.lock().await;

    match database::remove_reaction_role(&conn, message_id, emoji_str) {
        Ok(_) => {
            let data = CreateInteractionResponseMessage::new().content("Reaction role event deleted.");
            let builder = CreateInteractionResponse::Message(data);
            command.create_response(&ctx.http, builder).await.unwrap();
        }
        Err(e) => {
            println!("Failed to delete reaction role: {}", e);
            let data = CreateInteractionResponseMessage::new().content("Failed to delete reaction role event.");
            let builder = CreateInteractionResponse::Message(data);
            command.create_response(&ctx.http, builder).await.unwrap();
        }
    }
}