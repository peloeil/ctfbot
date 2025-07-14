use serenity::async_trait;
use serenity::model::application::Interaction;
use serenity::model::gateway::Ready;
use serenity::model::prelude::{Reaction, GuildId};
use serenity::prelude::*;
use std::env;

use crate::commands;
use crate::tasks::{spawn_alpacahack_task, spawn_ctftime_task};
use crate::models::DatabaseConnection;
use crate::database;

pub struct Handler;

#[async_trait]
impl EventHandler for Handler {
    async fn reaction_add(&self, ctx: Context, reaction: Reaction) {
        let data = ctx.data.read().await;
        let db_conn = data.get::<DatabaseConnection>().unwrap();
        let conn = db_conn.lock().await;

        if let Ok(Some(role_id)) = database::get_reaction_role(&conn, reaction.message_id, &reaction.emoji.to_string()) {
            if let Some(guild_id) = reaction.guild_id {
                if let Ok(member) = guild_id.member(&ctx.http, reaction.user_id.unwrap()).await {
                    if let Err(why) = member.add_role(&ctx.http, role_id).await {
                        println!("Failed to add role: {:?}", why);
                    }
                }
            }
        }
    }

    async fn reaction_remove(&self, ctx: Context, reaction: Reaction) {
        let data = ctx.data.read().await;
        let db_conn = data.get::<DatabaseConnection>().unwrap();
        let conn = db_conn.lock().await;

        if let Ok(Some(role_id)) = database::get_reaction_role(&conn, reaction.message_id, &reaction.emoji.to_string()) {
            if let Some(guild_id) = reaction.guild_id {
                if let Ok(member) = guild_id.member(&ctx.http, reaction.user_id.unwrap()).await {
                    if let Err(why) = member.remove_role(&ctx.http, role_id).await {
                        println!("Failed to remove role: {:?}", why);
                    }
                }
            }
        }
    }

    async fn interaction_create(&self, ctx: Context, interaction: Interaction) {
        if let Interaction::Command(command) = interaction {
            commands::handle_command(&command, &ctx).await;
        }
    }

    async fn ready(&self, ctx: Context, ready: Ready) {
        println!("{} is connected!", ready.user.name);

        

        let guild_id = GuildId::new(
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

