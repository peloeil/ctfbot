use serenity::async_trait;
use serenity::model::application::Interaction;
use serenity::model::gateway::Ready;
use serenity::prelude::*;
use std::env;

use crate::commands;
use crate::services::alpacahack_service::create_alpacahack_user_table_if_not_exists;
use crate::tasks::{spawn_alpacahack_task, spawn_ctftime_task};

pub struct Handler;

#[async_trait]
impl EventHandler for Handler {
    async fn interaction_create(&self, ctx: Context, interaction: Interaction) {
        if let Interaction::Command(command) = interaction {
            commands::handle_command(&command, &ctx).await;
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
            .set_commands(&ctx.http, commands::register_all_commands())
            .await;

        if let Err(why) = commands {
            println!("Failed to create commands: {why}");
        }

        spawn_ctftime_task(ctx.clone());
        spawn_alpacahack_task(ctx.clone());
    }
}
