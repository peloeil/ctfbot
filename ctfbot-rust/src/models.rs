
use serde::Deserialize;

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
