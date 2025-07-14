use std::env;
use std::sync::Arc;

use serenity::prelude::*;
use tokio::sync::Mutex;

mod commands;
mod handler;
mod models;
mod services;
mod tasks;
mod database;

#[tokio::main]
async fn main() {
    dotenv::dotenv().expect("Failed to load .env file");
    tracing_subscriber::fmt::init();

    let token = env::var("DISCORD_TOKEN").expect("Expected a token in the environment");

    let intents = GatewayIntents::GUILD_MESSAGES
        | GatewayIntents::DIRECT_MESSAGES
        | GatewayIntents::MESSAGE_CONTENT
        | GatewayIntents::GUILD_MESSAGE_REACTIONS;

    let mut client = Client::builder(&token, intents)
        .event_handler(handler::Handler)
        .await
        .expect("Err creating client");

    {
        let mut data = client.data.write().await;
        let conn = database::init_db().expect("Failed to initialize database.");
        data.insert::<models::DatabaseConnection>(Arc::new(Mutex::new(conn)));
    }

    if let Err(why) = client.start().await {
        println!("Client error: {:?}", why);
    }
}
