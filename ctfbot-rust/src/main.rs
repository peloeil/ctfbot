use std::env;

use chrono::{Datelike, Timelike, Utc};
use regex::Regex;
use rusqlite::{Connection, Result};
use serde::Deserialize;
use serenity::async_trait;
use serenity::builder::{CreateCommand, CreateCommandOption, CreateEmbed, CreateEmbedFooter, CreateInteractionResponseMessage, CreateInteractionResponse, CreateMessage};
use serenity::model::application::{CommandOptionType, Interaction};
use serenity::model::gateway::Ready;
use serenity::prelude::*;
use tokio::time::{sleep, Duration};

#[derive(Deserialize, Debug)]
struct CtfEvent {
    title: String,
    start: String,
    finish: String,
    ctftime_url: String,
}

#[derive(Deserialize, Debug)]
struct AlpacaHackInfo {
    // Define the structure of the AlpacaHack API response
}

async fn get_ctftime_events() -> Result<Vec<CtfEvent>, reqwest::Error> {
    let now = Utc::now();
    let start = now.to_rfc3339();
    let end = (now + chrono::Duration::weeks(2)).to_rfc3339();
    let url = format!(
        "https://ctftime.org/api/v1/events/?limit=20&start={}&end={}",
        start,
        end
    );
    let events = reqwest::get(&url).await?.json::<Vec<CtfEvent>>().await?;
    Ok(events)
}

async fn get_alpacahack_info(user: &str) -> Result<Vec<AlpacaHackInfo>, reqwest::Error> {
    let url = format!("https://alpacahack.com/api/user/{}/solves", user);
    let info = reqwest::get(&url).await?.json::<Vec<AlpacaHackInfo>>().await?;
    Ok(info)
}

fn create_alpacahack_user_table_if_not_exists() -> Result<()> {
    let conn = Connection::open("alpacahack.db")?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS alpacahack_users (name TEXT NOT NULL UNIQUE)",
        [],
    )?;
    Ok(())
}

fn insert_alpacahack_user(name: &str) -> Result<String> {
    let conn = Connection::open("alpacahack.db")?;
    conn.execute("INSERT INTO alpacahack_users (name) VALUES (?1)", [name])?;
    Ok(format!("Added user: {}", name))
}

fn delete_alpacahack_user(name: &str) -> Result<String> {
    let conn = Connection::open("alpacahack.db")?;
    conn.execute("DELETE FROM alpacahack_users WHERE name = ?1", [name])?;
    Ok(format!("Deleted user: {}", name))
}

fn get_all_alpacahack_users() -> Result<Vec<String>> {
    let conn = Connection::open("alpacahack.db")?;
    let mut stmt = conn.prepare("SELECT name FROM alpacahack_users")?;
    let mut rows = stmt.query([])?;
    let mut users = Vec::new();
    while let Some(row) = rows.next()? {
        users.push(row.get(0)?);
    }
    Ok(users)
}

struct Handler;

#[async_trait]
impl EventHandler for Handler {
    async fn interaction_create(&self, ctx: Context, interaction: Interaction) {
        if let Interaction::Command(command) = interaction {
            match command.data.name.as_str() {
                "echo" => {
                    let message = command
                        .data
                        .options
                        .iter()
                        .find(|opt| opt.name == "message")
                        .cloned();
                    if let Some(message) = message {
                        if let Some(value) = message.value.as_str() {
                            let data = CreateInteractionResponseMessage::new().content(value.to_string());
                            let builder = CreateInteractionResponse::Message(data);
                            if let Err(why) = command.create_response(&ctx.http, builder).await {
                                println!("Cannot respond to slash command: {why}");
                            }
                        }
                    }
                }
                "pin" | "unpin" => {
                    let link = command
                        .data
                        .options
                        .iter()
                        .find(|opt| opt.name == "link")
                        .cloned()
                        .unwrap();

                    if let Some(link) = link.value.as_str() {
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
                }
                "add_alpaca" => {
                    let name = command
                        .data
                        .options
                        .iter()
                        .find(|opt| opt.name == "name")
                        .cloned()
                        .unwrap();
                    if let Some(name) = name.value.as_str() {
                        let result = insert_alpacahack_user(&name).unwrap();
                        let data = CreateInteractionResponseMessage::new().content(result);
                        let builder = CreateInteractionResponse::Message(data);
                        if let Err(why) = command.create_response(&ctx.http, builder).await {
                            println!("Cannot respond to slash command: {why}");
                        }
                    }
                }
                "del_alpaca" => {
                    let name = command
                        .data
                        .options
                        .iter()
                        .find(|opt| opt.name == "name")
                        .cloned()
                        .unwrap();
                    if let Some(name) = name.value.as_str() {
                        let result = delete_alpacahack_user(&name).unwrap();
                        let data = CreateInteractionResponseMessage::new().content(result);
                        let builder = CreateInteractionResponse::Message(data);
                        if let Err(why) = command.create_response(&ctx.http, builder).await {
                            println!("Cannot respond to slash command: {why}");
                        }
                    }
                }
                "show_alpaca" => {
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
                _ => {
                    let data = CreateInteractionResponseMessage::new()
                        .content("not implemented");
                    let builder = CreateInteractionResponse::Message(data);
                    if let Err(why) = command.create_response(&ctx.http, builder).await {
                        println!("Cannot respond to slash command: {why}");
                    }
                }
            };
        }
    }

    async fn ready(&self, ctx: Context, ready: Ready) {
        println!("{} is connected!", ready.user.name);

        create_alpacahack_user_table_if_not_exists().unwrap();

        let guild_id = serenity::model::id::GuildId::new(
            env::var("GUILD_ID")
                .expect("Expected GUILD_ID in environment")
                .parse()
                .expect("GUILD_ID must be an integer"),
        );

        let commands = guild_id
            .set_commands(
                &ctx.http,
                vec![
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
                    CreateCommand::new("show_alpaca").description("Show all AlpacaHack users"),
                ],
            )
            .await;

        if let Err(why) = commands {
            println!("Failed to create commands: {why}");
        }

        let ctx_ctftime = ctx.clone();
        tokio::spawn(async move {
            loop {
                let now = Utc::now();
                if now.weekday() == chrono::Weekday::Mon && now.hour() == 9 && now.minute() == 0 {
                    let events = get_ctftime_events().await.unwrap();
                    let channel_id = env::var("BOT_CHANNEL_ID")
                        .expect("Expected BOT_CHANNEL_ID in environment")
                        .parse::<u64>()
                        .unwrap();
                    let channel = serenity::model::id::ChannelId::new(channel_id);

                    let mut embed = CreateEmbed::new()
                        .title("Upcoming CTFs")
                        .description(format!("Found {} events", events.len()))
                        .footer(CreateEmbedFooter::new("Fetched from CTFtime"));

                    for event in events {
                        let start_time = event.start;
                        let end_time = event.finish;

                        let field_value = format!(
                            "**Start**: {}\n**End**: {}\n**Link**: [CTFtime]({})",
                            start_time,
                            end_time,
                            event.ctftime_url
                        );

                        embed = embed.field(event.title, field_value, false);
                    }

                    let builder = CreateMessage::new().embed(embed.clone());

                    if let Err(why) = channel.send_message(&ctx_ctftime.http, builder).await {
                        println!("Error sending message: {:?}", why);
                    }
                }
                sleep(Duration::from_secs(60)).await;
            }
        });

        let ctx_alpacahack = ctx.clone();
        tokio::spawn(async move {
            loop {
                let now = Utc::now();
                if now.hour() == 23 && now.minute() == 0 {
                    let users = get_all_alpacahack_users().unwrap();
                    let channel_id = env::var("BOT_CHANNEL_ID")
                        .expect("Expected BOT_CHANNEL_ID in environment")
                        .parse::<u64>()
                        .unwrap();
                    let channel = serenity::model::id::ChannelId::new(channel_id);

                    for user in users {
                        let info = get_alpacahack_info(&user).await.unwrap();
                        // Format and send the info to the channel
                    }
                }
                sleep(Duration::from_secs(60)).await;
            }
        });
    }
}

#[tokio::main]
async fn main() {
    dotenv::dotenv().expect("Failed to load .env file");
    tracing_subscriber::fmt::init();

    let token = env::var("DISCORD_TOKEN").expect("Expected a token in the environment");

    let intents = GatewayIntents::GUILD_MESSAGES
        | GatewayIntents::DIRECT_MESSAGES
        | GatewayIntents::MESSAGE_CONTENT;

    let mut client = Client::builder(&token, intents)
        .event_handler(Handler)
        .await
        .expect("Err creating client");

    if let Err(why) = client.start().await {
        println!("Client error: {:?}", why);
    }
}
