use std::env;
use chrono::{Datelike, Timelike, Utc};
use serenity::builder::{CreateEmbed, CreateEmbedFooter, CreateMessage};
use serenity::prelude::*;
use tokio::time::{sleep, Duration};
use crate::services::ctftime_service::get_ctftime_events;
use crate::services::alpacahack_service::{get_all_alpacahack_users, get_alpacahack_info};

pub fn spawn_ctftime_task(ctx: Context) {
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

                if let Err(why) = channel.send_message(&ctx.http, builder).await {
                    println!("Error sending message: {:?}", why);
                }
            }
            sleep(Duration::from_secs(60)).await;
        }
    });
}

pub fn spawn_alpacahack_task(_ctx: Context) {
    tokio::spawn(async move {
        loop {
            let now = Utc::now();
            if now.hour() == 23 && now.minute() == 0 {
                let users = get_all_alpacahack_users().unwrap();
                let channel_id = env::var("BOT_CHANNEL_ID")
                    .expect("Expected BOT_CHANNEL_ID in environment")
                    .parse::<u64>()
                    .unwrap();
                let _channel = serenity::model::id::ChannelId::new(channel_id);

                for user in users {
                    let _info = get_alpacahack_info(&user).await.unwrap();
                    // Format and send the info to the channel
                }
            }
            sleep(Duration::from_secs(60)).await;
        }
    });
}
