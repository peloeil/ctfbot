use serde::Deserialize;
use serenity::prelude::TypeMapKey;
use rusqlite::Connection;
use std::sync::Arc;
use tokio::sync::Mutex;


pub struct DatabaseConnection;

impl TypeMapKey for DatabaseConnection {
    type Value = Arc<Mutex<Connection>>;
}

#[derive(Deserialize, Debug)]
pub struct CtfEvent {
    pub title: String,
    pub start: String,
    pub finish: String,
    pub ctftime_url: String,
}

#[derive(Deserialize, Debug)]
pub struct AlpacaHackInfo {
    // Define the structure of the AlpacaHack API response
}
